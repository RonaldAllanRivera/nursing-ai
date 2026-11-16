"""The private word list stores only SHA-256 hashes and the CLI never shows a word."""

import hashlib
import os
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


def test_cli_error_never_shows_the_setting_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=hiddenfolder/asfolder", ignore="hiddenfolder/\n")
    (repo / "hiddenfolder" / "asfolder").mkdir(parents=True)
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    out = capsys.readouterr()
    text = (out.out + out.err).lower()
    assert "cannot use private_words_file" in text
    assert "hiddenfolder" not in text
    assert "asfolder" not in text
    assert str(tmp_path).lower() not in text


def test_cli_malformed_file_names_the_line_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=words.sha256", ignore="words.sha256\n")
    (repo / "words.sha256").write_text(f"{privacy_words.hash_word('x')}\nbadlinetext\n")
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    out = capsys.readouterr()
    text = (out.out + out.err).lower()
    assert "line 2" in text
    assert "badlinetext" not in text
    assert "words.sha256" not in text


def test_add_words_dedupes_lines_already_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "w"
    h = privacy_words.hash_word("alpha")
    path.write_text(f"{h}\n{h}\n")
    assert privacy_words.add_words(path, ["Beta"]) == 2
    assert path.read_text().splitlines() == [h, privacy_words.hash_word("beta")]


REFUSAL = (
    "That entry can't be matched as one word (letters only, or a whole email): not saved."
    " Type each part of a hyphenated name separately."
)
UNMATCHABLE = ["mary-ann", "o'brien", "st4luke", "two words"]


def test_add_words_refuses_blank_and_unmatchable_entries(tmp_path: Path) -> None:
    path = tmp_path / "w"
    for bad in ("", "   ", *UNMATCHABLE):
        with pytest.raises(ValueError, match="one word") as info:
            privacy_words.add_words(path, [bad])
        assert bad.strip() == "" or bad not in str(info.value)
    assert not path.exists()


def test_add_words_accepts_a_word_and_a_whole_email(tmp_path: Path) -> None:
    path = tmp_path / "w"
    assert privacy_words.add_words(path, ["Zebracanary", "person@family.example"]) == 2


@pytest.mark.parametrize("bad", UNMATCHABLE)
def test_cli_refuses_an_entry_the_matcher_cannot_produce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad: str,
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=words.sha256", ignore="words.sha256\n")
    type_answers(monkeypatch, bad, "Zebracanary", "person@family.example", "")
    assert privacy_words.main(["--repo", str(repo)]) == 0
    out = capsys.readouterr()
    assert out.out.count(REFUSAL) == 1
    assert "2 hashes" in out.out
    assert bad.lower() not in (out.out + out.err).lower()
    assert privacy_words.load_hashes(repo / "words.sha256") == [
        privacy_words.hash_word("zebracanary"),
        privacy_words.hash_word("person@family.example"),
    ]


def test_cli_refuses_a_symlink_at_the_target_and_never_follows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=words.sha256", ignore="words.sha256\n")
    real = tmp_path / "elsewhere.sha256"
    real.write_text("")
    (repo / "words.sha256").symlink_to(real)
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    out = capsys.readouterr()
    assert "symbolic link" in out.err
    assert "elsewhere" not in (out.out + out.err)
    assert real.read_text() == ""
    assert (repo / "words.sha256").is_symlink()


def test_add_words_refuses_a_symlink_even_one_that_dangles(tmp_path: Path) -> None:
    link = tmp_path / "words.sha256"
    link.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="symbolic link"):
        privacy_words.add_words(link, ["Alpha"])
    assert not (tmp_path / "missing").exists()


def test_add_words_replaces_the_file_atomically_and_keeps_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "words.sha256"
    privacy_words.add_words(path, ["Alpha"])
    seen: list[tuple[str, str]] = []
    real_replace = privacy_words.os.replace

    def spy(src: str | Path, dst: str | Path) -> None:
        seen.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(privacy_words.os, "replace", spy)
    assert privacy_words.add_words(path, ["Beta"]) == 2
    assert len(seen) == 1
    src, dst = seen[0]
    assert dst == str(path)
    assert Path(src).parent == path.parent
    assert Path(src) != path
    assert path.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["words.sha256"]


def test_a_failed_write_leaves_the_old_list_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "words.sha256"
    privacy_words.add_words(path, ["Alpha"])
    before = path.read_text()

    def broken(src: str | Path, dst: str | Path) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(privacy_words.os, "replace", broken)
    with pytest.raises(OSError, match="No space"):
        privacy_words.add_words(path, ["Beta"])
    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["words.sha256"]


def test_cli_fails_closed_when_git_cannot_say_whether_the_file_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    (not_a_repo / ".env").write_text("PRIVATE_WORDS_FILE=words.sha256\n")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(not_a_repo)]) == 2
    assert "is not a git repository" in capsys.readouterr().err
    assert not (not_a_repo / "words.sha256").exists()


def test_cli_refuses_in_a_repo_folder_whose_name_is_not_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = tmp_path / os.fsdecode(b"repo-\xff")
    try:
        repo.mkdir()
    except OSError:
        pytest.skip("this filesystem refuses a folder name that is not UTF-8")
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("")
    (repo / ".env").write_text("PRIVATE_WORDS_FILE=words.sha256\n")
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    assert "is not ignored by git" in capsys.readouterr().err
    assert not (repo / "words.sha256").exists()


def test_cli_refuses_when_git_cannot_check_a_path_inside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    repo = make_repo(tmp_path, "PRIVATE_WORDS_FILE=link/words.sha256", ignore="real/\n")
    (repo / "real").mkdir()
    (repo / "link").symlink_to(repo / "real")
    type_answers(monkeypatch, "Alpha", "")
    assert privacy_words.main(["--repo", str(repo)]) == 2
    assert "git could not check that path" in capsys.readouterr().err
    assert not (repo / "real" / "words.sha256").exists()
