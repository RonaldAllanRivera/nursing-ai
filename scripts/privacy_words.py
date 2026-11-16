"""A list of SHA-256 hashes of private words, and the CLI that adds to it.

The words are typed at a hidden prompt and never written down or shown: only their hashes
are stored, one per line. `make public-check` and the pre-commit hook compare the words
in the git history against this list.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from getpass import getpass
from pathlib import Path

SETTING = "PRIVATE_WORDS_FILE"
_HASH = re.compile(r"[0-9a-f]{64}")
EMAIL = re.compile(r"\w[\w.+-]*@[\w-]+(?:\.[\w-]+)+")
LETTERS = re.compile(r"[^\W\d_]+")
NOT_MATCHABLE = (
    "That entry can't be matched as one word (letters only, or a whole email): not saved."
    " Type each part of a hyphenated name separately."
)


def normalize(text: str) -> str:
    """NFC first, then casefold, so case and Unicode-form variants compare equal."""
    return unicodedata.normalize("NFC", text).casefold()


def split_tokens(normalized: str) -> set[str]:
    """Whole emails and letter runs of text that is already normalized."""
    return set(EMAIL.findall(normalized)) | set(LETTERS.findall(normalized))


def tokens(text: str) -> set[str]:
    """NFC + casefold the whole text first, then whole emails and letter runs."""
    return split_tokens(normalize(text))


def is_matchable(entry: str) -> bool:
    """True when the checker can produce the entry as a token: letters only, or one whole email."""
    folded = normalize(entry.strip())
    return bool(LETTERS.fullmatch(folded) or EMAIL.fullmatch(folded))


def hash_word(word: str) -> str:
    return hashlib.sha256(normalize(word.strip()).encode("utf-8")).hexdigest()


def load_hashes(path: Path) -> list[str]:
    """Read the hashes in order. Entry number = position + 1."""
    hashes: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _HASH.fullmatch(line):
            raise ValueError(f"line {number} is not a 64-character lowercase hex hash")
        hashes.append(line)
    return hashes


def add_words(path: Path, words: Iterable[str]) -> int:
    """Merge the words' hashes into the file (no duplicates, first order kept); return the total."""
    if path.is_symlink():
        raise ValueError("the target is a symbolic link; it is never followed")
    merged = list(dict.fromkeys(load_hashes(path))) if path.exists() else []
    seen = set(merged)
    for word in words:
        if not is_matchable(word):
            raise ValueError("entry can't be matched as one word (letters only, or a whole email)")
        digest = hash_word(word)
        if digest not in seen:
            seen.add(digest)
            merged.append(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the list, then swap it in: a failed write never leaves half a list.
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(f"{digest}\n" for digest in merged))
        Path(temp).chmod(0o600)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return len(merged)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def words_file(repo: Path) -> Path | None:
    """PRIVATE_WORDS_FILE from the environment, else from repo/.env; None when empty or unset."""
    value = os.environ.get(SETTING, "").strip()
    if not value:
        env_file = repo / ".env"
        if env_file.is_file():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, rest = line.partition("=")
                if key.strip() == SETTING:
                    value = _unquote(rest)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo / path


def _git_says(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=False,
    )


def _ignore_problem(repo: Path, path: Path) -> str | None:
    """Why the target can't be used, or None when git ignores it or it lies outside the repo.

    Git answers first. Anything it can't answer (exit 128) is allowed only when the target
    really lies outside the repository; it is never read as "ignored".
    """
    result = _git_says(repo, "check-ignore", "-q", str(path))
    if result.returncode == 0:
        return None
    if result.returncode == 1:
        return f"{SETTING} is not ignored by git: add it to .gitignore first"
    top = _git_says(repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return f"cannot tell whether git ignores {SETTING}: the repo folder is not a git repository"
    # fsdecode, never a replacement decode: the folder name may not be UTF-8.
    root = Path(os.fsdecode(top.stdout.rstrip(b"\n"))).resolve()
    if not path.parent.resolve().is_relative_to(root):
        return None
    return f"cannot tell whether git ignores {SETTING}: git could not check that path"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add private words to the hashed word list.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    repo: Path = args.repo

    path = words_file(repo)
    if path is None:
        print(f"set {SETTING} in .env", file=sys.stderr)
        return 2
    if path.is_symlink():
        print(f"{SETTING} is a symbolic link: it is never followed", file=sys.stderr)
        return 2
    if (problem := _ignore_problem(repo, path)) is not None:
        print(problem, file=sys.stderr)
        return 2

    words: list[str] = []
    while answer := getpass("Private word (Enter to finish): "):
        entry = answer.strip()
        if not entry:
            continue
        if not is_matchable(entry):
            print(NOT_MATCHABLE)
            continue
        words.append(entry)
    try:
        total = add_words(path, words)
    except OSError as exc:
        print(f"cannot use {SETTING}: {exc.strerror}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"cannot use {SETTING}: {exc}", file=sys.stderr)
        return 2
    print(f"{total} {'hash' if total == 1 else 'hashes'} in the private word list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
