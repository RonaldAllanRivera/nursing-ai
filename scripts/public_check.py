"""Scan the whole git history before the repo goes public.

(a) secrets, with gitleaks; (b) paths outside the committed allowlist, plus env files;
(c) on the owner's PC only, every word, email, author and committer compared with the hashed
private word list, plus private path markers read from .git/info/exclude at run time.

A report never shows a private word, a marker or the line it was found on: only the commit,
the place ("message", "author", a file) and the entry number.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from privacy_words import SETTING, load_hashes, normalize, words_file

HERE = Path(__file__).resolve().parent
ALLOWLIST = HERE / "public_paths.txt"
HIDDEN = "(path hidden)"

_TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[^\W\d_]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LETTERS = re.compile(r"[^\W\d_]+")
_COMMIT_START = re.compile(r"\x1e(?=[0-9a-f]{40,64}\x1f)")
_DIFF_HEADER = re.compile(r"^diff --git ", re.MULTILINE)
_SAME_PATH = re.compile(r"a/(?P<p>.+) b/(?P=p)")

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


def tokens(text: str) -> set[str]:
    """NFC + casefold the whole text first, then whole emails and letter runs."""
    return _split(normalize(text))


def _split(normalized: str) -> set[str]:
    return set(_EMAIL.findall(normalized)) | set(_LETTERS.findall(normalized))


def private_markers(exclude_text: str, gitignore_text: str) -> list[str]:
    """Entries of .git/info/exclude that .gitignore does not also hold, without the slashes."""
    ignored = {line.strip().strip("/") for line in gitignore_text.splitlines()}
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
        elif path == ".claude/settings.local.json" or path.startswith(".claude/worktrees/"):
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
            for token in _split(folded)
            if (digest := hashlib.sha256(token.encode("utf-8")).hexdigest()) in entry
        }
        findings += [Finding("words", where, f"private word #{n}") for n in sorted(hit)]
    findings += [
        Finding("markers", where, f"private marker #{n}")
        for n, marker in enumerate(markers, start=1)
        if normalize(marker) in folded
    ]
    return findings


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "core.quotePath=false", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError("git could not read the history")
    return result.stdout.decode("utf-8", errors="replace")


def _file_chunks(short: str, diff: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for part in _DIFF_HEADER.split(diff)[1:]:
        header = part.split("\n", 1)[0]
        match = _SAME_PATH.fullmatch(header)
        name = match["p"] if match else header
        chunks.append((f"commit {short} · {name}", part))
    return chunks


def read_history(repo: Path) -> History:
    """Paths ever committed, and one chunk per message, person and file diff."""
    names = _git(repo, "log", "--all", "--no-renames", "--name-only", "--format=", "-z")
    paths = {name.strip("\n") for name in names.split("\0") if name.strip("\n")}
    fmt = "%x1e%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1f"
    log = _git(
        repo, "log", "--all", "-p", "--no-color", "--no-renames", "--no-ext-diff", f"--format={fmt}"
    )
    chunks: list[tuple[str, str]] = []
    for entry in _COMMIT_START.split(log)[1:] if log else []:
        sha, author, author_email, committer, committer_email, message, diff = entry.split(
            "\x1f", 6
        )
        short = f"commit {sha[:7]}"
        chunks.append((f"{short} · message", message))
        chunks.append((f"{short} · author", f"{author} {author_email}"))
        chunks.append((f"{short} · committer", f"{committer} {committer_email}"))
        chunks += _file_chunks(sha[:7], diff)
    return History(paths, chunks)


def _gitleaks_binary() -> str | None:
    found = shutil.which("gitleaks")
    if found:
        return found
    local = HERE.parent / ".tools" / "bin" / "gitleaks"
    return str(local) if local.is_file() else None


def run_gitleaks(repo: Path) -> list[Finding]:
    binary = _gitleaks_binary()
    if binary is None:
        return [Finding("secrets", "gitleaks", "gitleaks not found: run make tools")]
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        result = subprocess.run(  # noqa: S603
            [
                binary,
                "git",
                "--redact",
                "--no-banner",
                "--no-color",
                "--exit-code",
                "1",
                "--report-format",
                "json",
                "--report-path",
                str(report),
                str(repo),
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return []
        if result.returncode != 1 or not report.is_file():
            return [Finding("secrets", "gitleaks", f"gitleaks failed (exit {result.returncode})")]
        leaks = json.loads(report.read_text(encoding="utf-8"))
    return [
        Finding(
            "secrets",
            f"commit {str(leak.get('Commit', ''))[:7]} · {leak.get('File', '')}",
            str(leak.get("RuleID", "secret")),
        )
        for leak in leaks
    ]


def _read_markers(repo: Path) -> list[str]:
    exclude = Path(_git(repo, "rev-parse", "--git-path", "info/exclude").strip())
    exclude = exclude if exclude.is_absolute() else repo / exclude
    exclude_text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    ignore = repo / ".gitignore"
    ignore_text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    return private_markers(exclude_text, ignore_text)


def _fail(check: Check, where: str, detail: str) -> list[Finding]:
    return [Finding(check, where, detail)]


def _load_hashes(repo: Path) -> tuple[list[str], list[Finding]]:
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


def _hide_if_private(name: str, hashes: Sequence[str], markers: Sequence[str]) -> str:
    """Hide a file name that holds a private word or marker."""
    return HIDDEN if check_text("", name, hashes, markers) else name


def _scrub(where: str, hashes: Sequence[str], markers: Sequence[str]) -> str:
    head, sep, name = where.partition(" · ")
    if not sep or name in {"message", "author", "committer"}:
        return where
    return f"{head}{sep}{_hide_if_private(name, hashes, markers)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan the git history before the repo goes public."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    repo: Path = parser.parse_args(argv).repo.resolve()
    local = not os.environ.get("CI")

    hashes: list[str] = []
    markers: list[str] = []
    word_problem: list[Finding] = []
    marker_problem: list[Finding] = []
    if local:
        hashes, word_problem = _load_hashes(repo)
        try:
            markers = _read_markers(repo)
        except UnicodeDecodeError:
            marker_problem = _fail(
                "markers", "private markers", "cannot read the exclude file: not UTF-8 text"
            )
        except OSError as exc:
            reason = exc.strerror or "unreadable"
            marker_problem = _fail(
                "markers", "private markers", f"cannot read the exclude file: {reason}"
            )

    try:
        history = read_history(repo)
    except OSError as exc:
        print(f"public-check: cannot read the history: {exc}")
        return 1
    allowed = frozenset(
        line.strip() for line in ALLOWLIST.read_text(encoding="utf-8").splitlines() if line.strip()
    )

    secrets_found = run_gitleaks(repo)
    paths_found = check_paths(history.paths, allowed, markers)
    paths_found = [
        Finding(f.check, _hide_if_private(f.where, hashes, markers), f.detail) for f in paths_found
    ]
    words_found: list[Finding] = list(word_problem) + list(marker_problem)
    if local:
        for where, text in history.chunks:
            found = check_text(_scrub(where, hashes, markers), text, hashes, markers)
            words_found += found

    sections: list[tuple[str, list[Finding]]] = [
        ("secrets", secrets_found),
        ("paths", [f for f in paths_found if f.check == "paths"]),
    ]
    marker_paths = [f for f in paths_found if f.check == "markers"]
    if local:
        sections.append(("words", [f for f in words_found if f.check == "words"]))
        sections.append(
            ("markers", marker_paths + [f for f in words_found if f.check == "markers"])
        )
    total = sum(len(found) for _, found in sections)
    for name, found in sections:
        print(f"{name}: {'ok' if not found else f'{len(found)} finding(s)'}")
        for finding in found:
            print(f"  {finding.where}: {finding.detail}")
    if not local:
        print("words: SKIPPED (local only)")
        print("markers: SKIPPED (local only)")
    print("public-check: PASS" if total == 0 else f"public-check: FAIL ({total} findings)")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
