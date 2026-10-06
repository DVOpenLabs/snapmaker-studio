"""Project Materials engine: slots, candidates, ranking, mapping resolution, the same-preset
guard, and Prepare. Nothing is auto-selected, nothing is written to a provider."""
from __future__ import annotations

import datetime
import json
import zipfile
from pathlib import Path

import pytest

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import material_mapping as mm
from snapstudio_core import material_providers as providers
from snapstudio_core import preset_catalog
from snapstudio_core import project_materials as pm
from snapstudio_core.config_io import load_project_settings
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.preset_catalog import NEEDS_CONFIRMATION, NO_MATCH, PROVEN
from tests.test_api import _request, _run

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
MATTE = "Snapmaker PLA Matte @U1"
SNAPSPEED = "Snapmaker PLA SnapSpeed @U1"
PRINT_KEYS = ("nozzle_temperature", "nozzle_temperature_initial_layer", "filament_flow_ratio",
              "filament_max_volumetric_speed", "pressure_advance", "enable_pressure_advance",
              "fan_min_speed", "fan_max_speed", "hot_plate_temp", "textured_plate_temp")


# --- fixtures -----------------------------------------------------------------

def _preset(folder: Path, name: str, nozzle="0.4", vendor="Snapmaker", ftype="PLA"):
    (folder / f"{name}.json").write_text(json.dumps({
        "type": "filament", "instantiation": "true", "name": name,
        "compatible_printers": [f"Snapmaker U1 ({nozzle} nozzle)"],
        "filament_vendor": [vendor], "filament_type": [ftype]}), "utf-8")


@pytest.fixture
def profiles(tmp_path):
    root = tmp_path / "orca" / "Snapmaker"
    fil = root / "filament"
    fil.mkdir(parents=True)
    _preset(fil, MATTE)
    _preset(fil, SNAPSPEED)
    _preset(fil, "Generic PETG @U1 0.4 nozzle", vendor="Generic", ftype="PETG")
    return root


@pytest.fixture
def catalog(profiles):
    return preset_catalog.load(profiles)


@pytest.fixture
def store(tmp_path):
    return mm.Store(str(tmp_path / "maps" / mm.FILE_NAME))


def _cfg(**over):
    cfg = {
        "version": "02.05.00.66", "printer_model": "Bambu Lab H2D",
        "printer_settings_id": "Bambu Lab H2D 0.4 nozzle",
        "print_settings_id": "0.20mm Standard @BBL H2D",
        "default_print_profile": "0.20mm Standard @BBL H2D",
        "default_filament_profile": ["Bambu PLA Basic @BBL H2D"],
        "filament_settings_id": ["Generic PLA @BBL H2D", "Generic PLA @BBL H2D", "Generic PETG @BBL H2D"],
        "filament_vendor": ["Bambu Lab", "Bambu Lab", "Bambu Lab"],
        "filament_colour": ["#FF0000", "#00FF00", "#0000FF"],
        "filament_type": ["PLA", "PLA", "PETG"],
        "nozzle_temperature": ["220", "215", "250"],
        "filament_flow_ratio": ["0.98", "1", "0.95"],
        "enable_pressure_advance": ["0", "0", "0"],
        "different_settings_to_system": ["", "", "", "", ""],
        "ensure_vertical_shell_thickness": "enabled",
    }
    cfg.update(over)
    return cfg


SLICE_INFO = ('<?xml version="1.0"?>\n<config><header>'
              '<header_item key="X-BBL-Client-Version" value="02.05.00.66"/></header>'
              '<plate><metadata key="prediction" value="100"/>'
              '<filament id="1" type="PLA" color="#FF0000" used_m="5" used_g="180"/>'
              '<filament id="3" type="PETG" color="#0000FF" used_m="2" used_g="40.5"/></plate>'
              '</config>')


def _project(tmp_path: Path, cfg=None, name="proj.3mf", slice_info=SLICE_INFO) -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model/>')
        z.writestr("Metadata/project_settings.config", json.dumps(cfg or _cfg()))
        if slice_info:
            z.writestr("Metadata/slice_info.config", slice_info)
    return p


def _prepared(result) -> dict:
    return load_project_settings(zipfile.ZipFile(result.output_path).read("Metadata/project_settings.config"))


def spool(sid, vendor="Yoopai", material="PLA", subtype="Matte", color="#FF0000", remaining=412.0,
          quality="tracked", **kw):
    return {"id": str(sid), "vendor": vendor, "material": material, "subtype": subtype, "color": color,
            "remaining_g": remaining, "remaining_quality": quality, "remaining_as_of": NOW,
            "archived": False, "name": None, **kw}


def slot(**kw):
    base = {"slot": 0, "family": "PLA", "subtype": None, "colour": "#FF0000", "required_g": 180.0,
            "settings_id": None, "declared_keys": []}
    base.update(kw)
    return base


def _save(store, catalog, sid, preset=MATTE, provider="spoolman"):
    store.put(scope=mm.SCOPE_SPOOL, provider=provider, spool_id=sid, origin=mm.SOURCE_MANUAL,
              preset=catalog.evaluate(preset, "0.4"), catalog=catalog)


def _rank(slot_, spools, catalog, store, state=None):
    return pm.recommend(slot_, "spoolman", spools, state, catalog, store, "0.4")


def _ids(rec):
    return [c["spool_id"] for c in rec["candidates"]]


# --- 1. source extraction -----------------------------------------------------

def test_extracts_each_slot_from_what_the_project_states():
    cfg = _cfg(different_settings_to_system=["brim_type", "filament_vendor;nozzle_temperature", "", "filament_type", ""])
    slots = pm.extract_slots(cfg, plates=[{"filaments": [{"id": "1", "used_g": 100.0}, {"id": "1", "used_g": 80.0},
                                                         {"id": "3", "used_g": 40.5}]}])
    assert [s["slot"] for s in slots] == [0, 1, 2]
    s0, s1, s2 = slots
    assert (s0["family"], s0["subtype"], s0["colour"]) == ("PLA", None, "#FF0000")
    assert s0["settings_id"] == "Generic PLA @BBL H2D" and s0["vendor"] == "Bambu Lab"
    assert s0["required_g"] == 180.0 and s0["required_source"] == "the source file's own slice"
    assert s1["required_g"] is None and s1["required_source"] is None        # not invented
    assert s2["required_g"] == 40.5
    assert s0["declared_keys"] == ["filament_vendor", "nozzle_temperature"]
    assert s0["declared_identity"] == ["filament_vendor"]
    assert s1["declared_keys"] == [] and s2["declared_identity"] == ["filament_type"]


def test_missing_values_stay_missing():
    cfg = {"filament_colour": ["#FFFFFF"], "filament_type": [], "filament_settings_id": []}
    (s,) = pm.extract_slots(cfg)
    assert s["family"] is None and s["subtype"] is None and s["settings_id"] is None
    assert s["vendor"] is None and s["required_g"] is None and s["declared_keys"] == []


def test_a_subtype_is_only_taken_from_what_the_type_says():
    cfg = _cfg(filament_type=["PLA Matte", "PLA", "TPU 95A"])
    assert [s["subtype"] for s in pm.extract_slots(cfg)] == ["Matte", None, "95A"]


def test_colour_with_alpha_reads_as_six_digits():
    assert pm.hex6("#12345678") == "#123456" and pm.hex6("abcdef") == "#ABCDEF"
    assert pm.hex6("nope") is None and pm.hex6(None) is None


def test_project_settings_are_read_from_a_3mf(tmp_path):
    from snapstudio_core.container import ThreeMF
    cfg, plates = pm.read_project(ThreeMF.open(_project(tmp_path)))
    assert cfg["filament_type"] == ["PLA", "PLA", "PETG"]
    assert pm.required_grams(plates) == {0: 180.0, 2: 40.5}
    no_settings = tmp_path / "geo.3mf"
    with zipfile.ZipFile(no_settings, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
    assert pm.read_project(ThreeMF.open(no_settings)) == (None, [])


# --- 2/3. candidates and the recommender -----------------------------------------

def test_a_candidate_carries_every_field_and_its_reasons(catalog, store):
    _save(store, catalog, "1")
    state = {"available": True, "slots": [providers._slot(2, material="PLA", spool_id="1", source="spoolman")]}
    rec = _rank(slot(), [spool(1, slicer_filament="Generic PLA")], catalog, store, state)
    (c,) = rec["candidates"]
    assert {"provider", "spool_id", "vendor", "material", "subtype", "colour", "remaining_g",
            "remaining_quality", "loaded_slot", "slicer_filament", "mapping", "reasons"} <= set(c)
    assert (c["provider"], c["spool_id"], c["vendor"], c["colour"]) == ("spoolman", "1", "Yoopai", "#FF0000")
    assert c["slicer_filament"] == "Generic PLA" and c["loaded_slot"] == 2
    assert c["mapping"]["status"] == PROVEN and c["mapping"]["match_source"] == mm.SOURCE_SAVED_SPOOL
    codes = [r["code"] for r in c["reasons"]]
    assert codes == ["material_exact", "subtype_unspecified", "preset_proven", "weight_enough",
                     "colour_distance", "loaded"]
    weight = next(r for r in c["reasons"] if r["code"] == "weight_enough")
    assert weight["text"] == "Enough filament: 412 g available / 180 g needed"
    assert next(r for r in c["reasons"] if r["code"] == "colour_distance")["data"] == {"distance": 0}
    assert rec["selected"] is None            # nothing is chosen for the person
    assert not any(k.startswith("_") for k in c)


def test_only_the_same_family_and_unarchived_spools_are_candidates(catalog, store):
    rec = _rank(slot(), [spool(1), spool(2, material="PETG"), spool(3, archived=True), spool(4, material=None)],
                catalog, store)
    assert _ids(rec) == ["1"] and rec["candidate_count"] == 1


def test_reason_for_every_weight_situation(catalog, store):
    cases = [
        (slot(required_g=None), spool(1, remaining=None), "amount_unknown"),
        (slot(required_g=None), spool(1, remaining=300.0), "amount_needed_unknown"),
        (slot(required_g=180.0), spool(1, remaining=None), "amount_unknown"),
        (slot(required_g=180.0), spool(1, remaining=20.0), "weight_short"),
        (slot(required_g=180.0), spool(1, remaining=412.0, quality="unknown"), "weight_enough_untrusted"),
        (slot(required_g=180.0), spool(1, remaining=412.0), "weight_enough"),
    ]
    for slot_, spool_, code in cases:
        (c,) = _rank(slot_, [spool_], catalog, store)["candidates"]
        assert code in [r["code"] for r in c["reasons"]], (code, c["reasons"])


def test_subtype_outranks_a_proven_preset(catalog, store):
    _save(store, catalog, "2")
    rec = _rank(slot(subtype="Matte"), [spool(1, subtype="Matte"), spool(2, subtype="Silk")], catalog, store)
    assert _ids(rec) == ["1", "2"]
    assert [r["code"] for r in rec["candidates"][1]["reasons"] if r["code"].startswith("subtype")] == ["subtype_differs"]


def test_a_proven_preset_outranks_a_nearer_colour(catalog, store):
    _save(store, catalog, "2")
    rec = _rank(slot(colour="#FF0000"), [spool(1, color="#FF0000"), spool(2, color="#F00020")], catalog, store)
    assert _ids(rec) == ["2", "1"]


def test_preset_that_needs_confirmation_ranks_between_proven_and_none(catalog, store):
    _save(store, catalog, "3")
    rec = _rank(slot(), [spool(1), spool(2, slicer_filament=MATTE), spool(3)], catalog, store)
    assert _ids(rec) == ["3", "2", "1"]
    assert rec["candidates"][1]["mapping"]["status"] == NEEDS_CONFIRMATION
    assert rec["candidates"][1]["mapping"]["match_source"] == mm.SOURCE_EXACT_NAME


def test_trusted_enough_weight_outranks_colour_and_loading(catalog, store):
    state = {"available": True, "slots": [providers._slot(0, material="PLA", spool_id="1", source="spoolman")]}
    rec = _rank(slot(), [spool(1, remaining=20.0), spool(2, color="#F00020")], catalog, store, state)
    assert _ids(rec) == ["2", "1"]


def test_nearer_colour_outranks_being_loaded(catalog, store):
    state = {"available": True, "slots": [providers._slot(0, material="PLA", spool_id="1", source="spoolman")]}
    rec = _rank(slot(), [spool(1, color="#C00000"), spool(2, color="#FA0000")], catalog, store, state)
    assert _ids(rec) == ["2", "1"]


def test_loaded_breaks_an_otherwise_equal_tie(catalog, store):
    state = {"available": True, "slots": [providers._slot(1, material="PLA", spool_id="2", source="spoolman")]}
    rec = _rank(slot(), [spool(1), spool(2)], catalog, store, state)
    assert _ids(rec) == ["2", "1"]
    assert rec["candidates"][0]["loaded_slot"] == 1 and rec["candidates"][1]["loaded_slot"] is None


def test_final_tie_break_is_vendor_then_name_then_id_and_stable(catalog, store):
    spools = [spool(10, vendor="Zed"), spool(9, vendor="Acme"), spool(2, vendor="Acme", subtype="Matte"),
              spool(100, vendor="Acme")]
    first = _ids(_rank(slot(), spools, catalog, store))
    assert first == ["2", "9", "100", "10"]
    assert _ids(_rank(slot(), list(reversed(spools)), catalog, store)) == first


def test_close_call_flags_materially_similar_leaders(catalog, store):
    close = _rank(slot(colour="#FF0000"), [spool(1, color="#FF0000"), spool(2, color="#FA0000")], catalog, store)
    assert close["close_call"] is True
    far = _rank(slot(colour="#FF0000"), [spool(1, color="#FF0000"), spool(2, color="#800000")], catalog, store)
    assert far["close_call"] is False
    different_tier = _rank(slot(), [spool(1), spool(2)], catalog, store)
    _save(store, catalog, "1")
    assert _rank(slot(), [spool(1), spool(2)], catalog, store)["close_call"] is False
    assert different_tier["close_call"] is True
    assert _rank(slot(), [spool(1)], catalog, store)["close_call"] is False


def test_limit_trims_the_list_but_not_the_count(catalog, store):
    rec = pm.recommend(slot(), "spoolman", [spool(i) for i in range(1, 9)], None, catalog, store, "0.4", limit=3)
    assert len(rec["candidates"]) == 3 and rec["candidate_count"] == 8
    assert [c["rank"] for c in rec["candidates"]] == [1, 2, 3]


# --- 4. mapping resolution inside candidates ------------------------------------

def test_stale_mapping_is_needs_confirmation_and_not_applied(catalog, store, profiles):
    _save(store, catalog, "1")
    doc = profiles / "filament" / f"{MATTE}.json"
    data = json.loads(doc.read_text("utf-8"))
    data["filament_type"] = ["PETG"]
    doc.write_text(json.dumps(data), "utf-8")
    stale = preset_catalog.load(profiles)
    (c,) = _rank(slot(), [spool(1)], stale, store)["candidates"]
    assert c["mapping"]["status"] == NEEDS_CONFIRMATION and c["mapping"]["stale"] is True
    assert next(r for r in c["reasons"] if r["code"].startswith("preset"))["code"] == "preset_needs_confirmation"


def test_an_ambiguous_name_needs_confirmation(tmp_path):
    root = tmp_path / "amb" / "Snapmaker"
    fil = root / "filament"
    fil.mkdir(parents=True)
    _preset(fil, "Acme PLA @U1")
    doc = json.loads((fil / "Acme PLA @U1.json").read_text("utf-8"))
    doc["name"] = "ACME PLA @U1"
    (fil / "other.json").write_text(json.dumps(doc), "utf-8")
    cat = preset_catalog.load(root)
    (c,) = pm.recommend(slot(), "spoolease", [spool(1, slicer_filament="Acme PLA @U1")], None, cat,
                        mm.Store(str(tmp_path / "m.json")), "0.4")["candidates"]
    assert c["mapping"]["status"] == NEEDS_CONFIRMATION and c["mapping"]["preset_name"] is None
    assert len(c["mapping"]["candidates"]) == 2


def test_slicer_filament_alone_never_proves_a_preset(catalog, store):
    (c,) = _rank(slot(), [spool(1, slicer_filament=MATTE)], catalog, store)["candidates"]
    assert c["mapping"]["status"] == NEEDS_CONFIRMATION
    (c,) = _rank(slot(), [spool(1, slicer_filament="Yoopai PLA+")], catalog, store)["candidates"]
    assert c["mapping"]["status"] == NO_MATCH


def test_without_a_catalogue_nothing_is_proven(store):
    (c,) = pm.recommend(slot(), "spoolman", [spool(1, slicer_filament=MATTE)], None, None, store, "0.4")["candidates"]
    assert c["mapping"]["status"] == NO_MATCH and c["mapping"]["catalog_missing"] is True


# --- 5. same-preset guard -------------------------------------------------------

def _guard(cfg, catalog, confirmed=None):
    return pm.guard(cfg, pm.extract_slots(cfg), confirmed, catalog, "0.4")


def _shared(**over):
    base = dict(filament_settings_id=[MATTE, MATTE, "Generic PETG @U1"],
                filament_vendor=["Yoopai", "Snapmaker", "Generic"],
                different_settings_to_system=["", "filament_vendor", "", "", ""])
    base.update(over)
    return _cfg(**base)


def test_a_declared_vendor_on_a_shared_preset_with_different_vendors_blocks(catalog):
    g = _guard(_shared(), catalog, confirmed={2: "Generic PETG @U1"})
    assert g["blocking"] is True and g["applies"] is True
    (c,) = g["conflicts"]
    assert (c["key"], c["preset"], c["slots"], c["declared_in"]) == ("filament_vendor", MATTE, [0, 1], [0])
    assert c["values"] == {0: "Yoopai", 1: "Snapmaker"}
    assert g["shared"] == [{"preset": MATTE, "slots": [0, 1]}]
    assert "different installed preset" in g["resolution"] and "does not edit" in g["resolution"]
    assert "slots 1, 2 share" in pm.guard_message(g)


def test_without_project_materials_the_conflict_is_reported_but_never_blocks(catalog):
    g = _guard(_shared(), catalog, confirmed=None)
    assert g["conflicts"] and g["blocking"] is False and g["applies"] is False


def test_type_conflicts_block_too(catalog):
    cfg = _shared(filament_type=["PLA", "PETG", "PETG"], different_settings_to_system=["", "", "filament_type", "", ""])
    g = _guard(cfg, catalog, confirmed={2: "Generic PETG @U1"})
    assert [c["key"] for c in g["conflicts"]] == ["filament_type"] and g["blocking"] is True


def test_no_conflict_when_values_agree_or_nothing_is_declared_or_presets_differ(catalog):
    assert not _guard(_shared(filament_vendor=["Yoopai", "Yoopai", "G"]), catalog, {2: "Generic PETG @U1"})["conflicts"]
    assert not _guard(_shared(different_settings_to_system=["", "", "", "", ""]), catalog,
                      {2: "Generic PETG @U1"})["conflicts"]
    distinct = _shared(filament_settings_id=[MATTE, SNAPSPEED, "Generic PETG @U1"])
    g = _guard(distinct, catalog, {2: "Generic PETG @U1"})
    assert not g["conflicts"] and g["shared"] == [] and g["blocking"] is False


def test_the_users_own_preset_choice_can_create_the_conflict(catalog):
    cfg = _shared(filament_settings_id=["Generic PLA @BBL H2D", SNAPSPEED, "Generic PETG @U1"])
    assert not _guard(cfg, catalog, {2: "Generic PETG @U1"})["conflicts"]
    g = _guard(cfg, catalog, {0: SNAPSPEED})
    assert g["blocking"] is True and g["conflicts"][0]["slots"] == [0, 1]


def test_declared_print_values_on_a_shared_preset_are_a_warning_not_a_block(catalog):
    cfg = _shared(different_settings_to_system=["", "nozzle_temperature", "", "", ""], filament_vendor=["A", "A", "A"])
    g = _guard(cfg, catalog, {2: "Generic PETG @U1"})
    assert g["blocking"] is False and not g["conflicts"]
    assert g["warnings"][0]["keys"] == ["nozzle_temperature"] and g["warnings"][0]["declared_in"] == [0]


def test_guard_never_edits_the_source_declarations(catalog):
    cfg = _shared()
    before = json.dumps(cfg, sort_keys=True)
    _guard(cfg, catalog, {2: "Generic PETG @U1"})
    assert json.dumps(cfg, sort_keys=True) == before


# --- 6. Prepare integration --------------------------------------------------------

def _confirmed(catalog, selections):
    return pm.prepare_inputs(selections, _cfg(), catalog, "0.4")


def test_prepare_inputs_only_accepts_proven_installed_presets(catalog):
    presets, colours = _confirmed(catalog, [{"slot": 1, "preset": MATTE, "colour": "#00ff00"}, {"slot": 0}])
    assert presets == {1: MATTE} and colours == {1: "#00FF00"}
    assert _confirmed(catalog, None) == ({}, {})
    for bad, text in [
        ([{"slot": 9, "preset": MATTE}], "slot 9"),
        ([{"slot": 1, "preset": MATTE}, {"slot": 1, "colour": "#112233"}], "twice"),
        ([{"slot": 1, "preset": "Snapmaker PLA"}], "not a proven installed preset"),
        ([{"slot": 1, "preset": "snapmaker pla matte @u1"}], "not a proven installed preset"),
        ([{"slot": 1, "colour": "red"}], "not a hex colour"),
        ([{"slot": True, "preset": MATTE}], "slot True"),
        (["x"], "must be an object"),
    ]:
        with pytest.raises(ValueError, match=text):
            _confirmed(catalog, bad)
    with pytest.raises(ValueError, match="could not be read"):
        pm.prepare_inputs([{"slot": 1, "preset": MATTE}], _cfg(), None, "0.4")


def test_no_project_materials_input_changes_nothing(tmp_path):
    src = _project(tmp_path)
    plain = convert_to_u1(str(src), out_dir=str(tmp_path / "a"))
    empty = convert_to_u1(str(src), out_dir=str(tmp_path / "b"), confirmed_presets=None, confirmed_colours=None)
    assert _prepared(plain) == _prepared(empty)
    assert "project_materials" not in plain.settings_summary


def test_a_confirmed_preset_and_colour_are_written_and_nothing_else(tmp_path, catalog):
    src = _project(tmp_path)
    plain = _prepared(convert_to_u1(str(src), out_dir=str(tmp_path / "a")))
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "b"), confirmed_presets={1: MATTE},
                        filament_catalog=catalog, confirmed_colours={1: "#00AA11"})
    out = _prepared(res)
    assert out["filament_settings_id"][1] == MATTE                      # the REAL installed name
    assert out["filament_settings_id"][0] == plain["filament_settings_id"][0]   # other slots keep theirs
    assert out["filament_colour"][1] == "#00AA11" and out["filament_colour"][0] == plain["filament_colour"][0]
    differing = {k for k in set(plain) | set(out) if plain.get(k) != out.get(k)}
    assert differing == {"filament_settings_id", "filament_colour", "different_settings_to_system"}, differing
    # print-critical values are the project's own, never synthesized by Project Materials
    for key in PRINT_KEYS:
        assert out.get(key) == plain.get(key), key
    # and none is declared for the confirmed slot, so Orca takes them from the preset; the
    # slots Project Materials did not touch keep exactly what a plain Prepare declares
    plain_decl, out_decl = plain["different_settings_to_system"], out["different_settings_to_system"]
    assert plain_decl[2] == "nozzle_temperature" and out_decl[2] == ""
    assert [e for i, e in enumerate(out_decl) if i != 2] == [e for i, e in enumerate(plain_decl) if i != 2]
    pmat = res.settings_summary["project_materials"]
    assert pmat["applied"] == [{"slot": 1, "old": "Generic PLA @BBL H2D", "new": MATTE}]
    assert pmat["colours"] == [{"slot": 1, "old": "#00FF00", "new": "#00AA11"}]
    assert pmat["guard"]["blocking"] is False and res.validated_ok is True


def test_provider_ids_and_weights_never_reach_the_project(tmp_path, catalog):
    src = _project(tmp_path)
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "b"), confirmed_presets={0: MATTE, 1: SNAPSPEED},
                        filament_catalog=catalog, confirmed_colours={0: "#123456", 1: "#654321"})
    z = zipfile.ZipFile(res.output_path)
    blob = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.startswith("Metadata/")).lower()
    for word in ("spoolman", "spoolease", "remaining", "spool_id", "yoopai", "412"):
        assert word not in blob, word


def test_the_default_filament_profile_follows_a_confirmed_slot_zero(tmp_path, catalog):
    out = _prepared(convert_to_u1(str(_project(tmp_path)), out_dir=str(tmp_path / "b"),
                                  confirmed_presets={0: MATTE}, filament_catalog=catalog))
    assert out["default_filament_profile"] == [MATTE]


def test_colour_keeps_the_projects_own_alpha_notation(tmp_path, catalog):
    cfg = _cfg(filament_colour=["#FF0000AA", "#00FF00", "#0000FF"])
    out = _prepared(convert_to_u1(str(_project(tmp_path, cfg)), out_dir=str(tmp_path / "b"),
                                  confirmed_colours={0: "#102030"}))
    assert out["filament_colour"][0] == "#102030AA"


def test_a_spool_colour_alone_keeps_the_project_filament_identity(tmp_path, catalog):
    src = _project(tmp_path)
    plain = _prepared(convert_to_u1(str(src), out_dir=str(tmp_path / "a")))
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "b"), confirmed_colours={2: "#ABCDEF"},
                        filament_catalog=catalog)
    out = _prepared(res)
    assert out["filament_settings_id"] == plain["filament_settings_id"] and out["filament_colour"][2] == "#ABCDEF"
    assert res.settings_summary["project_materials"]["applied"] == []
    notice = "Studio keeps the project's existing filament identity."
    assert any(notice in w for w in res.settings_summary["warnings"])


def test_a_blocking_guard_stops_prepare_and_writes_nothing(tmp_path, catalog):
    src = _project(tmp_path, _shared())
    out_dir = tmp_path / "blocked"
    res = convert_to_u1(str(src), out_dir=str(out_dir), confirmed_presets={2: "Generic PETG @U1"},
                        filament_catalog=catalog)
    assert res.blocked is True and res.validated_ok is False and res.output_path == ""
    assert "Prepare stopped" in res.errors[0] and "do not edit" not in res.errors[0]
    assert res.settings_summary["project_materials"]["guard"]["conflicts"]
    assert not list(out_dir.glob("*.3mf")) and not src.with_suffix(".orig.3mf").exists()
    # the same source without any Project Materials choice prepares exactly as before
    ok = convert_to_u1(str(src), out_dir=str(tmp_path / "ok"))
    assert ok.blocked is False and ok.output_path


def test_recommended_with_a_catalogue_suggests_but_never_applies(tmp_path, catalog):
    src = _project(tmp_path)
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "r"), prepare_mode="recommended",
                        filament_catalog=catalog)
    out = _prepared(res)
    assert "Snapmaker PLA" not in out["filament_settings_id"]
    assert out["filament_settings_id"] == ["Generic PLA @BBL H2D", "Generic PLA @BBL H2D", "Generic PETG @BBL H2D"]
    (sug,) = res.settings_summary["project_materials"]["suggestions"]
    assert sug["slot"] == 2 and sug["preset_name"] == "Generic PETG @U1 0.4 nozzle"
    assert sug["status"] == NEEDS_CONFIRMATION
    confirmed = convert_to_u1(str(src), out_dir=str(tmp_path / "r2"), prepare_mode="recommended",
                              confirmed_presets={2: "Generic PETG @U1 0.4 nozzle"}, filament_catalog=catalog)
    assert _prepared(confirmed)["filament_settings_id"][2] == "Generic PETG @U1 0.4 nozzle"


# --- 7. service and HTTP API ----------------------------------------------------

class Provider:
    """Counts reads. A provider read is the only thing the analysis may do to a provider."""

    def __init__(self, monkeypatch, spools=None, slots=None):
        self.reads = []
        self.spools = spools if spools is not None else [
            spool(1, slicer_filament=MATTE), spool(2, color="#F00020"), spool(3, material="PETG", subtype=None)]
        self.slots = slots or []
        monkeypatch.setattr(providers, "read", self._read)

    def _read(self, kind, url, slot_map=None, timeout=4.0, slot_base=None, key=None):
        self.reads.append((kind, url))
        return {"available": True, "source": kind, "spools": self.spools, "slots": self.slots,
                "error": None, "error_code": None}


@pytest.fixture
def env(monkeypatch, tmp_path, profiles):
    monkeypatch.setenv("SNAPSTUDIO_ORCA_PROFILES_DIR", str(profiles))
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_analysis_is_read_only_and_selects_nothing(monkeypatch, env, tmp_path):
    fake = Provider(monkeypatch, slots=[providers._slot(3, material="PLA", spool_id="2", source="spoolman")])
    out = service.project_materials(str(_project(tmp_path)), provider="spoolman", provider_url="http://192.168.1.50:7912")
    assert len(fake.reads) == 1 and out["supported"] is True and out["nozzle"] == "0.4"
    assert out["catalog"]["available"] is True and out["provider"] == {"kind": "spoolman", "available": True, "error_code": None}
    s0, s1, s2 = out["slots"]
    assert all(s["selected"] is None for s in out["slots"])
    # the preset a provider names (needs confirmation) outranks colour and being loaded
    assert [c["spool_id"] for c in s0["candidates"]] == ["1", "2"]
    assert s0["candidates"][1]["loaded_slot"] == 3
    assert s0["required_g"] == 180.0 and s1["required_g"] is None and s2["required_g"] == 40.5
    assert [c["spool_id"] for c in s2["candidates"]] == ["3"]
    assert s2["suggestion"]["preset_name"] == "Generic PETG @U1 0.4 nozzle" and s0["suggestion"] is None
    assert s0["current_preset"]["status"] == NO_MATCH
    assert not (tmp_path / "data" / mm.FILE_NAME).exists()               # nothing saved as truth


def test_analysis_without_a_provider_still_lists_slots_and_suggestions(env, tmp_path):
    out = service.project_materials(str(_project(tmp_path)))
    assert out["provider"] is None and all(s["candidates"] == [] for s in out["slots"])
    assert out["slots"][2]["suggestion"]["status"] == NEEDS_CONFIRMATION


def test_analysis_of_an_unreadable_provider_is_an_answer_not_a_crash(monkeypatch, env, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(providers, "read", boom)
    out = service.project_materials(str(_project(tmp_path)), provider="spoolman", provider_url="http://192.168.1.50:7912")
    assert out["provider"]["available"] is False and out["provider"]["error_code"] == "unreachable"
    assert all(s["candidates"] == [] for s in out["slots"])


def test_stl_and_settingless_files_are_unsupported_not_errors(env, tmp_path):
    assert service.project_materials(str(tmp_path / "x.stl"))["supported"] is False
    geo = tmp_path / "geo.3mf"
    with zipfile.ZipFile(geo, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
    assert service.project_materials(str(geo))["supported"] is False


def test_preset_list_for_a_picker(env):
    out = service.material_presets("0.4")
    assert out["available"] is True
    assert [p["base_name"] for p in out["presets"]] == ["Generic PETG @U1", MATTE, SNAPSPEED]
    assert out["presets"][0]["preset_name"] == "Generic PETG @U1 0.4 nozzle"
    assert service.material_presets("0.2")["presets"] == []
    with pytest.raises(ValueError):
        service.material_presets("0.5")


def test_confirming_a_mapping_makes_the_next_analysis_proven_and_reset_removes_it(monkeypatch, env, tmp_path):
    Provider(monkeypatch)
    url = "http://192.168.1.50:7912"
    saved = service.material_mapping_confirm({"scope": "spool", "provider": "spoolman", "spool_id": 1, "preset": MATTE})
    assert saved["mapping"]["preset_base"] == MATTE and saved["mapping"]["origin"] == "manual"
    out = service.project_materials(str(_project(tmp_path)), provider="spoolman", provider_url=url)
    top = out["slots"][0]["candidates"][0]
    assert top["spool_id"] == "1" and top["mapping"]["status"] == PROVEN
    assert top["mapping"]["match_source"] == mm.SOURCE_SAVED_SPOOL
    sig = service.material_mapping_confirm({"scope": "signature", "provider": "spoolman", "vendor": "Yoopai",
                                            "material": "PLA", "subtype": "Matte", "preset": SNAPSPEED})
    assert sig["mapping"]["signature"] == {"vendor": "yoopai", "family": "pla", "subtype": "matte"}
    assert service.material_mapping_remove({"scope": "spool", "provider": "spoolman", "spool_id": "1"})["removed"] is True
    assert service.material_mapping_remove({"scope": "spool", "provider": "spoolman", "spool_id": "1"})["removed"] is False
    after = service.project_materials(str(_project(tmp_path)), provider="spoolman", provider_url=url)
    mapped = {c["spool_id"]: c["mapping"] for c in after["slots"][0]["candidates"]}
    assert mapped["1"]["match_source"] == mm.SOURCE_SAVED_SIGNATURE and mapped["1"]["base_name"] == SNAPSPEED


def test_only_a_proven_installed_preset_can_be_confirmed(env):
    for preset in ("Snapmaker PLA", "", None, "snapmaker pla matte @u1"):
        with pytest.raises(ValueError):
            service.material_mapping_confirm({"scope": "spool", "provider": "spoolman", "spool_id": 1, "preset": preset})
    with pytest.raises(ValueError):
        service.material_mapping_confirm({"scope": "spool", "provider": "", "spool_id": 1, "preset": MATTE})
    with pytest.raises(ValueError):
        service.material_mapping_confirm({"scope": "spool", "provider": "spoolman", "spool_id": 1,
                                          "preset": MATTE, "nozzle": "0.2"})


def test_service_convert_applies_selections_and_refuses_unproven_ones(env, tmp_path):
    src = _project(tmp_path)
    ok = service.convert(str(src), str(tmp_path / "o1"), "preserve", False,
                         {"selections": [{"slot": 0, "preset": MATTE, "colour": "#ABCDEF"}]})
    out = load_project_settings(zipfile.ZipFile(ok["output_path"]).read("Metadata/project_settings.config"))
    assert out["filament_settings_id"][0] == MATTE and out["filament_colour"][0] == "#ABCDEF"
    with pytest.raises(ValueError, match="not a proven installed preset"):
        service.convert(str(src), str(tmp_path / "o2"), "preserve", False, {"selections": [{"slot": 0, "preset": "Made Up"}]})
    with pytest.raises(ValueError, match="3MF"):
        service.convert(str(tmp_path / "m.stl"), None, "preserve", False, {"selections": []})
    blocked = service.convert(str(_project(tmp_path, _shared(), "shared.3mf")), str(tmp_path / "o3"), "preserve",
                              False, {"selections": [{"slot": 2, "preset": "Generic PETG @U1"}]})
    assert blocked["blocked"] is True and blocked["output_path"] == ""


def test_http_routes(monkeypatch, env, tmp_path):
    Provider(monkeypatch)
    httpd, token = build_server(port=0)
    _run(httpd)
    try:
        port = httpd.server_address[1]
        proj = str(_project(tmp_path))
        assert _request(port, "/project_materials", {"path": proj}, None)[0] == 401
        st, body = _request(port, "/material_presets", {"nozzle": "0.4"}, token)
        assert st == 200 and len(body["presets"]) == 3
        assert _request(port, "/material_presets", {"nozzle": "9"}, token)[0] == 400
        st, body = _request(port, "/project_materials", {"path": proj, "provider": "spoolman",
                                                         "provider_url": "http://192.168.1.50:7912"}, token)
        assert st == 200 and body["slots"][0]["candidates"] and body["slots"][0]["selected"] is None
        st, body = _request(port, "/material_mapping/confirm",
                            {"scope": "spool", "provider": "spoolman", "spool_id": "1", "preset": MATTE}, token)
        assert st == 200 and body["ok"] is True
        assert _request(port, "/material_mapping/confirm",
                        {"scope": "spool", "provider": "spoolman", "spool_id": "1", "preset": "Nope"}, token)[0] == 400
        st, body = _request(port, "/material_mapping/remove",
                            {"scope": "spool", "provider": "spoolman", "spool_id": "1"}, token)
        assert st == 200 and body["removed"] is True
        st, body = _request(port, "/convert", {"path": proj, "out_dir": str(tmp_path / "http"),
                                               "materials": {"selections": [{"slot": 1, "preset": MATTE}]}}, token)
        assert st == 200 and body["settings_summary"]["project_materials"]["applied"][0]["new"] == MATTE
        assert _request(port, "/convert", {"path": proj, "materials": {"selections": [{"slot": 1, "preset": "Nope"}]}},
                        token)[0] == 400
        assert _request(port, "/convert", {"path": proj, "materials": "x"}, token)[0] == 400
        st, body = _request(port, "/convert", {"path": str(_project(tmp_path, _shared(), "s2.3mf")),
                                               "out_dir": str(tmp_path / "http2"),
                                               "materials": {"selections": [{"slot": 2, "preset": "Generic PETG @U1"}]}},
                            token)
        assert st == 200 and body["blocked"] is True
        plain_before = _request(port, "/convert", {"path": proj, "out_dir": str(tmp_path / "plain")}, token)
        assert plain_before[0] == 200 and "project_materials" not in plain_before[1]["settings_summary"]
    finally:
        httpd.shutdown()


def test_a_declaration_the_project_itself_made_is_kept_on_a_confirmed_slot(tmp_path, catalog):
    cfg = _cfg(different_settings_to_system=["", "", "filament_type", "", ""])   # slot 2 declares its type
    src = _project(tmp_path, cfg)
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "o"), confirmed_presets={1: MATTE},
                        filament_catalog=catalog)
    out = _prepared(res)
    entries = out["different_settings_to_system"]
    # entries: [process, slot 1, slot 2, slot 3, printer]. Slot 2 is confirmed and declares its own type.
    assert entries[2] == "filament_type"            # the project's own declaration stays; Studio's is withdrawn
    assert entries[1] == "nozzle_temperature" and entries[3] == "nozzle_temperature"   # untouched slots as before
    # confirming the slot that holds the declaration withdraws only what Studio added
    res2 = convert_to_u1(str(src), out_dir=str(tmp_path / "o2"), confirmed_presets={1: MATTE, 0: SNAPSPEED},
                         filament_catalog=catalog)
    entries2 = _prepared(res2)["different_settings_to_system"]
    assert entries2[1] == "" and entries2[2] == "filament_type" and entries2[3] == "nozzle_temperature"


# --- the guard judges what will be written, not what the source declared -------------------

def _conflicted(tmp_path):
    return _project(tmp_path, _shared())


def test_preserve_blocks_when_the_conflicting_declarations_survive(tmp_path, catalog):
    res = convert_to_u1(str(_conflicted(tmp_path)), out_dir=str(tmp_path / "p"), prepare_mode="preserve",
                        confirmed_presets={2: "Generic PETG @U1"}, filament_catalog=catalog)
    assert res.blocked is True and res.output_path == ""
    g = res.settings_summary["project_materials"]["guard"]
    assert g["mode"] == "preserve" and g["blocking"] is True
    assert [(c["key"], c["slots"]) for c in g["conflicts"]] == [("filament_vendor", [0, 1])]
    assert g["source_conflicts"] == g["conflicts"] and g["removed_by_mode"] == []
    assert "Recommended mode removes the source's declarations" in g["resolution"]
    assert not list((tmp_path / "p").glob("*.3mf"))


def test_recommended_does_not_block_when_it_removes_those_declarations(tmp_path, catalog):
    src = _conflicted(tmp_path)
    before = src.read_bytes()
    res = convert_to_u1(str(src), out_dir=str(tmp_path / "r"), prepare_mode="recommended",
                        confirmed_presets={2: "Generic PETG @U1"}, filament_catalog=catalog)
    assert res.blocked is False and res.output_path
    g = res.settings_summary["project_materials"]["guard"]
    assert g["blocking"] is False and g["conflicts"] == []
    # still reported, as information: what the source held and that the mode took it away
    assert [(c["key"], c["preset"], c["slots"]) for c in g["source_conflicts"]] == [("filament_vendor", MATTE, [0, 1])]
    assert g["removed_by_mode"] == g["source_conflicts"]
    declared = _prepared(res)["different_settings_to_system"]
    assert not any("filament_vendor" in str(entry) for entry in declared)
    assert src.read_bytes() == before                      # the source is never edited


def test_recommended_still_blocks_a_conflict_that_survives_output(tmp_path, catalog, monkeypatch):
    from snapstudio_core import repair
    monkeypatch.setattr(repair, "normalize_presets", lambda cfg, **kw: [])   # a path that keeps declarations
    res = convert_to_u1(str(_conflicted(tmp_path)), out_dir=str(tmp_path / "r"), prepare_mode="recommended",
                        confirmed_presets={2: "Generic PETG @U1"}, filament_catalog=catalog)
    assert res.blocked is True and res.output_path == ""
    g = res.settings_summary["project_materials"]["guard"]
    assert g["mode"] == "recommended" and g["conflicts"] and g["removed_by_mode"] == []
    assert "Recommended mode removes" not in g["resolution"]


def test_without_project_materials_a_conflicted_source_prepares_as_before(tmp_path):
    for mode in ("preserve", "recommended"):
        res = convert_to_u1(str(_conflicted(tmp_path)), out_dir=str(tmp_path / mode), prepare_mode=mode)
        assert res.blocked is False and res.output_path
        assert "project_materials" not in res.settings_summary
