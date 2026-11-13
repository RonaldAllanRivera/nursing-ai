"""Reviewed binary files: blob ids in a private list next to the word list, never committed."""

import os
import subprocess
from pathlib import Path

import pytest
from reviewed_binaries import (
    AcceptError,
    BinaryBlob,
    accept,
    binary_blobs,
    load_reviewed,
    main,
    reviewed_file,
)

ZERO = "0" * 40
BLOB_A = "20b5be91886d0b6f26dc98a225c0dac05fe2c86e"
BLOB_B = "97cc663ca01800f83407f765dbdcd4736efa86bc"
TEXT_BLOB = "45b983be36b73c0788dc9cbcb76cbb80fc7bb057"


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    done = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return done.stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("PRIVATE_WORDS_FILE", raising=False)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    return path


@pytest.fixture
def private_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder of the private word list; the list itself doesn't have to exist."""
    folder = tmp_path / "private"
    folder.mkdir()
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(folder / "words.sha256"))
    return folder


def font(repo: Path, name: str = "web/public/fonts/a.woff2", data: bytes = b"wOF2\x00\x01") -> Path:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return Path(name)


def test_reviewed_file_sits_next_to_the_word_list(repo: Path, private_dir: Path) -> None:
    assert reviewed_file(repo) == private_dir / "reviewed-binaries.txt"


def test_reviewed_file_is_none_without_the_setting(repo: Path) -> None:
    assert reviewed_file(repo) is None


def test_accept_records_blob_id_and_path(repo: Path, private_dir: Path) -> None:
    name = font(repo)
    short = accept(repo, name)
    blob = git(repo, "hash-object", str(name)).strip()
    assert short == blob[:7]
    assert load_reviewed(private_dir / "reviewed-binaries.txt") == {blob: str(name)}


def test_accept_twice_records_once(repo: Path, private_dir: Path) -> None:
    name = font(repo)
    accept(repo, name)
    accept(repo, name)
    lines = (private_dir / "reviewed-binaries.txt").read_text().splitlines()
    assert len([line for line in lines if not line.startswith("#")]) == 1


def test_accept_refuses_text_file(repo: Path, private_dir: Path) -> None:
    (repo / "notes.md").write_text("plain text\n")
    with pytest.raises(AcceptError, match="text file"):
        accept(repo, Path("notes.md"))
    assert not (private_dir / "reviewed-binaries.txt").exists()


def test_accept_takes_git_attributes_binary_as_binary(repo: Path, private_dir: Path) -> None:
    (repo / ".gitattributes").write_text("*.dat binary\n")
    name = font(repo, "core/table.dat", b"no zero byte here")
    assert accept(repo, name) == git(repo, "hash-object", str(name)).strip()[:7]


def test_accept_refuses_a_path_outside_the_repo(
    repo: Path, private_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"\x00\x01")
    with pytest.raises(AcceptError, match="outside the repo"):
        accept(repo, outside)


def test_accept_refuses_a_missing_file(repo: Path, private_dir: Path) -> None:
    with pytest.raises(AcceptError, match="no such file"):
        accept(repo, Path("web/public/nothing.png"))


def test_accept_refuses_without_the_setting(repo: Path) -> None:
    name = font(repo)
    with pytest.raises(AcceptError, match="make private-words"):
        accept(repo, name)


def test_accept_refuses_a_list_git_would_commit(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "private").mkdir()
    monkeypatch.setenv("PRIVATE_WORDS_FILE", str(repo / "private" / "words.sha256"))
    name = font(repo)
    with pytest.raises(AcceptError, match="would be committed"):
        accept(repo, name)
    assert not (repo / "private" / "reviewed-binaries.txt").exists()


def test_load_reviewed_rejects_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "reviewed-binaries.txt"
    path.write_text(f"# reviewed\n{BLOB_A} web/a.png\nnot a blob id\n")
    with pytest.raises(ValueError, match="line 3 "):
        load_reviewed(path)


def test_load_reviewed_keeps_paths_with_spaces(tmp_path: Path) -> None:
    path = tmp_path / "reviewed-binaries.txt"
    path.write_text(f"{BLOB_A} web/public/a b.png\n\n")
    assert load_reviewed(path) == {BLOB_A: "web/public/a b.png"}


def test_binary_blobs_pairs_each_binary_with_its_blob() -> None:
    # `git log --raw --numstat -z --no-abbrev --format=%x1e%H` for: add a binary and a text
    # file, change the binary, delete the binary (newest first).
    log = (
        f"\x1ec3\x00\n:100644 000000 {BLOB_B} {ZERO} D\x00img.bin\x00-\t-\timg.bin\x00"
        f"\x1ec2\x00\n:100644 100644 {BLOB_A} {BLOB_B} M\x00img.bin\x00-\t-\timg.bin\x00"
        f"\x1ec1\x00\n:000000 100644 {ZERO} {BLOB_A} A\x00img.bin\x00"
        f":000000 100644 {ZERO} {TEXT_BLOB} A\x00t.txt\x00-\t-\timg.bin\x001\t0\tt.txt\x00"
    )
    assert binary_blobs(log) == [
        BinaryBlob("c3", "img.bin", BLOB_B),
        BinaryBlob("c2", "img.bin", BLOB_B),
        BinaryBlob("c1", "img.bin", BLOB_A),
    ]


def test_binary_blobs_reads_staged_output_with_a_tab_in_a_path() -> None:
    staged = f":000000 100644 {ZERO} {BLOB_A} A\x00a\tb.bin\x00-\t-\ta\tb.bin\x00"
    assert binary_blobs(staged) == [BinaryBlob("", "a\tb.bin", BLOB_A)]


def test_binary_blobs_fails_closed_on_a_binary_without_a_blob() -> None:
    with pytest.raises(OSError, match="blob"):
        binary_blobs("-\t-\timg.bin\x00")


def test_main_prints_the_short_id(
    repo: Path, private_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = font(repo)
    assert main(["--repo", str(repo), str(name)]) == 0
    blob = git(repo, "hash-object", str(name)).strip()
    assert capsys.readouterr().out == f"accepted {blob[:7]} {name}\n"


def test_main_reports_a_refusal_in_one_line(
    repo: Path, private_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.md").write_text("plain text\n")
    assert main(["--repo", str(repo), "notes.md"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("accept-binary: ")
    assert out.count("\n") == 1
    assert "plain text" not in out
