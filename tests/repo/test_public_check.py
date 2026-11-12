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


def git(repo: Path, *args: str, author: tuple[str, str] = AUTHOR) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": author[0],
        "GIT_COMMITTER_EMAIL": author[1],
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)  # noqa: S603, S607


def commit(
    repo: Path,
    files: dict[str, str],
    message: str = "add files",
    author: tuple[str, str] = AUTHOR,
) -> None:
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git(repo, "add", "--force", name)
    git(repo, "commit", "-q", "-m", message, author=author)


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
    assert "secrets" in out
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
