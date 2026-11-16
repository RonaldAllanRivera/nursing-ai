"""`make public-check` scans the whole history without ever printing a private word."""

import os
import re
import secrets
import string
import subprocess
from pathlib import Path

import pytest
from privacy_words import hash_word
from public_check import main, private_markers, tokens

CANARY = "zebracanary"
LISTED_EMAIL = "listed.person@family.example"
AUTHOR = ("Test Author", "author@example.com")


def git(
    repo: Path,
    *args: str,
    author: tuple[str, str] = AUTHOR,
    committer: tuple[str, str] | None = None,
) -> None:
    who = committer or author
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": who[0],
        "GIT_COMMITTER_EMAIL": who[1],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)  # noqa: S603, S607


def commit(
    repo: Path,
    files: dict[str, str],
    message: str = "add files",
    author: tuple[str, str] = AUTHOR,
    committer: tuple[str, str] | None = None,
) -> None:
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git(repo, "add", "--force", name)
    git(repo, "commit", "-q", "-m", message, author=author, committer=committer)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / ".git" / "info").mkdir(exist_ok=True)
    (path / ".git" / "info" / "exclude").write_text("# comment\n/secret-notes/\n")
    commit(path, {"README.md": "# demo\n"})
    return path


def head(repo: Path, ref: str = "HEAD") -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "--short=7", ref],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def ghp_token() -> str:
    """A GitHub token shape built at run time, so no test file holds one."""
    return "ghp_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))


def word_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str) -> None:
    path = tmp_path / "words.sha256"
    path.write_text("".join(f"{hash_word(w)}\n" for w in words))
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(path))


def run(repo: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> tuple[int, str]:
    code = main(["--repo", str(repo), *flags])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_clean_repo_passes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    code, out = run(repo, capsys)
    assert code == 0
    assert out.rstrip().splitlines()[-1] == "public-check: PASS"


def test_secret_in_history_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = "ghp_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(36)
    )
    commit(repo, {"core/leak.py": f'TOKEN = "{token}"\n'})
    git(repo, "rm", "-q", "core/leak.py")
    git(repo, "commit", "-q", "-m", "remove it")
    code, out = run(repo, capsys)
    assert code == 1
    assert "github-pat" in out
    assert token not in out
    assert out.rstrip().splitlines()[-1].startswith("public-check: FAIL (")


def test_unknown_top_level_path_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, {"NOTES.md": "hello\n"})
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "NOTES.md" in out


@pytest.mark.parametrize(
    ("path", "fails"),
    [
        (".env", True),
        (".env.local", True),
        ("web/.env.production", True),
        (".env-sample", True),
        ("core/.env.example", False),
        (".env.example", False),
    ],
)
def test_env_files_fail_except_example(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    path: str,
    fails: bool,
) -> None:
    commit(repo, {path: "X=1\n"})
    code, out = run(repo, capsys, "--ci")
    assert (code == 1) is fails
    assert ("env file" in out) is fails


def test_settings_local_json_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, {".claude/settings.local.json": "{}\n", ".claude/worktrees/a/x.txt": "x\n"})
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert out.count("machine-local") == 2


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.local.json",
        ".claude/worktrees/a/x.txt",
        "web/.claude/settings.local.json",
        "web/.claude/worktrees/x/y",
    ],
)
def test_machine_local_claude_files_fail_anywhere(
    repo: Path, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    commit(repo, {path: "x\n"})
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert f"{path}: machine-local Claude Code file" in out


def test_marker_path_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/Secret-Notes/a.txt": "x\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private marker #1" in out
    assert "secret-notes" not in out.casefold()


def test_marker_text_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/a.py": "# see the SECRET-NOTES folder\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private marker #1" in out
    assert "secret-notes" not in out.casefold()


def test_private_markers_skip_gitignore_entries() -> None:
    exclude = "# c\n\n/secret-notes/\n/shared/\nthing\n"
    assert private_markers(exclude, "shared/\n.env*\n") == ["secret-notes", "thing"]


def test_private_markers_skip_entries_gitignore_holds_in_any_folder() -> None:
    exclude = "/.claude/worktrees/\n.claude/settings.local.json\n/secret-notes/\n"
    gitignore = "**/.claude/settings.local.json\n**/.claude/worktrees/\n"
    assert private_markers(exclude, gitignore) == ["secret-notes"]


def test_tokens_split_emails_and_letter_runs() -> None:
    found = tokens("Mail JOSÉ at Me.Name+x@Host.Example, 42 times_ok")
    assert {"josé", "me.name+x@host.example", "mail", "times", "ok"} <= found


def test_author_email_in_list_is_caught(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY, LISTED_EMAIL)
    commit(repo, {"core/a.py": "x = 1\n"}, author=("Someone", LISTED_EMAIL))
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #2" in out
    assert LISTED_EMAIL not in out


@pytest.mark.parametrize("place", ["file", "message", "author"])
def test_planted_canary_word_is_caught(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    place: str,
) -> None:
    word_list(tmp_path, monkeypatch, "other", CANARY)
    if place == "file":
        commit(repo, {"core/a.py": f"# {CANARY}\n"})
    elif place == "message":
        commit(repo, {"core/a.py": "x = 1\n"}, message=f"about {CANARY}")
    else:
        commit(repo, {"core/a.py": "x = 1\n"}, author=(f"Ann {CANARY}", "ann@example.com"))
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #2" in out
    assert {"file": "core/a.py"}.get(place, place) in out


def test_unicode_variant_in_history_is_caught(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, "José")
    commit(repo, {"core/a.py": "# JOSÉ was here\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out


def test_email_in_list_is_caught_as_whole_address(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, LISTED_EMAIL)
    commit(repo, {"core/a.py": "# mail someone.else@family.example\n"}, message="no match here")
    assert run(repo, capsys)[0] == 0
    commit(repo, {"core/b.py": f"# mail {LISTED_EMAIL.upper()}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out


def test_report_never_contains_the_word(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(
        repo,
        {f"core/{CANARY}.py": f"line with {CANARY} in it\n"},
        message=f"{CANARY} message",
        author=(CANARY, "c@example.com"),
    )
    code, out = run(repo, capsys)
    assert code == 1
    assert CANARY not in out.casefold()
    assert "line with" not in out
    assert "private word #1" in out


def test_missing_word_list_fails_locally(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(repo, capsys)
    assert code == 1
    assert "run make private-words" in out


def test_empty_word_list_fails_locally(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "empty.sha256"
    path.write_text("# nothing yet\n")
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(path))
    code, out = run(repo, capsys)
    assert code == 1
    assert "run make private-words" in out


def test_ci_mode_says_words_skipped(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(repo, capsys, "--ci")
    assert code == 0
    assert "words: SKIPPED (local only)" in out
    assert "markers: SKIPPED (local only)" in out


def test_ci_mode_hides_marker_paths(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    token = ghp_token()
    commit(repo, {"secret-notes/todo.txt": f'TOKEN = "{token}"\n'})
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "private marker #1" in out
    assert "(path hidden): github-pat" in out
    assert "secret-notes" not in out.casefold()
    assert token not in out
    assert "words: SKIPPED (local only)" in out


def test_ci_variable_alone_never_skips_the_words(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "true")
    code, out = run(repo, capsys)
    assert code == 1
    assert "run make private-words" in out
    assert "SKIPPED" not in out


def test_word_list_that_is_a_folder_leaks_no_path(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "private-folder-name"
    folder.mkdir()
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(folder))
    code, out = run(repo, capsys)
    assert code == 1
    assert "cannot use PRIVATE_WORDS_FILE" in out
    assert "private-folder-name" not in out
    assert str(tmp_path) not in out


def test_malformed_word_list_names_the_line_only(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad-list-name.sha256"
    path.write_text(f"{hash_word('a')}\nnot-a-hash\n")
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(path))
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word list line 2 is malformed" in out
    assert "bad-list-name" not in out
    assert "not-a-hash" not in out


def test_missing_gitleaks_says_run_make_tools(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: None)
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "gitleaks not found: run make tools" in out


def test_history_on_an_empty_repo_is_fine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    code, _ = run(empty, capsys, "--ci")
    assert code == 0


def merge_adding(repo: Path, files: dict[str, str]) -> None:
    """A merge commit that alone adds the files (the side branch and main don't)."""
    git(repo, "checkout", "-qb", "side")
    commit(repo, {"core/a.py": "x = 1\n"})
    git(repo, "checkout", "-q", "main")
    commit(repo, {"core/b.py": "y = 2\n"})
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
        git(repo, "add", "--force", name)
    git(repo, "commit", "-q", "-m", "merge side")


def test_merge_commit_changes_are_scanned(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    merge_adding(repo, {"NOTES.md": "n\n", "core/b.py": f"y = 2  # {CANARY}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "NOTES.md" in out
    assert "private word #1" in out


def test_listed_email_at_the_start_of_a_line_is_caught(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, LISTED_EMAIL)
    commit(repo, {"core/invited.txt": f"{LISTED_EMAIL}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out


def test_file_git_calls_binary_is_scanned_and_listed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    target = repo / "core" / "data.txt"
    target.parent.mkdir()
    target.write_bytes(b"\x00 " + CANARY.encode() + b"\n")
    git(repo, "add", "core/data.txt")
    git(repo, "commit", "-q", "-m", "binary-ish")
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out
    assert "core/data.txt: binary file not scanned" in out
    assert f"commit {head(repo)} · core/data.txt: binary file not scanned" in out
    assert CANARY not in out.casefold()


def test_binary_with_a_tab_and_a_word_in_its_path_is_hidden(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    target = repo / "core" / f"\t{CANARY}.bin"
    target.parent.mkdir()
    target.write_bytes(b"\x00\x01")
    git(repo, "add", "--force", "core")
    git(repo, "commit", "-q", "-m", "binary with a tab in its name")
    code, out = run(repo, capsys)
    assert code == 1
    assert "binary file not scanned" in out
    assert CANARY not in out.casefold()


def test_secret_path_with_a_marker_is_hidden(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = "ghp_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(36)
    )
    commit(repo, {"core/secret-notes/key.py": f'TOKEN = "{token}"\n'})
    code, out = run(repo, capsys)
    assert code == 1
    assert "github-pat" in out
    assert "secret-notes" not in out.casefold()
    assert token not in out


@pytest.mark.parametrize("exit_code", [1, 2])
def test_gitleaks_error_or_empty_report_fails(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exit_code: int,
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, public_check.pinned_gitleaks_version(), exit_code)
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "secrets: 1 finding(s)" in out
    assert "gitleaks" in out


def test_gitleaks_error_exit_says_failed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, public_check.pinned_gitleaks_version(), 1)
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "gitleaks failed (exit 1)" in out


def test_gitleaks_error_on_the_message_scan_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    fake = tmp_path / "gitleaks"
    fake.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = version ]; then echo {public_check.pinned_gitleaks_version()}; fi\n'
        'if [ "$1" = git ]; then echo "INF 2 commits scanned." >&2; fi\n'
        'if [ "$1" = dir ]; then exit 1; fi\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "gitleaks: gitleaks failed (exit 1)" in out


def test_unit_separator_in_a_message_hides_nothing(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/a.py": "x = 1\n"}, message=f"first\x1fabout {CANARY}")
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out


def test_fake_commit_header_in_a_message_does_not_crash(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/a.py": "x = 1\n"}, message=f"first\n\x1e{'a' * 40}\x1f\nabout {CANARY}")
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out


def test_root_commit_is_scanned_even_if_show_root_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    root = tmp_path / "rooted"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "log.showRoot", "false")
    commit(root, {"core/a.py": f"# {CANARY}\n"})
    code, out = run(root, capsys)
    assert code == 1
    assert "private word #1" in out


def test_marker_count_is_printed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    assert "markers: ok (1 marker)" in run(repo, capsys)[1]
    (repo / ".git" / "info" / "exclude").unlink()
    assert "markers: ok (0 markers)" in run(repo, capsys)[1]


def test_committer_only_listed_email_is_caught(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY, LISTED_EMAIL)
    commit(repo, {"core/a.py": "x = 1\n"}, committer=("Someone", LISTED_EMAIL))
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #2" in out
    assert "committer" in out
    assert "author:" not in out


def test_word_only_in_a_tab_path_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {f"core/\t{CANARY}.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out
    assert CANARY not in out.casefold()


def test_tab_path_with_another_finding_never_prints_the_word(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {f"core/\t{CANARY}.py": f"# {CANARY}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out
    assert CANARY not in out.casefold()


def test_labels_ignore_diff_noprefix(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    git(repo, "config", "diff.noprefix", "true")
    commit(repo, {"core/a.py": f"# {CANARY}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · core/a.py: private word #1" in out


def test_diff_line_in_a_message_keeps_the_labels(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/a.py": "x = 1\n"}, message=f"subject\n\ndiff --git a/x b/x\n{CANARY}\n")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · message: private word #1" in out
    assert "· x:" not in out


def test_type_change_keeps_the_labels(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    (repo / "core").mkdir()
    (repo / "core" / "link").symlink_to("target")
    commit(repo, {"core/a.py": "x = 1\n"})
    git(repo, "add", "core/link")
    git(repo, "commit", "-q", "-m", "add a link")
    (repo / "core" / "link").unlink()
    commit(repo, {"core/link": f"# {CANARY}\n"}, message="the link becomes a file")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · core/link: private word #1" in out
    assert "do not line up" not in out


def test_file_list_and_diff_that_disagree_fail_closed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {"core/a.py": f"# {CANARY}\n", "core/b.py": "y = 2\n"})
    real = public_check.names_by_commit

    def one_name_short(repo: Path, nonce: str) -> dict[str, list[str]]:
        return {sha: names[1:] for sha, names in real(repo, nonce).items()}

    monkeypatch.setattr(public_check, "names_by_commit", one_name_short)
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · (path hidden): private word #1" in out
    assert f"commit {head(repo)}: file names and diff do not line up" in out
    assert "core/a.py" not in out


def test_secret_only_in_a_commit_message_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = ghp_token()
    commit(repo, {"core/a.py": "x = 1\n"}, message=f"add a\n\nused {token} here")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · message: github-pat" in out
    assert token not in out


@pytest.mark.parametrize(("place", "entry"), [("message", 1), ("tagger", 2)])
def test_listed_word_in_a_tag_is_caught(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    place: str,
    entry: int,
) -> None:
    word_list(tmp_path, monkeypatch, CANARY, LISTED_EMAIL)
    if place == "message":
        git(repo, "tag", "-a", "v0.1.0", "-m", f"release for {CANARY}")
    else:
        git(repo, "tag", "-a", "v0.1.0", "-m", "release", committer=("Someone", LISTED_EMAIL))
    code, out = run(repo, capsys)
    assert code == 1
    assert f"tag {head(repo, 'v0.1.0')} · {place}: private word #{entry}" in out
    assert CANARY not in out.casefold()
    assert LISTED_EMAIL not in out


def test_listed_word_in_a_tag_name_is_caught_and_hidden(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    git(repo, "tag", f"{CANARY}-build")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"tag {head(repo)} · name: private word #1" in out
    assert CANARY not in out.casefold()


def test_secret_only_in_a_tag_message_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = ghp_token()
    git(repo, "tag", "-a", "v0.1.0", "-m", f"release {token}")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"tag {head(repo, 'v0.1.0')} · message: github-pat" in out
    assert token not in out


ALLOW_ALL = "[allowlist]\nregexes = ['''.*''']\n"


def committed_leak(repo: Path) -> str:
    token = ghp_token()
    commit(repo, {"core/leak.py": f'TOKEN = "{token}"\n'})
    return token


def assert_leak_found(out: str, token: str) -> None:
    assert "core/leak.py: github-pat" in out
    assert token not in out
    assert out.rstrip().splitlines()[-1].startswith("public-check: FAIL (")


def test_untracked_gitleaks_config_cannot_hide_a_leak(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = committed_leak(repo)
    (repo / ".gitleaks.toml").write_text(ALLOW_ALL)
    code, out = run(repo, capsys)
    assert code == 1
    assert_leak_found(out, token)


@pytest.mark.parametrize("place", [".gitleaksignore", ".git/.gitleaksignore"])
def test_untracked_gitleaksignore_cannot_hide_a_leak(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    place: str,
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = committed_leak(repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo / place).write_text(f"{sha}:core/leak.py:github-pat:1\n")
    code, out = run(repo, capsys)
    assert code == 1
    assert_leak_found(out, token)


@pytest.mark.parametrize(
    ("name", "value"), [("GITLEAKS_CONFIG", os.devnull), ("GITLEAKS_CONFIG_TOML", ALLOW_ALL)]
)
def test_gitleaks_config_variables_cannot_hide_a_leak(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    value: str,
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    token = committed_leak(repo)
    monkeypatch.setenv(name, value)
    code, out = run(repo, capsys)
    assert code == 1
    assert_leak_found(out, token)


def fake_gitleaks(
    tmp_path: Path, version: str, exit_code: int = 0, log: str = "INF 1 commits scanned."
) -> Path:
    """A stand-in gitleaks that prints `version`, logs `log`, writes an empty report and exits."""
    fake = tmp_path / "fake-bin" / "gitleaks"
    fake.parent.mkdir(exist_ok=True)
    (fake.parent / "log.txt").write_text(log + "\n")
    fake.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = version ]; then echo {version}; exit 0; fi\n'
        f'cat "{fake.parent / "log.txt"}" >&2\n'
        'while [ $# -gt 0 ]; do\n  if [ "$1" = --report-path ]; then printf "[]" > "$2"; fi\n'
        "  shift\ndone\n"
        f"exit {exit_code}\n"
    )
    fake.chmod(0o755)
    return fake


def test_relative_git_dir_cannot_hide_a_leak(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = committed_leak(repo)
    # What `git --git-dir=.git push` puts in the pre-push hook's environment.
    monkeypatch.setenv("GIT_DIR", ".git")
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert_leak_found(out, token)


def test_explicit_bare_repository_setting_cannot_hide_a_leak(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token = committed_leak(repo)
    settings = tmp_path / "global.gitconfig"
    settings.write_text("[safe]\n\tbareRepository = explicit\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert_leak_found(out, token)


@pytest.mark.parametrize(
    ("log", "detail"),
    [
        ("12:00PM INF 0 commits scanned.", "gitleaks read no commits: secrets not checked"),
        ("12:00PM INF no leaks found", "gitleaks read no commits: secrets not checked"),
        (
            "12:00PM ERR [git] fatal: not a git repository\n12:00PM INF 1 commits scanned.",
            "gitleaks reported an error: secrets not fully checked",
        ),
    ],
)
def test_gitleaks_that_reads_nothing_fails(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    log: str,
    detail: str,
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, public_check.pinned_gitleaks_version(), log=log)
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert f"gitleaks: {detail}" in out
    assert "not a git repository" not in out


def test_pinned_gitleaks_wins_over_one_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, public_check.pinned_gitleaks_version())
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    assert public_check.PINNED_GITLEAKS.is_file(), "run make tools"
    assert public_check.gitleaks_binary() == str(public_check.PINNED_GITLEAKS)


def test_unpinned_gitleaks_version_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, "8.0.0")
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    word_list(tmp_path, monkeypatch, CANARY)
    code, out = run(repo, capsys)
    assert code == 1
    assert "gitleaks: not the pinned gitleaks: run make tools" in out


def test_install_script_reads_the_one_pin() -> None:
    import public_check

    script = (public_check.HERE / "install-tools.sh").read_text(encoding="utf-8")
    version = public_check.pinned_gitleaks_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert version not in script
    assert f"read_pin {public_check.GITLEAKS_PIN.stem}" in script


def test_missing_repo_path_is_never_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no-such-repo-dir"
    code, out = run(missing, capsys, "--ci")
    assert code != 0
    assert "no-such-repo-dir" not in out
    assert str(tmp_path) not in out


# Reviewed binary files and Git LFS.

FONT = "web/public/fonts/a.woff2"


def commit_bytes(repo: Path, name: str, data: bytes, message: str = "add a binary") -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    git(repo, "add", "--force", name)
    git(repo, "commit", "-q", "-m", message)


def blob_of(repo: Path, name: str, ref: str = "HEAD") -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f"{ref}:{name}"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def reviewed(tmp_path: Path, *lines: str) -> None:
    (tmp_path / "reviewed-binaries.txt").write_text("".join(f"{line}\n" for line in lines))


def test_accepted_binary_is_not_a_finding(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit_bytes(repo, FONT, b"wOF2\x00\x01")
    reviewed(tmp_path, "# fonts", f"{blob_of(repo, FONT)} {FONT}")
    code, out = run(repo, capsys)
    assert code == 0, out
    assert "accepted binaries: 1" in out
    assert "binary file not scanned" not in out


def test_deleting_an_accepted_binary_is_not_a_finding(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit_bytes(repo, FONT, b"wOF2\x00\x01")
    reviewed(tmp_path, f"{blob_of(repo, FONT)} {FONT}")
    git(repo, "rm", "-q", FONT)
    git(repo, "commit", "-q", "-m", "drop the font")
    code, out = run(repo, capsys)
    assert code == 0, out
    assert "accepted binaries: 1" in out


def test_changed_binary_is_a_finding_again(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit_bytes(repo, FONT, b"wOF2\x00\x01")
    reviewed(tmp_path, f"{blob_of(repo, FONT)} {FONT}")
    commit_bytes(repo, FONT, b"wOF2\x00\x02", "change the font")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"commit {head(repo)} · {FONT}: binary file not scanned" in out
    assert "accepted binaries: 1" in out


def test_malformed_reviewed_list_names_the_line_only(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    reviewed(tmp_path, "# fine", f"oops {CANARY}")
    code, out = run(repo, capsys)
    assert code == 1
    assert "reviewed binaries list line 2 is malformed" in out
    assert CANARY not in out.casefold()


@pytest.mark.parametrize("flags", [("--ci",), ()])
def test_lfs_attribute_in_history_fails(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    commit(repo, {".gitattributes": "*.png filter=lfs diff=lfs merge=lfs -text\n"})
    code, out = run(repo, capsys, *flags)
    assert code == 1
    assert f"commit {head(repo)} · .gitattributes: Git LFS is not allowed" in out


@pytest.mark.parametrize("flags", [("--ci",), ()])
def test_lfs_pointer_blob_fails(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    pointer = f"version https://git-lfs.github.com/spec/v1\noid sha256:{'ab' * 32}\nsize 12\n"
    commit(repo, {"web/public/a.png": pointer})
    code, out = run(repo, capsys, *flags)
    assert code == 1
    assert f"commit {head(repo)} · web/public/a.png: Git LFS pointer file" in out


def test_listed_word_in_a_latin1_file_is_caught_and_noted(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, "zörblat")
    commit_bytes(repo, "core/old.txt", "owner: Zörblat\n".encode("latin-1"))
    code, out = run(repo, capsys)
    assert code == 1
    assert "core/old.txt: private word #1" in out
    assert "not UTF-8: core/old.txt" in out
    assert "rblat" not in out


def test_utf8_files_get_no_not_utf8_note(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, "zörblat")
    commit(repo, {"core/new.txt": "owner: Zörblat\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private word #1" in out
    assert "not UTF-8" not in out


def test_not_utf8_note_never_prints_a_private_file_name(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, "quixley")
    commit_bytes(repo, "core/quixley.txt", b"caf\xe9\n")
    code, out = run(repo, capsys)
    assert code == 1
    assert "quixley" not in out.lower()
    assert "not UTF-8: (path hidden)" in out


def test_gitleaks_runs_without_replacement_objects(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    fake = fake_gitleaks(tmp_path, public_check.pinned_gitleaks_version())
    seen = tmp_path / "seen.txt"
    fake.write_text(
        fake.read_text().replace("cat ", f'echo "[$GIT_NO_REPLACE_OBJECTS]" >> "{seen}"\ncat ', 1)
    )
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    monkeypatch.delenv("GIT_NO_REPLACE_OBJECTS", raising=False)
    code, _ = run(repo, capsys, "--ci")
    assert code == 0
    assert set(seen.read_text().split()) == {"[1]"}


def test_repo_with_only_empty_commits_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    only_empty = tmp_path / "only-empty"
    only_empty.mkdir()
    git(only_empty, "init", "-q", "-b", "main")
    git(only_empty, "commit", "-q", "--allow-empty", "-m", "first")
    git(only_empty, "commit", "-q", "--allow-empty", "-m", "second")
    code, out = run(only_empty, capsys, "--ci")
    assert code == 0
    assert "read no commits" not in out


def test_gitleaks_that_reads_nothing_after_an_empty_commit_still_fails(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    git(repo, "commit", "-q", "--allow-empty", "-m", "nothing changed")
    fake = fake_gitleaks(
        tmp_path, public_check.pinned_gitleaks_version(), log="INF 0 commits scanned."
    )
    monkeypatch.setattr(public_check, "gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys, "--ci")
    assert code == 1
    assert "gitleaks read no commits: secrets not checked" in out


def test_a_binary_file_is_not_also_noted_as_not_utf8(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit_bytes(repo, "web/public/a.bin", b"\x00\xff\xfe\x80binary")
    code, out = run(repo, capsys, "--ci")
    assert code == 0
    assert "not UTF-8" not in out
