"""`make public-check` scans the whole history without ever printing a private word."""

import os
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
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / ".git" / "info").mkdir(exist_ok=True)
    (path / ".git" / "info" / "exclude").write_text("# comment\n/secret-notes/\n")
    commit(path, {"README.md": "# demo\n"})
    return path


def head(repo: Path) -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def word_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str) -> None:
    path = tmp_path / "words.sha256"
    path.write_text("".join(f"{hash_word(w)}\n" for w in words))
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(path))


def run(repo: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["--repo", str(repo)])
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


def test_unknown_top_level_path_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    commit(repo, {"NOTES.md": "hello\n"})
    code, out = run(repo, capsys)
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    path: str,
    fails: bool,
) -> None:
    monkeypatch.setenv("CI", "1")
    commit(repo, {path: "X=1\n"})
    code, out = run(repo, capsys)
    assert (code == 1) is fails
    assert ("env file" in out) is fails


def test_settings_local_json_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    commit(repo, {".claude/settings.local.json": "{}\n", ".claude/worktrees/a/x.txt": "x\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert out.count("machine-local") == 2


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


def test_ci_mode_says_words_skipped(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    code, out = run(repo, capsys)
    assert code == 0
    assert "words: SKIPPED (local only)" in out
    assert "markers: SKIPPED (local only)" in out


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

    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(public_check, "_gitleaks_binary", lambda: None)
    code, out = run(repo, capsys)
    assert code == 1
    assert "gitleaks not found: run make tools" in out


def test_history_on_an_empty_repo_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    code, _ = run(empty, capsys)
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

    fake = tmp_path / "fake-gitleaks"
    fake.write_text(
        "#!/bin/sh\n"
        'while [ $# -gt 0 ]; do\n  if [ "$1" = --report-path ]; then printf "[]" > "$2"; fi\n'
        "  shift\ndone\n"
        f"exit {exit_code}\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(public_check, "_gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys)
    assert code == 1
    assert "secrets: 1 finding(s)" in out
    assert "gitleaks" in out


def test_gitleaks_error_exit_says_failed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import public_check

    fake = tmp_path / "fake-gitleaks"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(public_check, "_gitleaks_binary", lambda: str(fake))
    code, out = run(repo, capsys)
    assert code == 1
    assert "gitleaks failed (exit 1)" in out


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
    monkeypatch.delenv("CI", raising=False)
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


def test_missing_repo_path_is_never_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    missing = tmp_path / "no-such-repo-dir"
    code, out = run(missing, capsys)
    assert code != 0
    assert "no-such-repo-dir" not in out
    assert str(tmp_path) not in out
