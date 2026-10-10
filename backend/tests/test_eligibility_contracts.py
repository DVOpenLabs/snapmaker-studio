"""readable != preparable, and every consumer reads the same eligibility record.

A project Studio can read but Prepare would refuse (an unverified per-object setting, a
part-level `nil` Orca 2.4.0 cannot load) must be reported identically by the Doctor, the
API, Model Connect, the Validation Center, the intelligence view, the Compatibility Doctor,
the project traits behind Ready Now, the CLI and Prepare itself. Each is driven through its
real entry point on files built at test time; none of them is handed a stand-in record.
"""
from __future__ import annotations

import hashlib
import threading
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import convert as conv
from snapstudio_core import doctor, eligibility, intelligence, project_traits, readiness
from snapstudio_core.container import ThreeMF
from snapstudio_core.errors import UnsoundOutput
from snapstudio_core.validation_report import readiness_report
from tests.test_api import _request
from tests.test_native_object_settings import BASE, SUPPORT_SHAPE, _inject
from tests.test_prepare_reliability import U1_BASE, _edit, _with_part_metadata

RAW_ENGINE_WORDS = ("must not be written into a prepared copy", "cannot vouch for")


def _blocked(tmp_path, kind: str, base: str = "bambu") -> str:
    if kind == "ironing":
        if base == "u1":
            return _edit(tmp_path, f"{kind}-u1.3mf", U1_BASE, object_extra={"ironing_type": "top surface"})
        return _inject(tmp_path, {**SUPPORT_SHAPE, "ironing_type": "top surface"}, f"{kind}.3mf")
    # C09-shaped: a part-level nil in a non-nullable speed, including outer_wall_speed
    extra = {"outer_wall_speed": "80,nil,80,nil", "inner_wall_speed": "50,nil"}
    if base == "u1":
        return _edit(tmp_path, f"{kind}-u1.3mf", U1_BASE, part_extra=extra)
    return _with_part_metadata(tmp_path, extra, f"{kind}.3mf")


CASES = [("ironing", "bambu"), ("nil", "bambu"), ("ironing", "u1"), ("nil", "u1")]


@pytest.fixture
def library_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SNAPSTUDIO_MODEL_DOWNLOADS_DIR", str(tmp_path))
    return tmp_path


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# --- the single record ----------------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_the_record_says_readable_but_not_preparable(tmp_path, kind, base):
    tm = ThreeMF.open(_blocked(tmp_path, kind, base))
    got = eligibility.assess(tm)
    assert got.readable and not got.preparable and got.problems and got.summary
    assert conv.structure_problems(tm) == got.problems          # Prepare's gate is the same list
    assert not any(w in got.summary for w in RAW_ENGINE_WORDS)


def test_a_clean_project_is_preparable_and_a_geometry_only_3mf_skips_the_gate(tmp_path):
    assert eligibility.assess(ThreeMF.open(_inject(tmp_path, SUPPORT_SHAPE))).preparable
    out = tmp_path / "geom.3mf"
    with zipfile.ZipFile(BASE) as z, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in z.infolist():
            if item.filename == "Metadata/project_settings.config":
                continue
            data = z.read(item.filename)
            if item.filename == "Metadata/model_settings.config":
                data = data.replace(b'<metadata key="extruder" value="1"/>',
                                    b'<metadata key="extruder" value="1"/>'
                                    b'<metadata key="ironing_type" value="x"/>', 1)
            dst.writestr(item, data)
    assert eligibility.assess(ThreeMF.open(str(out))).preparable


# --- Doctor (service + HTTP) ----------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_doctor_via_service_never_says_ready_and_never_says_unreadable(tmp_path, kind, base):
    d = service.doctor(_blocked(tmp_path, kind, base))
    assert d["prepare_blocked"] is True
    assert d["verdict"] not in ("READY", "HIGH_RISK")      # readable is not unreadable
    assert d["is_compatible"] is False
    assert "Prepare a U1 profile copy" not in d["recommended_action"]
    assert "open it in snapmaker orca and slice" not in d["recommended_action"].lower()
    assert d["validation_issues"] and not any(w in i for i in d["validation_issues"] for w in RAW_ENGINE_WORDS)
    assert d["structure_problems"]                          # raw wording lives here, separately
    assert d["schema_version"] == "doctor/1"


def test_a_genuine_u1_score_100_file_is_ready_only_when_nothing_blocks_it(tmp_path):
    clean = service.doctor(_edit(tmp_path, "clean.3mf", U1_BASE))
    assert clean["verdict"] == "READY" and clean["score"] == 100 and not clean["prepare_blocked"]
    blocked = service.doctor(_blocked(tmp_path, "ironing", "u1"))
    assert blocked["score"] == 100 and blocked["verdict"] != "READY"


def test_doctor_over_http_agrees(tmp_path):
    src = _blocked(tmp_path, "nil")
    httpd, token = build_server(port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, body = _request(port, "/doctor", {"path": src}, token)
    finally:
        httpd.shutdown()
    assert status == 200 and body["prepare_blocked"] is True and body["verdict"] != "HIGH_RISK"


def test_a_genuinely_unreadable_file_is_still_high_risk(tmp_path):
    junk = tmp_path / "junk.3mf"
    junk.write_bytes(b"not a zip")
    d = service.doctor(str(junk))
    assert d["verdict"] == "HIGH_RISK" and not d["prepare_blocked"]


# --- Model Connect / Model Browser import --------------------------------------

@pytest.mark.parametrize("kind", ["ironing", "nil"])
def test_a_readable_project_prepare_would_refuse_is_added_to_the_library(library_env, kind):
    src = _blocked(library_env, kind)
    got = service.register_downloaded_model(src, "www.printables.com",
                                            "https://www.printables.com/model/1-x")
    assert got["ok"] is True and got["prepare_blocked"] is True
    assert got["verdict"] != "HIGH_RISK" and got["ready_hint"] == "review"
    names = [p["name"] for p in service.library_list()["projects"]]
    assert Path(src).name in names                          # really in the library


# --- Validation Center ----------------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_the_validation_center_does_not_recommend_a_prepare_that_would_be_refused(tmp_path, kind, base):
    rep = readiness_report(_blocked(tmp_path, kind, base))
    assert rep["ready"] is False and rep["verdict"] != "READY"
    fits = [c for c in rep["checks"] if c["name"] == "Fits U1 profile checks"][0]
    assert fits["status"] == "warn" and "Prepare a U1 copy" not in fits["detail"]


# --- intelligence view ----------------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_the_intelligence_view_reports_the_same_thing(tmp_path, kind, base):
    info = intelligence.project_info(_blocked(tmp_path, kind, base))
    assert info["prepare_blocked"] is True and info["is_compatible"] is False
    assert info["verdict"] != "HIGH_RISK"
    assert info["issues"] and not any(w in i for i in info["issues"] for w in RAW_ENGINE_WORDS)


# --- Compatibility Doctor -------------------------------------------------------

@pytest.mark.parametrize("kind", ["ironing", "nil"])
def test_the_compatibility_check_does_not_call_a_blocked_project_clean(tmp_path, kind):
    res = service.compatibility_check(_blocked(tmp_path, kind))
    assert any(f["id"] == "prepare.blocked" for f in res["findings"])
    assert "No known U1 compatibility issues" not in res["summary"]


# --- project traits -> Ready Now ------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_ready_now_never_calls_a_blocked_project_ready_or_sends_it_to_prepare(tmp_path, kind, base):
    path = _blocked(tmp_path, kind, base)
    traits = project_traits.extract(path)
    assert traits["prepare_blocked"]["value"] is True
    res = readiness.classify_project({"path": path, "name": Path(path).name}, traits,
                                     {"reachable": True}, {"checks": []})
    assert res["bucket"] == readiness.NEEDS_ATTENTION
    assert "Prepare a U1 copy first" not in str(res)


def test_ready_now_traits_for_a_clean_project_are_not_blocked(tmp_path):
    assert project_traits.extract(_inject(tmp_path, SUPPORT_SHAPE))["prepare_blocked"]["value"] is False


# --- CLI ------------------------------------------------------------------------

def _cli(*args):
    from u1convert.cli import cli
    return CliRunner().invoke(cli, list(args))


@pytest.mark.parametrize("kind", ["ironing", "nil"])
def test_cli_doctor_and_repair_agree_with_prepare(tmp_path, kind):
    src = _blocked(tmp_path, kind)
    before = _sha(src)
    doc = _cli("doctor", src)
    assert doc.exit_code == 1 and "READY" not in doc.output.replace("Verdict : REPAIRABLE", "")
    assert "Snapmaker Orca" in doc.output and "Prepare a U1 profile copy" not in doc.output
    assert not any(w in doc.output for w in RAW_ENGINE_WORDS)
    out = tmp_path / "fixed.3mf"
    fixed = _cli("repair", src, "-o", str(out))
    assert fixed.exit_code != 0 and not out.exists()
    assert not Path(src).with_suffix(".orig.3mf").exists()
    assert not any(w in fixed.output for w in RAW_ENGINE_WORDS)
    assert _sha(src) == before


# --- Prepare itself -------------------------------------------------------------

@pytest.mark.parametrize("kind,base", CASES)
def test_prepare_refuses_in_plain_language_with_details_separate(tmp_path, kind, base):
    src = _blocked(tmp_path, kind, base)
    with pytest.raises(UnsoundOutput) as ei:
        service.convert(src, str(tmp_path / "out"))
    assert not any(w in str(ei.value) for w in RAW_ENGINE_WORDS)
    assert any(w in ei.value.details for w in RAW_ENGINE_WORDS[1:]) or "cannot vouch" in ei.value.details


# --- the Prusa brim_type collision (audit) -------------------------------------

def test_a_prusa_per_object_brim_type_stays_unsupported_and_blocks_nothing_removed(tmp_path):
    from snapstudio_core import fidelity
    prusa = Path(__file__).parent / "fixtures" / "prusa-multi-object" / "prusa_three_objects.3mf"
    src = tmp_path / "prusa_brim.3mf"
    with zipfile.ZipFile(prusa) as z, zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in z.infolist():
            data = z.read(item.filename)
            if item.filename == "Metadata/Slic3r_PE_model.config":
                data = data.replace(
                    b'<metadata type="object" key="name" value="A_two_volumes"/>',
                    b'<metadata type="object" key="name" value="A_two_volumes"/>\n'
                    b'  <metadata type="object" key="brim_type" value="outer_only"/>', 1)
            dst.writestr(item, data)
    prepared = conv.convert_to_u1(str(src), str(tmp_path / "out"))
    assert prepared.output_path
    report = fidelity.audit(str(src), prepared.output_path)
    rows = [r for r in report["rows"] if "brim_type" in r["detail"]]
    assert rows and all(r["status"] == "unsupported" for r in rows)
    assert report["claims"]["nothing_removed"] is False
