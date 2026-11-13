"""Refuse a commit that adds private words, private paths or stray top-level files.

Runs as a pre-commit hook. It reads the allowlist and the private markers the way
`make public-check` does, and checks the staged paths, the added lines and the author.
Gitleaks has its own hook. A report never shows a private word, a marker or the line it
was found on: only the file (or "author") and the entry number.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from public_check import (
    Finding,
    check_paths,
    check_text,
    hide_if_private,
    load_private_hashes,
    read_allowlist,
    read_markers,
)

_DIFF_HEADER = re.compile(r"^diff --git ", re.MULTILINE)
WARNING = "private words not checked: run make private-words"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "core.quotePath=false", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError("git could not read the staged changes")
    return result.stdout.decode("utf-8", errors="replace")


def _staged_paths(repo: Path) -> list[str]:
    names = _git(
        repo, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=ACMR", "-z"
    )
    return [name for name in names.split("\0") if name]


def _added_text(repo: Path) -> list[tuple[str, str]]:
    """One (path, added lines) pair per staged file; removed and context lines are left out."""
    diff = _git(
        repo,
        *("diff", "--cached", "-U0", "--no-color", "--text", "--no-ext-diff", "--no-textconv"),
        *("--no-renames", "--diff-filter=ACMR"),
    )
    # Same filter and order as _staged_paths, so the names come from there: a diff header
    # C-quotes odd names and would print them.
    names = _staged_paths(repo)
    parts = _DIFF_HEADER.split(diff)[1:]
    if len(parts) != len(names):
        raise OSError("git listed the staged files twice with different results")
    chunks: list[tuple[str, str]] = []
    for name, part in zip(names, parts, strict=True):
        body = part.partition("\n")[2]
        added: list[str] = []
        in_hunk = False
        for line in body.split("\n"):
            if line.startswith("@@"):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                added.append(line[1:])
        chunks.append((name, "\n".join(added)))
    return chunks


def staged_findings(repo: Path, hashes: Sequence[str], markers: Sequence[str]) -> list[Finding]:
    """Findings in the staged paths, the added lines and the author, none of them printable text."""
    findings = [
        Finding(f.check, hide_if_private(f.where, hashes, markers), f.detail)
        for f in check_paths(_staged_paths(repo), read_allowlist(), markers)
    ]
    for path, text in _added_text(repo):
        findings += check_text(hide_if_private(path, hashes, markers), text, hashes, markers)
    ident = _git(repo, "var", "GIT_AUTHOR_IDENT")
    findings += check_text("author", ident, hashes, markers)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the staged changes for private content.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    repo: Path = parser.parse_args(argv).repo.resolve()

    hashes, word_problem = load_private_hashes(repo)
    if word_problem:
        print(WARNING)
        for problem in word_problem:
            print(f"  {problem.detail}")
    try:
        markers = read_markers(repo)
        findings = staged_findings(repo, hashes, markers)
    except UnicodeDecodeError:
        print("staged-check: cannot read the exclude file: not UTF-8 text")
        return 1
    except OSError as exc:
        reason = exc.strerror or "unreadable"
        print(f"staged-check: cannot read the exclude file or the staged changes: {reason}")
        return 1

    for finding in findings:
        print(f"{finding.where}: {finding.detail}")
    if findings:
        print(f"staged-check: refused ({len(findings)} findings)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
