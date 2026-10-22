"""The command-line contract an external program relies on, exercised through the real entry point.

Other programs call `u1convert` to check a model and to write a prepared copy. This
pins what they depend on, using the actual CLI in a subprocess (the same entry point
the installed command runs) - not an in-process import:

* `doctor <file> --json` prints one JSON object on stdout and exits 0 only when the
  verdict is READY. A valid CONVERTIBLE answer exits 1; a missing file exits 2. The exit code is a verdict
  signal, not a transport failure: a caller must read the JSON, not the exit code.
* `repair <file> --mode u1 -o <out>` writes a NEW file; with a different `<out>` the input is
  untouched (an `<out>` equal to the input is unsupported and not pinned).
* The JSON fields a caller reads: verdict, score, validation_issues,
  compatibility_issues, recommended_action, family, is_u1.

Scope: by default this is the source CLI, run with this interpreter, which does NOT
validate a packaged/installed executable. Point SNAPSTUDIO_CLI_EXE at one to run the
identical checks against it; until that has been done and recorded, packaging is
unverified.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

CUBE = """solid cube
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 10 10 0
  vertex 10 0 0
 endloop
endfacet
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 0 10 0
  vertex 10 10 0
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 10
  vertex 10 0 10
  vertex 10 10 10
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 10
  vertex 10 10 10
  vertex 0 10 10
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 10 0 10
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 10 0 10
  vertex 0 0 10
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 10 0 0
  vertex 10 10 0
  vertex 10 10 10
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 10 0 0
  vertex 10 10 10
  vertex 10 0 10
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 10 10 0
  vertex 0 10 0
  vertex 0 10 10
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 10 10 0
  vertex 0 10 10
  vertex 10 10 10
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 10 0
  vertex 0 0 0
  vertex 0 0 10
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 10 0
  vertex 0 0 10
  vertex 0 10 10
 endloop
endfacet
endsolid cube
"""


def run(*args, timeout=120):
    """Run the real CLI in a subprocess.

    By default the source entry point (what the `u1convert` command invokes). Set
    SNAPSTUDIO_CLI_EXE to the path of a built/installed `u1convert` executable to run
    the same checks against that instead - the separate packaging gate.
    """
    exe = os.environ.get("SNAPSTUDIO_CLI_EXE")
    cmd = [exe] if exe else [sys.executable, "-c", "from u1convert.cli import cli; cli()"]
    return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def parse_like_a_caller(stdout: str) -> dict:
    """The tolerant parse an external caller uses: the last {...} in stdout."""
    text = stdout.strip()
    start, end = text.rfind("{"), text.rfind("}")
    assert 0 <= start < end, f"no JSON object in stdout: {stdout!r}"
    return json.loads(text[start:end + 1])


@pytest.fixture()
def cube(tmp_path):
    p = tmp_path / "authored_cube.stl"
    p.write_text(CUBE)
    return str(p)


def test_doctor_on_a_convertible_model_returns_valid_json_and_exits_1(cube):
    before = sha(cube)
    r = run("doctor", cube, "--json")
    data = json.loads(r.stdout)                  # the whole of stdout is one JSON object
    assert data["verdict"] == "CONVERTIBLE"
    assert r.returncode == 1, "CONVERTIBLE is a valid answer that exits 1; callers must not treat that as failure"
    assert sha(cube) == before


def test_the_json_carries_the_fields_a_caller_reads(cube):
    data = json.loads(run("doctor", cube, "--json").stdout)
    for key in ("verdict", "score", "validation_issues", "compatibility_issues", "recommended_action", "family", "is_u1"):
        assert key in data, key
    assert isinstance(data["verdict"], str)
    assert isinstance(data["validation_issues"], list) and isinstance(data["compatibility_issues"], list)
    assert isinstance(data["is_u1"], bool)


def test_repair_writes_a_new_file_and_never_modifies_the_input(cube, tmp_path):
    before = sha(cube)
    out = tmp_path / "prepared_u1.3mf"
    r = run("repair", cube, "--mode", "u1", "-o", str(out))
    assert out.exists(), (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert out.stat().st_size > 0
    assert sha(cube) == before


def test_a_prepared_copy_is_then_ready_and_exits_0(cube, tmp_path):
    out = tmp_path / "prepared_u1.3mf"
    run("repair", cube, "--mode", "u1", "-o", str(out))
    r = run("doctor", str(out), "--json")
    data = parse_like_a_caller(r.stdout)
    assert (data["verdict"], r.returncode) == ("READY", 0)


def test_doctor_on_a_missing_file_does_not_masquerade_as_an_answer(tmp_path):
    r = run("doctor", str(tmp_path / "nope.3mf"), "--json")
    assert r.returncode == 2
    try:
        data = parse_like_a_caller(r.stdout)
    except AssertionError:
        return                                   # no JSON at all is acceptable
    assert data.get("verdict") != "READY"
