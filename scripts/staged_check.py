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
from reviewed_binaries import BinaryBlob, binary_blobs, load_reviewed, reviewed_file

_DIFF_HEADER = re.compile(r"^diff --git ", re.MULTILINE)
WARNING = "private words not checked: run make private-words"
NOT_REVIEWED = "binary not reviewed: run make accept-binary"


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


# The same options for the file list and the diff, so both list the same files in the same
# order. T: a type change, such as a link replaced by a file.
_STAGED = (
    "diff",
    "--cached",
    "--no-renames",
    "--diff-filter=ACMRT",
    "--no-relative",
    "-O/dev/null",
)


def _staged_changes(repo: Path) -> list[tuple[str, str]]:
    """(status, path) for every staged change; with -z the paths are not quoted."""
    fields = _git(repo, *_STAGED, "--name-status", "-z").split("\0")
    return list(zip(fields[0::2], fields[1::2], strict=False))


def _staged_binaries(repo: Path) -> list[BinaryBlob]:
    return binary_blobs(_git(repo, *_STAGED, "--raw", "--numstat", "-z", "--no-abbrev"))


def binary_findings(
    repo: Path, hashes: Sequence[str], markers: Sequence[str]
) -> tuple[list[Finding], list[str]]:
    """Unreviewed staged binaries: findings when the reviewed list exists, else warning lines.

    A lane worktree has no .env, so it has no list and only warns; the owner's PC refuses.
    """
    path = reviewed_file(repo)
    has_list = path is not None and path.is_file()
    reviewed = load_reviewed(path) if path is not None and has_list else {}
    findings: list[Finding] = []
    warnings: list[str] = []
    for binary in _staged_binaries(repo):
        if binary.blob in reviewed:
            continue
        where = hide_if_private(binary.path, hashes, markers)
        if has_list:
            findings.append(Finding("paths", where, NOT_REVIEWED))
        else:
            warnings.append(f"binary not reviewed: {where}")
    return findings, warnings


def _staged_paths(repo: Path) -> list[str]:
    return [path for _, path in _staged_changes(repo)]


def _added_text(repo: Path) -> list[tuple[str, str]]:
    """One (path, added lines) pair per file diff; removed and context lines are left out."""
    diff = _git(repo, *_STAGED, "-U0", "--no-color", "--text", "--no-ext-diff", "--no-textconv")
    # The names come from the file list: a diff header C-quotes odd names and would print
    # them. A type change prints two diffs (the old file removed, the new one added).
    names = [
        path for status, path in _staged_changes(repo) for _ in range(2 if status == "T" else 1)
    ]
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
        where = hide_if_private(path, hashes, markers)
        findings += check_text(where, text, hashes, markers)
        # A word in the file name itself (public-check sees it in the diff header).
        findings += [f for f in check_text(where, path, hashes, markers) if f.check == "words"]
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
    try:
        unreviewed, warnings = binary_findings(repo, hashes, markers)
    except UnicodeDecodeError:
        print("staged-check: cannot use the reviewed binaries list: not UTF-8 text")
        return 1
    except ValueError as exc:
        print(f"staged-check: reviewed binaries list {exc}")
        return 1
    except OSError:
        print("staged-check: cannot read the reviewed binaries list or the staged binaries")
        return 1
    findings += unreviewed
    for warning in warnings:
        print(warning)

    for finding in findings:
        print(f"{finding.where}: {finding.detail}")
    if findings:
        print(f"staged-check: refused ({len(findings)} findings)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
