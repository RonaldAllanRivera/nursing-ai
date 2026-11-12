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
import unicodedata
from collections.abc import Iterable
from getpass import getpass
from pathlib import Path

SETTING = "PRIVATE_WORDS_FILE"
_HASH = re.compile(r"[0-9a-f]{64}")


def normalize(text: str) -> str:
    """NFC first, then casefold, so case and Unicode-form variants compare equal."""
    return unicodedata.normalize("NFC", text).casefold()


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
    merged = load_hashes(path) if path.exists() else []
    seen = set(merged)
    for word in words:
        digest = hash_word(word)
        if digest not in seen:
            seen.add(digest)
            merged.append(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("".join(f"{digest}\n" for digest in merged))
    path.chmod(0o600)
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


def _not_ignored(repo: Path, path: Path) -> bool:
    """True when the file sits in the repo and git would commit it (exit 128: outside the repo)."""
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=False,
    )
    return result.returncode == 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add private words to the hashed word list.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    repo: Path = args.repo

    path = words_file(repo)
    if path is None:
        print(f"set {SETTING} in .env", file=sys.stderr)
        return 2
    if _not_ignored(repo, path):
        print(f"{SETTING} is not ignored by git: add it to .gitignore first", file=sys.stderr)
        return 2

    words: list[str] = []
    while answer := getpass("Private word (Enter to finish): "):
        if answer.strip():
            words.append(answer)
    total = add_words(path, words)
    print(f"{total} {'hash' if total == 1 else 'hashes'} in the private word list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
