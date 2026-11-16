"""Scan the whole git history before the repo goes public.

(a) secrets, with the pinned gitleaks: every commit's diff, then every commit and tag message
with its author, committer or tagger; (b) paths outside the committed allowlist, plus env files
and machine-local Claude Code files; (c) on the owner's PC only (CI passes --ci), every word,
email, author, committer, tagger, file name and tag name compared with the hashed private word
list, plus private path markers read from .git/info/exclude at run time.

A report never shows a private word, a marker or the line it was found on: only the commit or
tag, the place ("message", "author", a file) and the entry number. Markers hide labels in
every mode.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from privacy_words import SETTING, load_hashes, normalize, split_tokens, words_file
from privacy_words import tokens as tokens
from reviewed_binaries import BinaryBlob, binary_blobs, load_reviewed, reviewed_file

HERE = Path(__file__).resolve().parent
ALLOWLIST = HERE / "public_paths.txt"
GITLEAKS_PIN = HERE / "gitleaks.pin"
PINNED_GITLEAKS = HERE.parent / ".tools" / "bin" / "gitleaks"
# Only gitleaks' own rules: no config or ignore file from the repo, the folder or the environment.
GITLEAKS_CONFIG = "[extend]\nuseDefault = true\n"
HIDDEN = "(path hidden)"
GITLEAKS_ERRORED = "gitleaks reported an error: secrets not fully checked"
GITLEAKS_READ_NOTHING = "gitleaks read no commits: secrets not checked"

_DIFF_HEADER = re.compile(r"^diff --git ", re.MULTILINE)
# gitleaks' log lines: "12:43PM ERR [git] fatal: …" and "12:43PM INF 3 commits scanned."
_GITLEAKS_ERROR = re.compile(r"^(?:\S+ )?ERR\b", re.MULTILINE)
_COMMITS_SCANNED = re.compile(r"\b(\d+) commits scanned\b")
_STATUS = re.compile(r"[ADMT]")
# Git LFS keeps file content outside the history, where no check can read it.
_LFS_ATTRIBUTE = re.compile(r"^[+-][^\n]*\bfilter=lfs\b", re.MULTILINE)
_LFS_POINTER = re.compile(r"^[+-]version https://git-lfs\.github\.com/spec/v1\b", re.MULTILINE)
# Claude Code makes a .claude/ folder wherever a session starts, so these are refused anywhere.
_MACHINE_LOCAL = re.compile(r"(?:^|/)\.claude/(?:settings\.local\.json$|worktrees/)")
# The same options for the file list and the diffs, so both list the same files in the same
# order whatever the user's diff settings (order file, relative paths, colour).
_DIFF_OPTIONS = (
    "--diff-merges=first-parent",
    "--no-renames",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-relative",
    "-O/dev/null",
)

Check = Literal["secrets", "paths", "words", "markers"]


@dataclass(frozen=True)
class Finding:
    check: Check
    where: str
    detail: str


@dataclass
class History:
    paths: set[str]
    chunks: list[tuple[str, str]]
    binaries: list[BinaryBlob]
    unpaired: list[str]
    # (file name, label, text) for the gitleaks scan of messages and identities.
    messages: list[tuple[str, str, str]]
    # (where, detail) for every sign of Git LFS.
    lfs: list[tuple[str, str]]
    # The place of every text that is not UTF-8 (a note, not a finding).
    not_utf8: list[str]


def private_markers(exclude_text: str, gitignore_text: str) -> list[str]:
    """Entries of .git/info/exclude that .gitignore does not also hold, without the slashes.

    A .gitignore entry `**/x` (x in any folder) also holds the entry `x`.
    """
    ignored = {line.strip().removeprefix("**/").strip("/") for line in gitignore_text.splitlines()}
    markers: list[str] = []
    for raw in exclude_text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        marker = line.strip("/")
        if marker and marker not in ignored and marker not in markers:
            markers.append(marker)
    return markers


def _marker_hits(text: str, markers: Sequence[str]) -> list[int]:
    folded = normalize(text)
    return [n for n, marker in enumerate(markers, start=1) if normalize(marker) in folded]


def check_paths(
    paths: Iterable[str], allowed_top: frozenset[str], markers: Sequence[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(paths):
        hits = _marker_hits(path, markers)
        if hits:
            # Naming the path would print the marker.
            findings += [
                Finding("markers", "a committed path", f"path contains private marker #{n}")
                for n in hits
            ]
            continue
        basename = path.rsplit("/", 1)[-1]
        if basename.startswith(".env") and basename != ".env.example":
            findings.append(Finding("paths", path, "env file"))
        elif _MACHINE_LOCAL.search(path):
            findings.append(Finding("paths", path, "machine-local Claude Code file"))
        elif path.split("/", 1)[0] not in allowed_top:
            findings.append(Finding("paths", path, "top-level entry is not in the allowlist"))
    return findings


def check_text(
    where: str, text: str, hashes: Sequence[str], markers: Sequence[str]
) -> list[Finding]:
    folded = normalize(text)
    findings: list[Finding] = []
    if hashes:
        entry = {digest: n for n, digest in reversed(list(enumerate(hashes, start=1)))}
        hit = {
            entry[digest]
            for token in split_tokens(folded)
            if (digest := hashlib.sha256(token.encode("utf-8")).hexdigest()) in entry
        }
        findings += [Finding("words", where, f"private word #{n}") for n in sorted(hit)]
    findings += [
        Finding("markers", where, f"private marker #{n}")
        for n, marker in enumerate(markers, start=1)
        if normalize(marker) in folded
    ]
    return findings


def _git(repo: Path, *args: str, latin1: bool = False) -> str:
    """git's output as UTF-8 text, or (latin1) one character per byte, so nothing is lost."""
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "core.quotePath=false", "-c", "log.showRoot=true", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
    )
    if result.returncode != 0:
        raise OSError("git could not read the history")
    return result.stdout.decode("latin-1" if latin1 else "utf-8", errors="replace")


def text_views(latin1: str) -> tuple[list[str], bool]:
    """The ways to read text git printed one character per byte, and whether it was not UTF-8.

    Text that is not UTF-8 is read as UTF-8 with replacement characters (which can hide a
    word that holds an accented letter) and as Latin-1 (every byte is a character).
    """
    raw = latin1.encode("latin-1")
    try:
        return [raw.decode("utf-8")], False
    except UnicodeDecodeError:
        return [raw.decode("utf-8", errors="replace"), latin1], True


def _binary_files(repo: Path) -> list[BinaryBlob]:
    """Every change where git sees a binary blob (numstat prints '-' for it), with that blob."""
    log = _git(
        repo,
        "log",
        "--all",
        "--raw",
        "--numstat",
        "-z",
        "--no-abbrev",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        "--diff-merges=first-parent",
        "--format=%x1e%H",
    )
    return binary_blobs(log)


def _lfs_use(name: str, diff: str) -> str | None:
    """Why a file diff shows Git LFS: a pointer file, or an LFS filter in a .gitattributes."""
    if _LFS_POINTER.search(diff):
        return "Git LFS pointer file"
    attributes = name == HIDDEN or name.rsplit("/", 1)[-1] == ".gitattributes"
    if attributes and _LFS_ATTRIBUTE.search(diff):
        return "Git LFS is not allowed"
    return None


def names_by_commit(repo: Path, nonce: str) -> dict[str, list[str]]:
    """Each commit's file names, unquoted, in the order `git log -p` prints their diffs.

    A type change (a link that becomes a file) prints two diffs, so its name is listed twice.
    """
    head = f"\x1e{nonce}"
    log = _git(repo, "log", "--all", *_DIFF_OPTIONS, "--name-status", "-z", f"--format={head}%H")
    found: dict[str, list[str]] = {}
    names: list[str] = []
    # With -z, entries end in NUL and names are not quoted; a name is never stripped.
    entries = iter(log.split("\0"))
    for entry in entries:
        field = entry.removeprefix("\n")
        if field.startswith(head):
            names = found.setdefault(field[len(head) :], [])
        elif _STATUS.fullmatch(field):
            name = next(entries, None)
            if name is None:
                raise OSError("git listed a change without a file name")
            names += [name, name] if field == "T" else [name]
        elif field:
            raise OSError("git listed the changed files in an unexpected form")
    return found


def _tags(
    repo: Path, nonce: str
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]], list[str]]:
    """Chunks for every tag's name and, for an annotated tag, its message and tagger."""
    sep = f"\x1f{nonce}"
    fields = ("%(objecttype)", "%(objectname)", "%(refname)", "%(taggername) %(taggeremail)")
    fmt = f"%1e{nonce}" + "".join(f"{field}%1f{nonce}" for field in fields) + "%(contents)"
    listing = _git(repo, "for-each-ref", f"--format={fmt}", "refs/tags", latin1=True)
    chunks: list[tuple[str, str]] = []
    messages: list[tuple[str, str, str]] = []
    notes: list[str] = []

    def add(label: str, field: str) -> str:
        views, odd = text_views(field)
        chunks.extend((label, view) for view in views)
        if odd:
            notes.append(label)
        return views[0]

    for entry in listing.split(f"\x1e{nonce}")[1:]:
        parts = entry.split(sep)
        if len(parts) != len(fields) + 1:
            raise OSError("git printed a tag in an unexpected form")
        kind, sha, ref, tagger, contents = parts
        short = f"tag {sha[:7]}"
        # The label never holds the tag's name, so a word in it is never printed.
        add(f"{short} · name", ref.removeprefix("refs/tags/"))
        if kind == "tag":
            body = add(f"{short} · message", contents)
            who = add(f"{short} · tagger", tagger)
            messages.append((f"tag-{sha}.txt", f"{short} · message", f"{who}\n\n{body}"))
    return chunks, messages, notes


def read_history(repo: Path) -> History:
    """Paths ever committed, and one chunk per message, person, file diff and tag."""
    # A random marker per run ends each field, so no message or name can imitate one.
    nonce = secrets.token_hex(16)
    names = names_by_commit(repo, nonce)
    paths = {name for found in names.values() for name in found}
    sep = f"\x1f{nonce}"
    fields = ("%H", "%an", "%ae", "%cn", "%ce", "%B")
    log = _git(
        repo,
        "log",
        "--all",
        "-p",
        "--text",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        *_DIFF_OPTIONS,
        "--format=" + f"%x1e{nonce}" + "".join(f"{field}%x1f{nonce}" for field in fields),
        latin1=True,
    )
    chunks: list[tuple[str, str]] = []
    unpaired: list[str] = []
    messages: list[tuple[str, str, str]] = []
    lfs: list[tuple[str, str]] = []
    not_utf8: list[str] = []

    def add(label: str, field: str) -> str:
        views, odd = text_views(field)
        chunks.extend((label, view) for view in views)
        if odd:
            not_utf8.append(label)
        return views[0]

    for entry in log.split(f"\x1e{nonce}")[1:]:
        parts = entry.split(sep)
        if len(parts) != len(fields) + 1:
            raise OSError("git printed a commit in an unexpected form")
        sha, author, author_email, committer, committer_email, message, diff = parts
        short = f"commit {sha[:7]}"
        message = add(f"{short} · message", message)
        author = add(f"{short} · author", f"{author} {author_email}")
        committer = add(f"{short} · committer", f"{committer} {committer_email}")
        messages.append((f"{sha}.txt", f"{short} · message", f"{author}\n{committer}\n\n{message}"))
        # Labels come from the unquoted file list: a diff header C-quotes odd names.
        files = _DIFF_HEADER.split(diff)[1:]
        labels = names.get(sha, [])
        if len(labels) != len(files):
            unpaired.append(short)
            labels = [HIDDEN] * len(files)
        for label, part in zip(labels, files, strict=True):
            part = add(f"{short} · {label}", part)
            if (detail := _lfs_use(label, part)) is not None:
                lfs.append((f"{short} · {label}", detail))
    tag_chunks, tag_messages, tag_notes = _tags(repo, nonce)
    return History(
        paths,
        chunks + tag_chunks,
        _binary_files(repo),
        unpaired,
        messages + tag_messages,
        lfs,
        not_utf8 + tag_notes,
    )


def pinned_gitleaks_version() -> str:
    """The version scripts/gitleaks.pin names; install-tools.sh reads the same file."""
    for line in GITLEAKS_PIN.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "GITLEAKS_VERSION":
            return value.strip()
    raise ValueError("the gitleaks pin names no version")


def gitleaks_binary() -> str | None:
    """The pinned gitleaks in .tools/bin, else one on PATH (its version is checked before use)."""
    if PINNED_GITLEAKS.is_file():
        return str(PINNED_GITLEAKS)
    return shutil.which("gitleaks")


def _gitleaks_env() -> dict[str, str]:
    """The environment without GITLEAKS_* settings (GITLEAKS_CONFIG would replace the rules)."""
    return {key: value for key, value in os.environ.items() if not key.startswith("GITLEAKS_")}


def _gitleaks_scan(
    binary: str, work: Path, env: dict[str, str], *target: str
) -> tuple[list[Any], Finding | None, str]:
    """The leaks gitleaks reports for one target, the finding that says it failed (or None),
    and its log, which is never printed (it can hold paths)."""
    report = work / "report.json"
    report.unlink(missing_ok=True)
    result = subprocess.run(  # noqa: S603
        [
            binary,
            *target,
            "--config",
            str(work / "gitleaks.toml"),
            "--gitleaks-ignore-path",
            str(work / "no-ignore-file"),
            "--log-level",
            "info",
            "--redact",
            "--no-banner",
            "--no-color",
            "--exit-code",
            "2",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        capture_output=True,
        check=False,
        cwd=work,
        env=env,
    )
    log = result.stderr.decode("utf-8", errors="replace")
    leaks: list[Any] = []
    if result.returncode == 2 and report.is_file():
        leaks = json.loads(report.read_text(encoding="utf-8"))
    if result.returncode not in (0, 2) or (result.returncode == 2 and not leaks):
        return (
            leaks,
            Finding("secrets", "gitleaks", f"gitleaks failed (exit {result.returncode})"),
            log,
        )
    if _GITLEAKS_ERROR.search(log):
        # gitleaks logs a failed `git log` and carries on as if the history were empty.
        return leaks, Finding("secrets", "gitleaks", GITLEAKS_ERRORED), log
    return leaks, None, log


def run_gitleaks(repo: Path, messages: Sequence[tuple[str, str, str]] = ()) -> list[Finding]:
    """gitleaks over every commit's diff, then over the messages and identities it never reads."""
    binary = gitleaks_binary()
    if binary is None:
        return [Finding("secrets", "gitleaks", "gitleaks not found: run make tools")]
    try:
        pinned = pinned_gitleaks_version()
        git_dir = _git(repo, "rev-parse", "--absolute-git-dir").strip()
        commits = int(_git(repo, "rev-list", "--all", "--count").strip())
    except (OSError, ValueError):
        return [Finding("secrets", "gitleaks", "cannot read the gitleaks pin or the git folder")]
    version = subprocess.run(  # noqa: S603
        [binary, "version"], capture_output=True, check=False, env=_gitleaks_env()
    )
    if version.returncode != 0 or version.stdout.decode(errors="replace").strip() != pinned:
        return [Finding("secrets", "gitleaks", "not the pinned gitleaks: run make tools")]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "gitleaks.toml").write_text(GITLEAKS_CONFIG, encoding="utf-8")
        (work / "no-ignore-file").mkdir()
        (work / "source").mkdir()
        folder = work / "messages"
        folder.mkdir()
        label_of: dict[str, str] = {}
        for name, label, text in messages:
            (folder / name).write_text(text, encoding="utf-8")
            label_of[name] = label

        # gitleaks reads a .gitleaksignore in the folder it scans, whatever
        # --gitleaks-ignore-path says, so it scans an empty folder and finds the history
        # through an absolute GIT_DIR. That also replaces a relative GIT_DIR from the caller
        # (`git --git-dir=.git push`), and git accepts it under safe.bareRepository=explicit.
        git_env = {**_gitleaks_env(), "GIT_DIR": git_dir}
        leaks, problem, log = _gitleaks_scan(binary, work, git_env, "git", str(work / "source"))
        findings = [
            Finding(
                "secrets",
                f"commit {str(leak.get('Commit', ''))[:7]} · {leak.get('File', '')}",
                str(leak.get("RuleID", "secret")),
            )
            for leak in leaks
        ]
        scanned = _COMMITS_SCANNED.search(log)
        if problem is None and commits and (scanned is None or int(scanned[1]) == 0):
            problem = Finding("secrets", "gitleaks", GITLEAKS_READ_NOTHING)
        if problem is not None:
            return [*findings, problem]
        if not messages:
            return findings
        leaks, problem, _ = _gitleaks_scan(binary, work, _gitleaks_env(), "dir", str(folder))
    findings += [
        Finding(
            "secrets",
            label_of.get(Path(str(leak.get("File", ""))).name, "a message"),
            str(leak.get("RuleID", "secret")),
        )
        for leak in leaks
    ]
    return [*findings, problem] if problem is not None else findings


def read_allowlist() -> frozenset[str]:
    """The top-level entries a public repo may hold (scripts/public_paths.txt)."""
    lines = ALLOWLIST.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip())


def read_markers(repo: Path) -> list[str]:
    exclude = Path(_git(repo, "rev-parse", "--git-path", "info/exclude").strip())
    exclude = exclude if exclude.is_absolute() else repo / exclude
    exclude_text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    ignore = repo / ".gitignore"
    ignore_text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    return private_markers(exclude_text, ignore_text)


def load_markers(repo: Path) -> tuple[list[str], list[Finding]]:
    """The private markers, or the one finding that says why they can't be read."""
    try:
        return read_markers(repo), []
    except UnicodeDecodeError:
        reason = "not UTF-8 text"
    except OSError as exc:
        reason = exc.strerror or "unreadable"
    return [], _fail("markers", "private markers", f"cannot read the exclude file: {reason}")


def _fail(check: Check, where: str, detail: str) -> list[Finding]:
    return [Finding(check, where, detail)]


def load_private_hashes(repo: Path) -> tuple[list[str], list[Finding]]:
    """The private hashes, or the one finding that says why they can't be used."""
    try:
        path = words_file(repo)
        if path is None:
            return [], _fail(
                "words", "private word list", f"{SETTING} is not set: run make private-words"
            )
        hashes = load_hashes(path)
    except FileNotFoundError:
        return [], _fail("words", "private word list", "missing: run make private-words")
    except UnicodeDecodeError:
        return [], _fail("words", "private word list", f"cannot use {SETTING}: not UTF-8 text")
    except OSError as exc:
        return [], _fail("words", "private word list", f"cannot use {SETTING}: {exc.strerror}")
    except ValueError as exc:
        number = re.match(r"line (\d+) ", str(exc))
        what = f"private word list line {number[1]} is malformed" if number else "malformed"
        return [], _fail("words", "private word list", what)
    if not hashes:
        return [], _fail("words", "private word list", "empty: run make private-words")
    return hashes, []


def load_reviewed_list(repo: Path) -> tuple[dict[str, str], list[Finding]]:
    """The reviewed binaries (none when there is no list yet), or the finding that says why not."""
    where = "reviewed binaries list"
    try:
        path = reviewed_file(repo)
        if path is None or not path.exists():
            return {}, []
        return load_reviewed(path), []
    except UnicodeDecodeError:
        return {}, _fail("words", where, f"cannot use the {where}: not UTF-8 text")
    except OSError as exc:
        return {}, _fail("words", where, f"cannot use the {where}: {exc.strerror}")
    except ValueError as exc:
        number = re.match(r"line (\d+) ", str(exc))
        what = f"{where} line {number[1]} is malformed" if number else f"{where} is malformed"
        return {}, _fail("words", where, what)


def hide_if_private(name: str, hashes: Sequence[str], markers: Sequence[str]) -> str:
    """Hide a file name that holds a private word or marker."""
    return HIDDEN if check_text("", name, hashes, markers) else name


def scrub(where: str, hashes: Sequence[str], markers: Sequence[str]) -> str:
    head, sep, name = where.partition(" · ")
    if not sep or name in {"message", "author", "committer", "tagger", "name"}:
        return where
    return f"{head}{sep}{hide_if_private(name, hashes, markers)}"


def _note_place(where: str) -> str:
    """A file's path, or the label of a message, person or tag."""
    _, sep, name = where.partition(" · ")
    return (
        where if not sep or name in {"message", "author", "committer", "tagger", "name"} else name
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan the git history before the repo goes public."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: skip the private word list and the marker text scan (no list in CI)",
    )
    args = parser.parse_args(argv)
    repo: Path = args.repo.resolve()
    local = not args.ci

    hashes: list[str] = []
    word_problem: list[Finding] = []
    reviewed: dict[str, str] = {}
    if local:
        hashes, word_problem = load_private_hashes(repo)
        reviewed, reviewed_problem = load_reviewed_list(repo)
        word_problem += reviewed_problem
    # Markers hide labels in every mode (a CI checkout's exclude file holds none).
    markers, marker_problem = load_markers(repo)

    try:
        history = read_history(repo)
    except OSError:
        print("public-check: cannot read the history")
        return 1
    allowed = read_allowlist()

    secrets_found = [
        Finding(f.check, scrub(f.where, hashes, markers), f.detail)
        for f in run_gitleaks(repo, history.messages)
    ]
    paths_found = check_paths(history.paths, allowed, markers)
    paths_found = [
        Finding(f.check, hide_if_private(f.where, hashes, markers), f.detail) for f in paths_found
    ]
    words_found: list[Finding] = list(word_problem)
    if local:
        words_found += [
            Finding(
                "words",
                scrub(f"commit {binary.commit[:7]} · {binary.path}", hashes, markers),
                "binary file not scanned",
            )
            for binary in history.binaries
            if binary.blob not in reviewed
        ]
        words_found += [
            Finding("words", where, "file names and diff do not line up: names hidden")
            for where in history.unpaired
        ]
        # The diff headers C-quote odd names (a tab, a quote), which hides a word in them.
        for path in sorted(history.paths):
            words_found += check_text(HIDDEN, path, hashes, [])
        for where, text in history.chunks:
            found = check_text(scrub(where, hashes, markers), text, hashes, markers)
            words_found += found

    marker_paths = marker_problem + [f for f in paths_found if f.check == "markers"]
    # Git LFS fails in every mode: CI can't read LFS content either.
    lfs_found = [Finding("paths", scrub(where, hashes, markers), d) for where, d in history.lfs]
    paths_only = [f for f in paths_found if f.check == "paths"] + lfs_found
    sections: list[tuple[str, list[Finding]]] = [("secrets", secrets_found)]
    if local:
        sections.append(("paths", paths_only))
        sections.append(("words", [f for f in words_found if f.check == "words"]))
        sections.append(
            ("markers", marker_paths + [f for f in words_found if f.check == "markers"])
        )
    else:
        # The text scan is skipped, but a marker path (hidden) still fails the paths check.
        sections.append(("paths", paths_only + marker_paths))
    total = sum(len(found) for _, found in sections)
    for name, found in sections:
        ok = (
            f"ok ({len(markers)} marker{'' if len(markers) == 1 else 's'})"
            if name == "markers"
            else "ok"
        )
        print(f"{name}: {ok if not found else f'{len(found)} finding(s)'}")
        for finding in found:
            print(f"  {finding.where}: {finding.detail}")
    # A note, never a finding: the path (hidden when private), never the content.
    for note in sorted({_note_place(scrub(where, hashes, markers)) for where in history.not_utf8}):
        print(f"not UTF-8: {note}")
    if local:
        accepted = {binary.blob for binary in history.binaries if binary.blob in reviewed}
        print(f"accepted binaries: {len(accepted)}")
    else:
        print("words: SKIPPED (local only)")
        print("markers: SKIPPED (local only)")
    print("public-check: PASS" if total == 0 else f"public-check: FAIL ({total} findings)")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
