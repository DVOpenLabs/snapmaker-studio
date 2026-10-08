"""Full-inventory spool choice and what a chosen spool does (and does not do) to the filament preset.

Two things the first real SpoolEase tester reported:

* he could only pick among the few spools Studio ranked for a model colour, never a spool of his own
  choosing (a model that asks for red, a spool he deliberately wants blue);
* a prepared copy of a Bambu-authored project opened in Snapmaker Orca still named Bambu filament presets.

The second is two different cases, and the product must never let them blur:

1. a physical spool is chosen and no Orca preset is: the spool decides the colour, the project's own filament
   preset stays, and Studio says so in words;
2. an installed Orca SYSTEM preset is confirmed: the copy names exactly that preset for that slot.
"""
import json
import zipfile

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import project_materials as pm
from snapstudio_core.materials_fidelity import SPOOL_WITHOUT_PRESET
from tests.test_api import _request, _run
from tests.test_project_materials import (MATTE, Provider, _cfg, _prepared, _project, catalog, env,  # noqa: F401
                                          profiles, spool)

URL = "http://192.168.1.50:7912"
SENTENCE = "Spool selected, but no Orca preset selected. The project's existing filament preset will remain."


def _inventory(tmp_path, monkeypatch, spools, kind="spoolman", slot=0):
    Provider(monkeypatch, spools=spools)
    return service.project_materials_inventory(str(_project(tmp_path)), slot, provider=kind, provider_url=URL)


STOCK = [
    spool(1, color="#FF0000"),                                   # red PLA: what the model asks for
    spool(2, color="#0000FF", subtype="Basic"),                  # blue PLA: a deliberate other colour
    spool(3, material="PETG", subtype=None, color="#00FF00"),    # another material family
    spool(4, archived=True, color="#FF0000"),                    # archived: never offered
]


# --- A. the whole inventory ---------------------------------------------------------------------

def test_the_ranked_list_is_unchanged_and_the_inventory_adds_every_other_spool(env, tmp_path, monkeypatch):
    Provider(monkeypatch, spools=STOCK)
    path = str(_project(tmp_path))
    ranked = service.project_materials(path, provider="spoolman", provider_url=URL, limit=1)["slots"][0]
    assert [c["spool_id"] for c in ranked["candidates"]] == ["1"] and ranked["candidate_count"] == 2
    full = service.project_materials_inventory(path, 0, provider="spoolman", provider_url=URL)
    assert [e["spool_id"] for e in full["entries"]] == ["1", "2", "3"]       # same family first, archived never
    assert full["count"] == 3 and full["same_family_count"] == 2 and full["supported"] is True


def test_a_different_colour_is_information_never_a_warning_or_a_blocker(env, tmp_path, monkeypatch):
    full = _inventory(tmp_path, monkeypatch, STOCK)
    blue = next(e for e in full["entries"] if e["spool_id"] == "2")
    assert blue["family_match"] is True and blue["warnings"] == []
    assert any(r["code"] == "colour_distance" for r in blue["reasons"])       # shown, not enforced


def test_a_different_material_family_is_flagged_for_confirmation_with_the_engines_words(env, tmp_path, monkeypatch):
    full = _inventory(tmp_path, monkeypatch, STOCK)
    petg = next(e for e in full["entries"] if e["spool_id"] == "3")
    assert petg["family_match"] is False
    (warning,) = petg["warnings"]
    assert warning["code"] == "material_family_differs" and warning["requires_confirmation"] is True
    assert "PETG" in warning["text"] and "PLA" in warning["text"]
    assert any(r["code"] == "material_differs" for r in petg["reasons"])
    # the facts the picker shows are all there: colour, vendor, material, id, weight, preset status
    for key in ("colour", "color_name", "vendor", "material", "subtype", "spool_id", "remaining_g", "mapping"):
        assert key in petg
    assert petg["mapping"]["status"] in ("proven", "needs_confirmation", "no_match")


@pytest.mark.parametrize("kind", ["spoolease", "spoolman", "bambuddy"])
def test_every_provider_uses_the_same_path(env, tmp_path, monkeypatch, kind):
    full = _inventory(tmp_path, monkeypatch, STOCK, kind=kind)
    assert full["provider"] == {"kind": kind, "available": True, "error_code": None}
    assert [e["spool_id"] for e in full["entries"]] == ["1", "2", "3"]
    assert all(e["provider"] == kind for e in full["entries"])


def test_an_unreadable_provider_gives_an_empty_inventory_not_a_crash(env, tmp_path, monkeypatch):
    from snapstudio_core import material_providers as providers

    def down(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(providers, "read", down)
    full = service.project_materials_inventory(str(_project(tmp_path)), 0, provider="spoolman", provider_url=URL)
    assert full["entries"] == [] and full["provider"]["available"] is False


def test_the_inventory_never_selects_and_never_writes_to_the_provider(env, tmp_path, monkeypatch):
    fake = Provider(monkeypatch, spools=STOCK)
    service.project_materials_inventory(str(_project(tmp_path)), 1, provider="spoolman", provider_url=URL)
    assert len(fake.reads) == 1                                   # one read, nothing else
    assert not (tmp_path / "data").exists() or not list((tmp_path / "data").glob("**/material*"))


def test_a_slot_the_project_does_not_have_is_refused(env, tmp_path, monkeypatch):
    Provider(monkeypatch, spools=STOCK)
    with pytest.raises(ValueError, match="slot 9"):
        service.project_materials_inventory(str(_project(tmp_path)), 9, provider="spoolman", provider_url=URL)


def test_an_stl_has_no_inventory(env, tmp_path):
    assert service.project_materials_inventory(str(tmp_path / "x.stl"), 0)["supported"] is False


def test_inventory_http_route_needs_the_token(monkeypatch, env, tmp_path):
    Provider(monkeypatch, spools=STOCK)
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        body = {"path": str(_project(tmp_path)), "slot": 0, "provider": "spoolman", "provider_url": URL}
        assert _request(port, "/project_materials/inventory", body, None)[0] == 401
        st, out = _request(port, "/project_materials/inventory", body, token)
        assert st == 200 and [e["spool_id"] for e in out["entries"]] == ["1", "2", "3"]
        assert _request(port, "/project_materials/inventory", {**body, "slot": 9}, token)[0] == 400
        # a malformed request is a 400, never a 500 and never a silent slot 0
        without_slot = {k: v for k, v in body.items() if k != "slot"}
        for bad in (without_slot, {**body, "slot": "0"}, {**body, "slot": True}, {**body, "slot": 1.5},
                    {**body, "slot": None}, {**body, "slot_map": [1]}, [1, 2]):
            assert _request(port, "/project_materials/inventory", bad, token)[0] == 400, bad
    finally:
        httpd.shutdown()


def test_a_slot_with_no_stated_material_has_nothing_to_contradict(env, tmp_path, monkeypatch):
    Provider(monkeypatch, spools=STOCK)
    cfg = _cfg(filament_type=["", "PLA", "PETG"])
    full = service.project_materials_inventory(str(_project(tmp_path, cfg)), 0, provider="spoolman", provider_url=URL)
    assert all(e["warnings"] == [] and e["family_match"] for e in full["entries"])


# --- the review states a deliberate other-material choice ------------------------------------------------------

def _convert(tmp_path, selections, project=None, out="o", mode="preserve"):
    src = project or _project(tmp_path)
    return service.convert(str(src), str(tmp_path / out), mode, False, {"selections": selections})


def test_choosing_another_material_is_recorded_in_the_review(env, tmp_path):
    sel = {"slot": 0, "preset": None, "colour": "#00FF00",
           "spool": {"provider": "spoolman", "id": 3, "vendor": "Yoopai", "material": "PETG", "subtype": None,
                     "colour": "#00FF00"}}
    rec = _convert(tmp_path, [sel])["settings_summary"]["project_materials"]["fidelity"]["slots"][0]
    assert "spool_material_differs" in [d["code"] for d in rec["discrepancies"]]


def test_a_spool_with_no_recorded_material_is_noted_when_the_model_names_one(env, tmp_path):
    sel = {"slot": 0, "preset": None, "colour": "#00FF00",
           "spool": {"provider": "spoolman", "id": 9, "vendor": "Yoopai", "material": None, "subtype": None,
                     "colour": "#00FF00"}}
    rec = _convert(tmp_path, [sel])["settings_summary"]["project_materials"]["fidelity"]["slots"][0]
    assert "spool_material_differs" in [d["code"] for d in rec["discrepancies"]]


def test_a_same_material_spool_of_another_colour_adds_no_material_note(env, tmp_path):
    sel = {"slot": 0, "preset": None, "colour": "#0000FF",
           "spool": {"provider": "spoolman", "id": 2, "vendor": "Yoopai", "material": "PLA", "subtype": "Basic",
                     "colour": "#0000FF"}}
    rec = _convert(tmp_path, [sel])["settings_summary"]["project_materials"]["fidelity"]["slots"][0]
    assert "spool_material_differs" not in [d["code"] for d in rec["discrepancies"]]


# --- B. a Bambu-authored project: spool alone vs a confirmed system preset ---------------------------------------

BAMBU = dict(
    filament_ids=["GFA00", "GFA00", "GFG00"],
    filament_vendor=["Bambu Lab", "Bambu Lab", "Bambu Lab"],
    filament_settings_id=["Bambu PLA Basic @BBL H2D", "Bambu PLA Basic @BBL H2D", "Bambu PETG Basic @BBL H2D"],
    different_settings_to_system=["", "", "", "", ""],
)
SPOOL_SEL = {"provider": "spoolease", "id": 7, "vendor": "Yoopai", "material": "PLA", "subtype": "Matte",
             "colour": "#00AA11"}
FIELDS = ("filament_settings_id", "filament_vendor", "filament_type", "filament_colour", "filament_ids",
          "different_settings_to_system")


def _bambu(tmp_path):
    return _project(tmp_path, _cfg(**BAMBU))


def test_case_1_a_spool_without_a_preset_keeps_the_project_preset_and_says_so(env, tmp_path):
    src = _bambu(tmp_path)
    plain = _prepared(type("R", (), {"output_path": _convert(tmp_path, [], src, "plain")["output_path"]}))
    result = _convert(tmp_path, [{"slot": 1, "preset": None, "colour": "#00AA11", "spool": SPOOL_SEL}], src, "case1")
    out = _prepared(type("R", (), {"output_path": result["output_path"]}))
    # the spool changed the colour of its slot and nothing about the preset identity
    assert out["filament_colour"][1] == "#00AA11"
    for key in ("filament_settings_id", "filament_vendor", "filament_type", "filament_ids"):
        assert out[key] == plain[key], key
    assert out["filament_settings_id"][1] == "Bambu PLA Basic @BBL H2D"
    # and the review says it in the exact words, for that slot
    rec = result["settings_summary"]["project_materials"]["fidelity"]["slots"][1]
    assert SENTENCE in rec["line"] and SPOOL_WITHOUT_PRESET == SENTENCE
    assert rec["output"]["preset_written"] is None and rec["output"]["vendor_type_origin"] == "project"


def test_case_1_wording_is_absent_when_no_spool_was_chosen(env, tmp_path):
    src = _bambu(tmp_path)
    result = _convert(tmp_path, [{"slot": 1, "preset": None, "colour": "#00AA11"}], src, "nospool")
    rec = result["settings_summary"]["project_materials"]["fidelity"]["slots"][1]
    assert SENTENCE not in rec["line"]


def test_case_2_a_confirmed_system_preset_replaces_the_bambu_preset_for_that_slot(env, tmp_path):
    src = _bambu(tmp_path)
    plain = _prepared(type("R", (), {"output_path": _convert(tmp_path, [], src, "plain")["output_path"]}))
    result = _convert(tmp_path, [{"slot": 1, "preset": MATTE, "colour": "#00AA11", "spool": SPOOL_SEL}], src, "case2")
    out = _prepared(type("R", (), {"output_path": result["output_path"]}))
    # the exact installed preset identity, not a Bambu one
    assert out["filament_settings_id"][1] == "Snapmaker PLA Matte @U1" == MATTE
    assert "Bambu" not in out["filament_settings_id"][1] and "BBL" not in out["filament_settings_id"][1]
    # slots the person did not choose keep what the project had
    assert out["filament_settings_id"][0] == plain["filament_settings_id"][0]
    assert out["filament_settings_id"][2] == plain["filament_settings_id"][2]
    # Studio itself declares nothing for the confirmed slot, so Orca takes the preset's own values
    assert out["different_settings_to_system"][2] == "" and "filament_settings_id" not in out["different_settings_to_system"][2]
    rec = result["settings_summary"]["project_materials"]["fidelity"]["slots"][1]
    assert rec["output"]["preset_written"] == MATTE and SENTENCE not in rec["line"]
    assert rec["output"]["vendor_type_origin"] == "preset"


def test_case_2_for_slot_zero_the_default_filament_follows_the_preset(env, tmp_path):
    src = _bambu(tmp_path)
    out = _prepared(type("R", (), {"output_path": _convert(tmp_path, [{"slot": 0, "preset": MATTE}], src, "z")["output_path"]}))
    assert out["filament_settings_id"][0] == MATTE and out["default_filament_profile"] == [MATTE]


def test_case_2_a_declared_vendor_in_the_source_is_reported_not_silently_kept(env, tmp_path):
    """Orca keeps a value the project declares over the preset's. Studio never strips a declaration the creator
    made, so a Bambu vendor the source DECLARES can survive; the review has to say so for that slot."""
    cfg = _cfg(**{**BAMBU, "different_settings_to_system": ["", "", "filament_vendor", "", ""]})
    result = _convert(tmp_path, [{"slot": 1, "preset": MATTE, "colour": "#00AA11", "spool": SPOOL_SEL}],
                      _project(tmp_path, cfg), "decl")
    out = _prepared(type("R", (), {"output_path": result["output_path"]}))
    assert out["filament_settings_id"][1] == MATTE                      # the identity is still the preset
    rec = result["settings_summary"]["project_materials"]["fidelity"]["slots"][1]
    assert "filament_vendor" in rec["declarations"]["retained"]
    (note,) = [d for d in rec["discrepancies"] if d["code"] == "declared_identity_kept"]
    assert "Bambu Lab" in note["text"] and "Snapmaker" in note["text"]
    # and a project that declares nothing about the vendor gets no such note
    clean = _convert(tmp_path, [{"slot": 1, "preset": MATTE}], _bambu(tmp_path), "clean")
    assert "declared_identity_kept" not in [
        d["code"] for d in clean["settings_summary"]["project_materials"]["fidelity"]["slots"][1]["discrepancies"]]


def test_the_two_cases_never_share_a_review_line(env, tmp_path):
    src = _bambu(tmp_path)
    result = _convert(tmp_path, [
        {"slot": 0, "preset": MATTE, "colour": "#102030", "spool": {**SPOOL_SEL, "id": 8}},
        {"slot": 1, "preset": None, "colour": "#00AA11", "spool": SPOOL_SEL}], src, "both")
    lines = [s["line"] for s in result["settings_summary"]["project_materials"]["fidelity"]["slots"]]
    assert SENTENCE not in lines[0] and SENTENCE in lines[1]
