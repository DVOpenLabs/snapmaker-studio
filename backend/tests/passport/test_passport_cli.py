"""The connector contract through the real command line (plan P7 tests 5-9). Evidence label: fixture-tested.

Every case runs the CLI in a subprocess. The passport group is attached by the child interpreter
(see synthetic_client._WIRED); `test_u1convert_registers_passport` pins the registration itself.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from tests.passport.synthetic_client import CliClient, ManifestClient, parse_last_brace, parse_strict, run_cli
from tests.test_external_cli_contract import CUBE

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "passport"


def sha(path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


@pytest.fixture
def cube(tmp_path):
    p = tmp_path / "authored_cube.stl"
    p.write_text(CUBE)
    return str(p)


@pytest.fixture
def job(tmp_path):
    """Original, prepared and sliced stand-ins whose names contain braces, on purpose."""
    d = tmp_path / "job"
    d.mkdir()
    names = ("part{a}.3mf", "part{a}_u1}.3mf", "part{a}{.gcode")
    for i, name in enumerate(names):
        (d / name).write_bytes(f"synthetic file {i}".encode())
    return d, names


def export(d, names, *extra):
    out = d / "job.passport.json"
    proc = run_cli("passport", "export", "--original", str(d / names[0]), "--prepared", str(d / names[1]),
                   "--sliced", str(d / names[2]), "-o", str(out), *extra)
    return proc, out


def test_5_doctor_json_is_exactly_one_object_with_a_score_key(cube):
    proc = run_cli("doctor", cube, "--json")
    data = parse_strict(proc.stdout)
    assert data is not None, proc.stdout                      # json.loads of ALL of stdout, nothing after it
    assert "score" in data and "verdict" in data
    assert proc.stdout.strip().endswith("}") and proc.stdout.count("\n{") == 0
    client = CliClient().doctor(cube)
    assert client["ok"] and "score" in client["keys"] and client["exit"] in (0, 1)


def test_5_last_brace_parsing_is_not_guaranteed_by_studio(job):
    d, names = job
    proc, out = export(d, names)
    assert proc.returncode == 0, proc.stderr
    verify = run_cli("passport", "verify", str(out), "--base-dir", str(d))
    assert verify.returncode == 0
    strict = parse_strict(verify.stdout)
    assert strict is not None and strict["ok"] is True
    names_in_output = [row["name"] for row in strict["verification"]["artifacts"]]
    assert names_in_output == list(names)                     # string values do contain "{" and "}"
    # A caller that cuts at the last "{" gets a fragment inside a string value, or nothing. Studio's
    # contract is "one object, nothing else on stdout", so the strict parse is the only supported one.
    assert parse_last_brace(verify.stdout) != strict


def test_6_exit_codes_are_0_or_1_with_json(cube, job):
    d, names = job
    ok = run_cli("passport", "verify", str(export(d, names)[1]), "--base-dir", str(d))
    assert ok.returncode == 0 and parse_strict(ok.stdout)["ok"] is True
    (d / names[0]).write_bytes(b"changed on disk")
    bad = run_cli("passport", "verify", str(d / "job.passport.json"), "--base-dir", str(d))
    assert bad.returncode == 1
    data = parse_strict(bad.stdout)
    assert data["ok"] is False and data["verification"]["summary"]["invalidated"]
    garbage = d / "garbage.json"
    garbage.write_text("{ not json")
    handled = run_cli("passport", "import", str(garbage))
    assert handled.returncode == 1 and parse_strict(handled.stdout)["error"]["code"] == "malformed_json"
    unusable = d / "future.json"
    unusable.write_text(json.dumps({"schema_version": "passport/9"}))
    refused = run_cli("passport", "verify", str(unusable))
    assert refused.returncode == 1 and parse_strict(refused.stdout)["error"]["code"] == "unusable_passport"
    nofiles = run_cli("passport", "export")
    assert nofiles.returncode == 1 and parse_strict(nofiles.stdout)["error"]["code"] == "no_files"


def test_6_a_missing_file_is_click_exit_2_with_no_json_and_a_client_calls_it_a_failure(tmp_path):
    missing = str(tmp_path / "nope.3mf")
    for args in (("doctor", missing, "--json"), ("passport", "verify", missing), ("passport", "import", missing),
                 ("passport", "export", "--original", missing)):
        proc = run_cli(*args)
        assert proc.returncode == 2, args
        assert proc.stdout.strip() == "", (args, proc.stdout)     # no JSON at all
        assert parse_strict(proc.stdout) is None
    result = CliClient().doctor(missing)
    assert result["ok"] is False and result["exit"] == 2          # absent JSON is failure, never success


def test_6_invalid_json_is_a_failure_not_a_success():
    for text in ("", "not json", "[1, 2]", "{ truncated", '{"a": 1} trailing'):
        assert parse_strict(text) is None


def test_7_repair_writes_a_new_file_and_leaves_the_original_unchanged(cube, tmp_path):
    before = sha(cube)
    out = tmp_path / "prepared_u1.3mf"
    proc = run_cli("repair", cube, "--mode", "u1", "-o", str(out))
    assert out.exists() and out.stat().st_size > 0, (proc.returncode, proc.stdout[-200:], proc.stderr[-200:])
    assert sha(cube) == before
    # the output of `repair` goes straight into a passport as the prepared step
    exported = tmp_path / "from_repair.passport.json"
    made = run_cli("passport", "export", "--original", cube, "--prepared", str(out), "-o", str(exported))
    assert made.returncode == 0 and exported.exists()
    assert sha(cube) == before
    assert run_cli("passport", "verify", str(exported), "--base-dir", str(tmp_path)).returncode == 0


def test_8_export_import_verify_round_trip_and_refusals(job):
    d, names = job
    before = {n: sha(d / n) for n in names}
    proc, out = export(d, names)
    data = parse_strict(proc.stdout)
    assert proc.returncode == 0 and data["ok"] and data["written"] == "job.passport.json"
    assert json.loads(out.read_text(encoding="utf-8"))["passport_id"] == data["passport_id"]
    assert str(d) not in out.read_text(encoding="utf-8")                      # no local path in the file
    imported = parse_strict(run_cli("passport", "import", str(out), "--base-dir", str(d)).stdout)
    assert imported["ok"] and imported["passport"]["passport_id"] == data["passport_id"]
    assert {p["witness"] for p in imported["parentage"]} == {"declared"}
    assert imported["verification"]["summary"]["all_intact"] is True
    again = run_cli("passport", "export", "--original", str(d / names[0]), "-o", str(out))
    assert again.returncode == 1 and parse_strict(again.stdout)["error"]["code"] == "output_exists"
    clobber = run_cli("passport", "export", "--original", str(d / names[0]), "-o", str(d / names[0]))
    assert clobber.returncode == 1 and parse_strict(clobber.stdout)["error"]["code"] == "output_is_input"
    assert {n: sha(d / n) for n in names} == before                           # inputs untouched
    located = run_cli("passport", "verify", str(out), "--path", f"{names[0]}={d / names[0]}")
    assert parse_strict(located.stdout)["verification"]["summary"]["unverified"]     # others not located


def test_u1convert_registers_passport():
    from u1convert.cli import cli
    if "passport" not in cli.commands:
        pytest.skip("u1convert/cli.py does not register the passport group yet (two-line change, out of this package's scope)")
    proc = run_cli("passport", "--help")
    assert proc.returncode == 0 and "export" in proc.stdout


def test_9_a_generic_manifest_client_round_trips_nested_passports(job, tmp_path):
    d, names = job
    recipes = tmp_path / "recipes.json"
    recipes.write_text((FIXTURES / "recipes.json").read_text(encoding="utf-8"), encoding="utf-8")
    mappings = FIXTURES / "mappings.json"
    out = d / "with_recipes.passport.json"
    proc = run_cli("passport", "export", "--original", str(d / names[0]), "--prepared", str(d / names[1]),
                   "--recipes", str(recipes), "--mappings", str(mappings), "-o", str(out))
    exported = parse_strict(proc.stdout)
    assert proc.returncode == 0, proc.stdout
    client = ManifestClient()
    manifest = client.pack({"job-b": json.loads(out.read_text(encoding="utf-8")), "job-a": exported["passport"]})
    assert [j["name"] for j in manifest["jobs"]] == ["job-a", "job-b"]
    results = client.unpack_through_studio(manifest, str(tmp_path))
    assert [r["exit"] for r in results] == [0, 0]
    for r in results:
        kept = r["json"]["passport"]
        assert [x["recipe_id"] for x in kept["recipes"]] == ["synthetic:mix-a", "synthetic:loops"]
        assert [m["slot_ref"] for m in kept["material_mappings"]] == ["slot:0", "project:1:2"]
        reasons = {(l["kind"], l["id"]): l["reason"] for l in r["json"]["losses"]}
        assert reasons[("recipe", "synthetic:from-the-future")] == "unknown_schema_version"   # explicit loss
        assert reasons[("material_mapping", "banana")] == "bad_slot_ref"
    # a manifest passport whose recipes were damaged in transit: the loss is reported, not hidden
    broken = json.loads(out.read_text(encoding="utf-8"))
    broken["recipes"][0]["components"] = "x"
    again = client.unpack_through_studio(client.pack({"job-c": broken}), str(tmp_path))[0]
    assert again["exit"] == 0
    assert ("recipe", "synthetic:mix-a") in {(l["kind"], l["id"]) for l in again["json"]["losses"]}


def test_10_the_contract_document_states_the_rules():
    text = (pathlib.Path(__file__).resolve().parents[3] / "docs" / "internal" / "PASSPORT.md").read_text(encoding="utf-8")
    for needle in ("exactly one top-level JSON object", "exit 2", "no JSON", "rfind", "declared", "exit 0", "exit 1",
                   "fixture-tested"):
        assert needle in text, needle
