"""The private word list stores only SHA-256 hashes and the CLI never shows a word."""

import hashlib
import subprocess
from pathlib import Path

import privacy_words
import pytest

HEX64 = set("0123456789abcdef")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607


def make_repo(tmp_path: Path, env_line: str, ignore: str = "") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text(ignore)
    (repo / ".env").write_text(env_line + "\n")
    return repo


def type_answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    queue = iter(answers)

    def fake_getpass(prompt: str) -> str:
        assert prompt == "Private word (Enter to finish): "
        return next(queue)

    monkeypatch.setattr(privacy_words, "getpass", fake_getpass)


def test_hash_word_normalizes_case_and_unicode() -> None:
    expected = hashlib.sha256("josé".encode()).hexdigest()
    assert privacy_words.hash_word("José") == expected
    assert privacy_words.hash_word("JOSÉ") == expected
    assert privacy_words.hash_word("José") == expected
    assert privacy_words.hash_word("  José ") == expected


def test_add_words_dedupes_and_returns_count(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "words.sha256"
    assert privacy_words.add_words(path, ["Alpha", "alpha", "Beta"]) == 2
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert all(len(line) == 64 and set(line) <= HEX64 for line in lines)
    assert lines[0] == privacy_words.hash_word("alpha")
    assert privacy_words.add_words(path, ["BETA", "gamma"]) == 3
    assert path.stat().st_mode & 0o777 == 0o600


def test_load_hashes_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "w"
    h = privacy_words.hash_word("x")
    path.write_text(f"# note\n\n{h}\n")
    assert privacy_words.load_hashes(path) == [h]


def test_load_hashes_rejects_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "w"
    path.write_text(f"{privacy_words.hash_word('x')}\nnot-a-hash\n")
    with pytest.raises(ValueError, match="line 2"):
        privacy_words.load_hashes(path)


def test_words_file_environment_wins_then_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path, 'PRIVATE_WORDS_FILE = "rel/words.txt"')
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    assert privacy_words.words_file(repo) == repo / "rel" / "words.txt"
    monkeypatch.setenv("PRIVATE_WORDS_FILE", "/abs/other.txt")
    assert privacy_words.words_file(repo) == Path("/abs/other.txt")


def test_words_file_blank_or_missing_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    assert privacy_words.words_file(make_repo(tmp_path, "PRIVATE_WORDS_FILE=")) is None
    (tmp_path / "repo" / ".env").write_text("# PRIVATE_WORDS_FILE=x\nOTHER=1\n")
    assert privacy_words.words_file(tmp_path / "repo") is None
    (tmp_path / "repo" / ".env").unlink()
    assert privacy_words.words_file(tmp_path / "repo") is None


def test_cli_needs_private_words_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    assert "set PRIVATE_WORDS_FILE in .env" in capsys.readouterr().err


def test_cli_refuses_a_file_git_would_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=words.sha256")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    assert "is not ignored by git" in capsys.readouterr().err
    assert not (repo / "words.sha256").exists()


def test_cli_prints_the_count_never_the_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=words.sha256", ignore="words.sha256\n")
    type_answers(monkeypatch, "Zebracanary", "   ", "")
    assert privacy_words.main(["--repo", str(repo)]) == 0
    out = capsys.readouterr()
    assert "1 hash" in out.out
    assert "zebracanary" not in (out.out + out.err).lower()
    assert privacy_words.load_hashes(repo / "words.sha256") == [
        privacy_words.hash_word("zebracanary")
    ]


def test_cli_allows_a_file_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "elsewhere" / "w.sha256"
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(outside))
    repo = make_repo(tmp_path, "")
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 0
    assert "1 hash in the private word list" in capsys.readouterr().out
    assert outside.exists()
