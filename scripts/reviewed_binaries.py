"""Binary files the owner has looked at, recorded by git blob id in a private list.

`make public-check` can't read a binary file for private words, so every binary in the history
is a finding until the owner reviews it: an image is opened and shows synthetic data only, a
font comes from its published source. `make accept-binary FILE=…` then records the file's blob
id in `reviewed-binaries.txt`, next to the private word list and, like it, never committed. A
changed file has a new blob id, so it is a finding again. Nothing here prints a file's content.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from privacy_words import words_file

LIST_NAME = "reviewed-binaries.txt"
HEADER = "# Binary files the owner reviewed: <git blob id> <path>. Never commit this file.\n"
ZERO_BLOB = "0" * 40
_LINE = re.compile(r"([0-9a-f]{40}) (\S.*)")
_RAW = re.compile(r":\d{6} \d{6} ([0-9a-f]{40}) ([0-9a-f]{40}) [A-Z]\d*")
_NUMSTAT = re.compile(r"(?:\d+|-)\t(?:\d+|-)\t(.*)", re.DOTALL)


class AcceptError(Exception):
    """Why a file can't be accepted, in words that never quote its content."""


@dataclass(frozen=True)
class BinaryBlob:
    commit: str  # "" for staged changes
    path: str
    blob: str


def reviewed_file(repo: Path) -> Path | None:
    """The list next to the private word list, whether or not either file exists yet."""
    words = words_file(repo)
    return None if words is None else words.parent / LIST_NAME


def load_reviewed(path: Path) -> dict[str, str]:
    """Blob id → path. Raises ValueError("line N is malformed") naming the line number only."""
    return parse_reviewed(path.read_text(encoding="utf-8"))


def parse_reviewed(text: str) -> dict[str, str]:
    reviewed: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"line {number} is malformed")
        reviewed[match[1]] = match[2]
    return reviewed


def binary_blobs(output: str) -> list[BinaryBlob]:
    """Each binary change in `--raw --numstat -z --no-abbrev` output, with the blob it holds.

    A commit prints `\\x1e<sha>` (only with `--format=%x1e%H`), then its raw entries, then one
    numstat line per entry; numstat prints `-` for a binary. A deletion holds the old blob.
    """
    found: list[BinaryBlob] = []
    commit = ""
    blobs: dict[str, str] = {}
    fields = iter(output.split("\0"))
    for entry in fields:
        field = entry.removeprefix("\n")
        if not field:
            continue
        if field.startswith("\x1e"):
            commit, blobs = field[1:], {}
        elif raw := _RAW.fullmatch(field):
            path = next(fields, None)
            if path is None:
                raise OSError("git listed a change without a file name")
            old, new = raw[1], raw[2]
            blobs[path] = new if new != ZERO_BLOB else old
        elif numstat := _NUMSTAT.fullmatch(field):
            if field.startswith("-\t-\t"):
                path = numstat[1]
                if path not in blobs:
                    raise OSError("git listed a binary file without its blob")
                found.append(BinaryBlob(commit, path, blobs[path]))
        else:
            raise OSError("git listed the changes in an unexpected form")
    return found


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", "-c", "core.quotePath=false", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _is_binary(repo: Path, relative: str) -> bool:
    """Git's own answer, so `.gitattributes` (`binary`, `-diff`) counts as numstat counts it."""
    done = _git(repo, "diff", "--no-index", "--numstat", "--", os.devnull, relative)
    if done.returncode not in (0, 1):
        raise AcceptError("git could not read the file")
    return done.stdout.startswith("-\t-\t")


def _would_be_committed(repo: Path, path: Path) -> bool:
    """True when the path sits in the repo and git wouldn't ignore it (128: outside the repo)."""
    return _git(repo, "check-ignore", "-q", str(path)).returncode == 1


def accept(repo: Path, file: Path) -> str:
    """Record `file`'s blob id in the reviewed list and return the short id."""
    target = reviewed_file(repo)
    if target is None:
        raise AcceptError("PRIVATE_WORDS_FILE is not set: run make private-words")
    resolved = (file if file.is_absolute() else repo / file).resolve()
    try:
        relative = resolved.relative_to(repo.resolve()).as_posix()
    except ValueError:
        raise AcceptError("the file is outside the repo") from None
    if not resolved.is_file():
        raise AcceptError("no such file")
    if not _is_binary(repo, relative):
        raise AcceptError("text file: public-check reads it as text, so there is nothing to accept")
    if _would_be_committed(repo, target):
        raise AcceptError("the reviewed list would be committed: keep it next to an ignored list")
    hashed = _git(repo, "hash-object", "--", relative)
    if hashed.returncode != 0:
        raise AcceptError("git could not hash the file")
    blob = hashed.stdout.strip()
    existing = target.read_text(encoding="utf-8") if target.is_file() else HEADER
    if blob not in parse_reviewed(existing):
        _write_atomically(target, f"{existing.rstrip(chr(10))}\n{blob} {relative}\n")
    return blob[:7]


def _write_atomically(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{LIST_NAME}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        Path(temp).replace(target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a reviewed binary file by its blob id.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        short = accept(args.repo.resolve(), args.file)
    except AcceptError as exc:
        print(f"accept-binary: {exc}")
        return 1
    except (OSError, UnicodeDecodeError, ValueError):
        print("accept-binary: cannot read or write the reviewed list")
        return 1
    print(f"accepted {short} {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
