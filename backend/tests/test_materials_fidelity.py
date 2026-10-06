"""Project Materials fidelity: what happened to each slot, said in plain language, computed from
the files and the selections — and checked against the prepared copy again when shown."""
from __future__ import annotations

import copy
import json

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import fidelity, materials_fidelity as mf
from snapstudio_core import material_mapping as mm
from snapstudio_core.convert import convert_to_u1
from tests.test_api import _request, _run
from tests.test_project_materials import (MATTE, SNAPSPEED, _cfg, _project, _shared, catalog, env,  # noqa: F401
                                          profiles, store)

SECRET = "SECRET-PROVIDER-KEY-123"
HOST = "192.168.77.77"
SPOOL = {"provider": "spoolman", "id": 124, "vendor": "Yoopai", "material": "PLA", "subtype": "Matte",
         "colour": "#00AA11"}
LINE_SLOT2 = ("Slot 2: Yoopai PLA Matte Green #124 mapped to 'Snapmaker PLA Matte @U1'. "
              "Colour changed to Green. Temperature, flow and cooling come from the installed "
              "Snapmaker PLA Matte @U1 preset.")


def _prepare(tmp_path, selections, mode="preserve", project=None, out="o"):
    src = project or _project(tmp_path)
    result = service.convert(str(src), str(tmp_path / out), mode, False, {"selections": selections})
    return src, result


def _record(result) -> dict:
    return result["settings_summary"]["project_materials"]["fidelity"]


def _mapped(tmp_path, **extra):
    sel = {"slot": 1, "preset": MATTE, "colour": "#00AA11", "spool": {**SPOOL, **extra}}
    return _prepare(tmp_path, [sel])


# --- per-slot structure ---------------------------------------------------------------------

def test_a_mapped_slot_records_source_selection_output_declarations_and_discrepancies(env, tmp_path):
    _, result = _mapped(tmp_path)
    rec = _record(result)
    assert rec["schema"] == mf.SCHEMA and rec["mode"] == "preserve" and rec["nozzle"] == "0.4"
    assert [s["slot"] for s in rec["slots"]] == [0, 1, 2]
    s = rec["slots"][1]
    assert s["label"] == "Slot 2" and s["involved"] is True
    assert s["source"] == {"settings_id": "Generic PLA @BBL H2D", "vendor": "Bambu Lab", "type": "PLA",
                           "colour": "#00FF00", "declared_keys": []}
    assert s["selection"] == {"provider": "spoolman", "spool_id": "124", "vendor": "Yoopai", "material": "PLA",
                              "subtype": "Matte", "colour": "#00AA11", "color_name": "green",
                              "label": "Yoopai PLA Matte Green #124", "preset": MATTE,
                              "mapping_source": "manual"}
    out = s["output"]
    assert out["preset_written"] == MATTE and out["colour_written"] == "#00AA11"
    assert out["colour_changed"] is True and out["vendor_type_origin"] == "preset"
    assert {"key": "filament_settings_id", "old": "Generic PLA @BBL H2D", "new": MATTE} in out["changed_fields"]
    assert {"key": "filament_colour", "old": "#00FF00", "new": "#00AA11"} in out["changed_fields"]
    assert {"key": "filament_vendor", "value": "Bambu Lab"} in out["preserved_fields"]
    assert {"key": "filament_type", "value": "PLA"} in out["preserved_fields"]
    assert out["preset_controlled"]["fields"][:3] == ["temperature", "flow", "volumetric speed"]
    assert "nozzle_temperature" in out["preset_controlled"]["keys"]
    d = s["declarations"]
    assert d["source"] == [] and d["retained"] == [] and d["removed_by_mode"] == []
    assert d["withdrawn_studio_added"] == ["nozzle_temperature"]
    assert [x["code"] for x in s["discrepancies"]] == ["vendor_mismatch"]
    assert "Yoopai" in s["discrepancies"][0]["text"] and "did not override" in s["discrepancies"][0]["text"]
    assert rec["counts"] == {"slots": 3, "involved": 1, "presets_written": 1, "colours_written": 1}


def test_plain_language_line_for_a_mapped_slot(env, tmp_path):
    _, result = _mapped(tmp_path)
    rec = _record(result)
    assert rec["slots"][1]["line"] == LINE_SLOT2
    assert rec["lines"][0] == LINE_SLOT2
    assert ("Slot 2: Studio did not declare nozzle_temperature, so Snapmaker Orca takes them from "
            "'Snapmaker PLA Matte @U1'.") in rec["lines"]


def test_untouched_slots_say_so_and_note_a_possible_customized_preset(env, tmp_path):
    _, result = _mapped(tmp_path)
    s = _record(result)["slots"][0]
    assert s["involved"] is False and s["selection"] is None
    assert s["line"] == "Slot 1: no Project Materials choice; Studio keeps the project's own filament identity."
    assert s["output"]["preset_written"] is None and s["output"]["vendor_type_origin"] == "project"
    assert s["output"]["preset_controlled"] == {"fields": [], "keys": []}
    assert [d["code"] for d in s["discrepancies"]] == ["customized_preset_possible"]
    assert "may treat it as a Customized Preset" in s["discrepancies"][0]["text"]
    assert not s["line"].count("Customized")


def test_a_preset_chosen_without_a_spool_is_described_as_chosen_by_you(env, tmp_path):
    _, result = _prepare(tmp_path, [{"slot": 0, "preset": SNAPSPEED}])
    s = _record(result)["slots"][0]
    assert s["line"] == ("Slot 1: mapped to 'Snapmaker PLA SnapSpeed @U1' (chosen by you). Temperature, flow "
                         "and cooling come from the installed Snapmaker PLA SnapSpeed @U1 preset.")
    assert s["selection"]["mapping_source"] == "manual" and s["selection"]["provider"] is None
    assert {"key": "default_filament_profile", "old": "Bambu PLA Basic @BBL H2D", "new": SNAPSPEED} in \
        s["output"]["changed_fields"]


def test_a_colour_only_slot_keeps_its_identity_and_says_so(env, tmp_path):
    _, result = _prepare(tmp_path, [{"slot": 2, "colour": "#FF8800", "spool": {**SPOOL, "id": 9, "material": "PETG",
                                                                                  "subtype": None, "colour": "#FF8800"}}])
    s = _record(result)["slots"][2]
    assert s["output"]["preset_written"] is None and s["output"]["colour_written"] == "#FF8800"
    assert [c["key"] for c in s["output"]["changed_fields"]] == ["filament_colour"]
    assert {"key": "filament_settings_id", "value": "Generic PETG @BBL H2D"} in s["output"]["preserved_fields"]
    assert s["line"].startswith("Slot 3: Colour changed to Orange (from Yoopai PETG Orange #9).")
    assert "Studio keeps the project's filament identity 'Generic PETG @BBL H2D'." in s["line"]
    assert "Orca may treat it as a Customized Preset and rename it." in s["line"]
    assert s["selection"]["mapping_source"] is None


def test_a_colour_that_was_already_right_is_not_called_a_change(env, tmp_path):
    _, result = _prepare(tmp_path, [{"slot": 1, "preset": MATTE, "colour": "#00FF00"}])
    s = _record(result)["slots"][1]
    assert s["output"]["colour_changed"] is False and "Colour was already Green." in s["line"]
    assert [c["key"] for c in s["output"]["changed_fields"]] == ["filament_settings_id"]


# --- how the preset was matched ----------------------------------------------------------------

def test_mapping_source_is_computed_not_asserted(env, tmp_path):
    sel = lambda **x: [{"slot": 1, "preset": MATTE, "spool": {**SPOOL, **x}}]   # noqa: E731
    src = _project(tmp_path)

    def source(selections, name):
        return _record(service.convert(str(src), str(tmp_path / name), "preserve", False,
                                       {"selections": selections}))["slots"][1]["selection"]["mapping_source"]

    assert source(sel(), "a") == "manual"
    assert source(sel(slicer_filament=MATTE), "b") == "slicer_filament_confirmed"
    assert source(sel(slicer_filament="Something else"), "c") == "manual"
    service.material_mapping_confirm({"scope": "signature", "provider": "spoolman", "vendor": "Yoopai",
                                      "material": "PLA", "subtype": "Matte", "preset": MATTE})
    assert source(sel(), "d") == "saved_signature"
    service.material_mapping_confirm({"scope": "spool", "provider": "spoolman", "spool_id": 124, "preset": MATTE})
    assert source(sel(), "e") == "saved_spool"
    # a saved mapping that points somewhere else is a discrepancy, and the mapping source is not claimed
    other = [{"slot": 1, "preset": SNAPSPEED, "spool": {**SPOOL}}]
    rec = _record(service.convert(str(src), str(tmp_path / "f"), "preserve", False, {"selections": other}))
    slot = rec["slots"][1]
    assert slot["selection"]["mapping_source"] == "manual"
    assert "mapping_overridden" in [d["code"] for d in slot["discrepancies"]]


def test_a_material_mismatch_between_provider_and_preset_is_reported(env, tmp_path):
    _, result = _prepare(tmp_path, [{"slot": 1, "preset": MATTE, "spool": {**SPOOL, "material": "PETG"}}])
    codes = [d["code"] for d in _record(result)["slots"][1]["discrepancies"]]
    assert "material_mismatch" in codes


# --- declarations ---------------------------------------------------------------------------------

def test_recommended_removed_declarations_and_the_corrected_guard_case(env, tmp_path):
    src = _project(tmp_path, _shared())
    result = service.convert(str(src), str(tmp_path / "r"), "recommended", False,
                             {"selections": [{"slot": 2, "preset": "Generic PETG @U1"}]})
    assert result["blocked"] is False
    rec = _record(result)
    sentence = ("Source contained conflicting vendor declarations on slots sharing 'Snapmaker PLA Matte @U1'. "
                "Recommended mode removed those declarations before Prepare, so no Orca propagation "
                "conflict remains.")
    assert sentence in rec["lines"]
    s0 = rec["slots"][0]
    assert s0["declarations"]["source"] == ["filament_vendor"] and s0["declarations"]["removed_by_mode"] == ["filament_vendor"]
    assert s0["declarations"]["retained"] == []
    assert "Slot 1: Recommended mode removed the declarations filament_vendor before Prepare." in rec["lines"]
    assert rec["guard"]["conflicts"] == [] and rec["guard"]["removed_by_mode"][0]["key"] == "filament_vendor"
    assert rec["guard"]["blocking"] is False and rec["mode"] == "recommended"


def test_source_declarations_that_survive_are_retained(env, tmp_path):
    cfg = _cfg(different_settings_to_system=["", "", "filament_type", "", ""])
    _, result = _prepare(tmp_path, [{"slot": 1, "preset": MATTE}], project=_project(tmp_path, cfg))
    d = _record(result)["slots"][1]["declarations"]
    assert d["source"] == ["filament_type"] and d["retained"] == ["filament_type"]
    assert d["withdrawn_studio_added"] == ["nozzle_temperature"] and d["removed_by_mode"] == []


def test_a_shared_preset_with_declared_values_is_a_warning_in_the_record(env, tmp_path):
    cfg = _cfg(filament_settings_id=[MATTE, MATTE, "Generic PETG @U1"], filament_vendor=["A", "A", "A"],
               different_settings_to_system=["", "nozzle_temperature", "", "", ""])
    _, result = _prepare(tmp_path, [{"slot": 2, "preset": "Generic PETG @U1"}], project=_project(tmp_path, cfg))
    assert result["blocked"] is False
    rec = _record(result)
    kinds = [p["kind"] for p in rec["slots"][1]["declarations"]["propagation"]]
    assert kinds == ["shared_preset", "declared_values"]
    # slot 2 also declares it: Studio's own Preserve declaration on a slot it did not map
    text = ("Snapmaker Orca copies declared values (nozzle_temperature) from slots 1 and 2 to every slot "
            "using “Snapmaker PLA Matte @U1”.")
    assert text in rec["lines"]
    assert rec["slots"][0]["declarations"]["propagation"][0]["text"] == \
        "Slot 1 shares “Snapmaker PLA Matte @U1” with slot 2."


# --- backward compatibility, verification, secrets ------------------------------------------------

def test_without_project_materials_nothing_about_materials_appears(env, tmp_path):
    src = _project(tmp_path)
    result = service.convert(str(src), str(tmp_path / "plain"), "preserve", False)
    assert "project_materials" not in result["settings_summary"]
    report = fidelity.audit(str(src), result["output_path"])
    assert report["schema_version"] == "fidelity/1" and "materials" not in report
    # an unusable record is ignored, not attached
    for junk in ({}, {"schema": "other"}, {"schema": mf.SCHEMA, "slots": "x"}):
        again = fidelity.audit(str(src), result["output_path"], junk)
        assert again["schema_version"] == "fidelity/1" and "materials" not in again


def test_the_audit_attaches_a_checked_materials_section_and_bumps_the_schema(env, tmp_path):
    src, result = _mapped(tmp_path)
    base = fidelity.audit(str(src), result["output_path"])
    report = fidelity.audit(str(src), result["output_path"], _record(result))
    assert report["schema_version"] == "fidelity/2"
    assert {k: v for k, v in report.items() if k not in ("materials", "schema_version")} == \
        {k: v for k, v in base.items() if k != "schema_version"}
    assert report["materials"]["verified"] is True
    assert all(s["verified"] and s["verification"] == [] for s in report["materials"]["slots"])


def test_a_record_that_does_not_match_the_copy_is_marked_unverified(env, tmp_path):
    src, result = _mapped(tmp_path)
    forged = copy.deepcopy(_record(result))
    forged["slots"][1]["output"]["preset_written"] = SNAPSPEED
    forged["slots"][1]["output"]["colour_written"] = "#010203"
    report = fidelity.audit(str(src), result["output_path"], forged)
    slot = report["materials"]["slots"][1]
    assert report["materials"]["verified"] is False and slot["verified"] is False
    assert len(slot["verification"]) == 2 and "does not carry the preset" in slot["verification"][0]


def test_unknown_keys_in_a_record_are_dropped(env, tmp_path):
    src, result = _mapped(tmp_path)
    noisy = copy.deepcopy(_record(result))
    noisy["provider_key"] = SECRET
    noisy["slots"][1]["provider_url"] = f"http://{HOST}:7912"
    noisy["slots"][1]["selection"]["extra"] = "x" * 5000
    clean = mf.sanitize(noisy)
    blob = json.dumps(clean)
    assert SECRET not in blob and HOST not in blob and "provider_key" not in blob
    assert len(clean["slots"][1]["selection"]["extra"]) <= 400


def test_no_provider_secret_or_weight_reaches_the_record(env, tmp_path):
    spool = {**SPOOL, "provider_key": SECRET, "url": f"http://{HOST}:7912", "api_key": SECRET, "token": SECRET,
             "host": HOST, "remaining_g": 412.5, "remaining_quality": "tracked", "remaining_as_of": "2026-10-01"}
    _, result = _prepare(tmp_path, [{"slot": 1, "preset": MATTE, "colour": "#00AA11", "spool": spool}])
    blob = json.dumps(result["settings_summary"]["project_materials"]).lower()
    for word in (SECRET.lower(), HOST, "412.5", "remaining", "tracked", "api_key", "provider_key", "token"):
        assert word not in blob, word
    sel = _record(result)["slots"][1]["selection"]
    assert set(sel) == {"provider", "spool_id", "vendor", "material", "subtype", "colour", "color_name",
                        "label", "preset", "mapping_source"}


def test_the_record_is_only_built_when_project_materials_made_a_choice(tmp_path, catalog):
    src = _project(tmp_path)
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "a"), filament_catalog=catalog)
    assert "fidelity" not in res.settings_summary["project_materials"]
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "b"), confirmed_presets={1: MATTE}, filament_catalog=catalog)
    assert res.settings_summary["project_materials"]["fidelity"]["slots"][1]["line"].startswith("Slot 2: mapped to")


def test_http_fidelity_route_with_materials(env, tmp_path):
    src, result = _mapped(tmp_path)
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        body = {"original": str(src), "prepared": result["output_path"], "materials": _record(result)}
        st, out = _request(port, "/fidelity", body, token)
        assert st == 200 and out["schema_version"] == "fidelity/2" and out["materials"]["verified"] is True
        assert out["materials"]["lines"][0] == LINE_SLOT2
        st, out = _request(port, "/fidelity", {"original": str(src), "prepared": result["output_path"]}, token)
        assert st == 200 and out["schema_version"] == "fidelity/1" and "materials" not in out
        assert _request(port, "/fidelity", {**body, "materials": "x"}, token)[0] == 400
        body["materials"] = {**_record(result), "provider_key": SECRET}
        st, out = _request(port, "/fidelity", body, token)
        assert st == 200 and SECRET not in json.dumps(out)
    finally:
        httpd.shutdown()
