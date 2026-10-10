"""`u1convert doctor` prints issue counts and a rule-check note, not a score (#92)."""
import re
from pathlib import Path

from click.testing import CliRunner

from u1convert.cli import cli

ROOT = Path(__file__).resolve().parents[2]


def test_doctor_text_output_has_issue_counts_and_no_score():
    res = CliRunner().invoke(cli, ["doctor", str(ROOT / "examples" / "demo_offplate_foreign.3mf")])
    out = res.output
    assert re.search(r"Issues\s*: \d+ file-structure, \d+ U1-compatibility", out)
    assert not re.search(r"Score|/\s*100", out)
    assert "not a prediction that a print will succeed" in out


def test_doctor_json_is_unchanged_for_machines():
    res = CliRunner().invoke(cli, ["doctor", "--json", str(ROOT / "examples" / "sample_cube.stl")])
    assert '"verdict"' in res.output
