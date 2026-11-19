"""The Terraform check's plaintext-secret scan (its step 7) on files written to fool it.

Each fixture's name ends in _PASS (valid Terraform with no plaintext secret) or _FAIL (a plaintext
`value` on a parameter that is not a plain String, or a file the scan cannot follow to its end).
The scan runs under every awk on the machine, because check.sh calls plain `awk`.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAN = ROOT / "infra" / "scripts" / "ssm-plaintext.awk"
FIXTURES = sorted((Path(__file__).parent / "fixtures" / "ssm_scan").glob("*.tf"))
AWKS = [name for name in ("gawk", "mawk", "busybox") if shutil.which(name)] or ["awk"]

# Known gaps, each pinned so that fixing one turns its test into an unexpected pass. The first three
# miss a secret only in Terraform written to hide one; the last two fail closed on valid HCL.
KNOWN_GAPS = {
    "d01_type_string_in_interp_object_FAIL": 'a type = "String" inside an interpolation\'s object '
    "literal marks the parameter a plain String",
    "f03_marker_line_inside_heredoc_interp_balanced_FAIL": "a line equal to the heredoc marker "
    "inside a multi-line interpolation ends the heredoc early",
    "f04_unicode_marker_balanced_FAIL": "a non-ASCII heredoc marker with a balanced body is read "
    "as code",
    "f01_unicode_heredoc_marker_PASS": "a non-ASCII heredoc marker fails closed (could not parse)",
    "f02_marker_line_inside_heredoc_interp_PASS": "a marker-equal line inside a heredoc's "
    "interpolation fails closed (could not parse)",
}


def _cases() -> list[object]:
    cases: list[object] = []
    for fixture in FIXTURES:
        for awk in AWKS:
            gap = KNOWN_GAPS.get(fixture.stem)
            marks = [pytest.mark.xfail(reason=gap, strict=True)] if gap else []
            cases.append(pytest.param(fixture, awk, id=f"{fixture.stem}-{awk}", marks=marks))
    return cases


def _scan(fixture: Path, awk: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    # The repository stores every text file with LF endings, so a fixture named for CRLF gets its
    # CRLF copy here, whatever the checkout did.
    target = fixture
    if "crlf" in fixture.stem:
        target = tmp_path / fixture.name
        target.write_bytes(fixture.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    command = [*awk.split(), *(["awk"] if awk == "busybox" else [])]
    return subprocess.run(  # noqa: S603
        [*command, "-v", f"file={fixture.name}", "-f", str(SCAN), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_there_is_a_fixture_for_each_outcome() -> None:
    names = [f.stem for f in FIXTURES]
    assert len(names) == 43
    assert all(name.endswith(("_PASS", "_FAIL")) for name in names)
    assert set(KNOWN_GAPS) <= set(names)


@pytest.mark.parametrize(("fixture", "awk"), _cases())
def test_the_scan_answers_as_the_fixture_name_says(fixture: Path, awk: str, tmp_path: Path) -> None:
    result = _scan(fixture, awk, tmp_path)
    expected = 1 if fixture.stem.endswith("_FAIL") else 0
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        # The scan's own report, not an awk error that happens to exit 1.
        assert result.stdout.startswith(f"{fixture.name}:"), result.stdout + result.stderr
        assert result.stderr == ""
    # A finding names the file and the line, never the value.
    assert "hunter2" not in result.stdout + result.stderr


def test_the_terraform_check_runs_this_scan_on_every_file() -> None:
    script = (ROOT / "infra" / "scripts" / "check.sh").read_text()
    call = 'awk -v file="$f" -f "$repo_root/infra/scripts/ssm-plaintext.awk" "$f" || bad=1'
    assert call in script
    # The program lives in one place only.
    assert "function scan(" not in script
