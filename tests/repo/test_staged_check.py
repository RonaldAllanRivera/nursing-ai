"""The commit-time check refuses private words, markers and stray paths without printing them."""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import staged_check
import yaml
from privacy_words import hash_word

CANARY = "zebracanary"
LISTED_EMAIL = "listed.person@family.example"
AUTHOR = ("Test Author", "author@example.com")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607


def stage(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git(repo, "add", "--force", name)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in ("PRIVATE_WORDS_FILE", "CI"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_NAME", AUTHOR[0])
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", AUTHOR[1])
    monkeypatch.setenv("GIT_COMMITTER_NAME", AUTHOR[0])
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", AUTHOR[1])
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / ".git" / "info" / "exclude").write_text("# comment\n/secret-notes/\n")
    stage(path, {"README.md": "# demo\n"})
    git(path, "commit", "-q", "-m", "first")
    return path


def word_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str) -> None:
    path = tmp_path / "words.sha256"
    path.write_text("".join(f"{hash_word(w)}\n" for w in words))
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(path))


def run(repo: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = staged_check.main(["--repo", str(repo)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_clean_stage_passes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    stage(repo, {"core/a.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 0
    assert "not checked" not in out


def test_staged_marker_path_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repo, {"secret-notes/todo.txt": "hello\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private marker #1" in out
    assert "secret-notes" not in out


def test_staged_marker_text_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repo, {"core/a.py": "# see secret-notes for more\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "core/a.py: private marker #1" in out
    assert "secret-notes" not in out


def test_staged_author_in_list_refused(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY, LISTED_EMAIL)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", LISTED_EMAIL)
    stage(repo, {"core/a.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "author: private word #2" in out
    assert LISTED_EMAIL not in out


def test_staged_word_refused_when_list_present(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, "otherword", CANARY.upper())
    stage(repo, {"core/a.py": f"name = '{CANARY}'\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "core/a.py: private word #2" in out
    assert CANARY not in out.casefold()


def test_missing_list_warns_but_allows(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repo, {"core/a.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 0
    assert "private words not checked: run make private-words" in out


def test_missing_list_still_checks_paths_and_markers(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage(repo, {"zz-note.md": "hello\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "private words not checked" in out
    assert "zz-note.md: top-level entry is not in the allowlist" in out


def test_malformed_list_warns_with_the_reason_only(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.sha256"
    bad.write_text(f"{hash_word(CANARY)}\nnot-a-hash {CANARY}\n")
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(bad))
    stage(repo, {"core/a.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 0
    assert "private words not checked: run make private-words" in out
    assert "line 2 is malformed" in out
    assert CANARY not in out


def test_only_added_lines_and_changed_files_are_read(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    stage(repo, {"core/a.py": f"old = '{CANARY}'\nkeep = 1\n"})
    git(repo, "-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-q", "-m", "old")
    stage(repo, {"core/a.py": "keep = 1\n"})
    code, out = run(repo, capsys)
    assert code == 0
    git(repo, "rm", "-q", "-f", "core/a.py")
    code, out = run(repo, capsys)
    assert code == 0, out


def test_path_with_a_word_is_hidden(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    stage(repo, {f"core/\t{CANARY}.py": f"# {CANARY}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "(path hidden): private word #1" in out
    assert CANARY not in out.casefold()


def test_env_file_is_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage(repo, {"core/.env": "KEY=value\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "core/.env: env file" in out
    assert "value" not in out


def test_unreadable_exclude_file_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".git" / "info" / "exclude").write_bytes(b"\xff\xfe\x00bad")
    stage(repo, {"core/a.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "cannot read the exclude file" in out


def test_default_repo_is_the_current_folder(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    stage(repo, {"core/a.py": "x = 1\n"})
    assert staged_check.main([]) == 0
    capsys.readouterr()


def hook_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    config: dict[str, Any] = yaml.safe_load(
        (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    return config


def test_every_hook_is_local_and_system() -> None:
    repos: list[dict[str, Any]] = hook_config()["repos"]
    assert [r["repo"] for r in repos] == ["local"]
    hooks: list[dict[str, Any]] = repos[0]["hooks"]
    assert {h["language"] for h in hooks} == {"system"}
    assert {h["id"] for h in hooks} >= {"ruff-format", "ruff-check", "pyright", "eslint"}
    assert {h["id"] for h in hooks} >= {"prettier", "gitleaks", "actionlint", "staged-check"}
    staged = next(h for h in hooks if h["id"] == "staged-check")
    assert staged.get("verbose") is True
    always = {h["id"] for h in hooks if h.get("always_run")}
    assert always == {"gitleaks", "staged-check", "public-check"}


def test_public_check_runs_before_every_push() -> None:
    config = hook_config()
    assert config["default_install_hook_types"] == ["pre-commit", "pre-push"]
    assert config["default_stages"] == ["pre-commit"]
    hooks: list[dict[str, Any]] = config["repos"][0]["hooks"]
    check = next(h for h in hooks if h["id"] == "public-check")
    assert check["stages"] == ["pre-push"]
    assert check["entry"] == "uv run python scripts/public_check.py"
    assert check["pass_filenames"] is False
    assert check["verbose"] is True
    assert [h["id"] for h in hooks if "pre-push" in h.get("stages", [])] == ["public-check"]


def test_staged_path_with_a_word_refused(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    stage(repo, {f"core/{CANARY.upper()}.py": "x = 1\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "(path hidden): private word #1" in out
    assert CANARY not in out.casefold()


def test_type_change_with_a_word_refused(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    (repo / "core").mkdir()
    (repo / "core" / "link").symlink_to("target")
    git(repo, "add", "core/link")
    git(repo, "commit", "-q", "-m", "add a link")
    (repo / "core" / "link").unlink()
    stage(repo, {"core/link": f"# {CANARY}\n"})
    code, out = run(repo, capsys)
    assert code == 1
    assert "core/link: private word #1" in out
    assert CANARY not in out.casefold()


# Reviewed binary files (carry-over 1).

FONT = "web/public/fonts/a.woff2"


def stage_bytes(repo: Path, name: str, data: bytes) -> str:
    """Stage a binary file and return its blob id."""
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    git(repo, "add", "--force", name)
    done = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f":{name}"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def test_staged_unlisted_binary_refused_when_reviewed_file_exists(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    (tmp_path / "reviewed-binaries.txt").write_text("# none yet\n")
    stage_bytes(repo, FONT, b"wOF2\x00\x01")
    code, out = run(repo, capsys)
    assert code == 1
    assert f"{FONT}: binary not reviewed: run make accept-binary" in out


def test_staged_listed_binary_passes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    blob = stage_bytes(repo, FONT, b"wOF2\x00\x01")
    (tmp_path / "reviewed-binaries.txt").write_text(f"{blob} {FONT}\n")
    code, out = run(repo, capsys)
    assert code == 0, out
    assert "binary not reviewed" not in out


def test_staged_binary_warns_without_reviewed_file(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    stage_bytes(repo, FONT, b"wOF2\x00\x01")
    code, out = run(repo, capsys)
    assert code == 0
    assert f"binary not reviewed: {FONT}" in out


def test_staged_binary_warns_in_a_worktree_without_settings(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage_bytes(repo, FONT, b"wOF2\x00\x01")
    code, out = run(repo, capsys)
    assert code == 0
    assert f"binary not reviewed: {FONT}" in out


def test_staged_binary_path_with_a_word_is_hidden(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    word_list(tmp_path, monkeypatch, CANARY)
    (tmp_path / "reviewed-binaries.txt").write_text("# none yet\n")
    stage_bytes(repo, f"web/public/{CANARY}.png", b"\x89PNG\x00")
    code, out = run(repo, capsys)
    assert code == 1
    assert CANARY not in out.casefold()
