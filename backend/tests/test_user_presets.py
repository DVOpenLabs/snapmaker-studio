"""Presets the person made in Snapmaker Orca: found read-only, proven only on evidence, never ambiguous
by last-wins, and re-checked every time a remembered mapping is used."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from snapstudio_api import service
from snapstudio_core import material_mapping as mm
from snapstudio_core import preset_catalog as pc
from snapstudio_core import project_materials as pm
from snapstudio_core.preset_catalog import NEEDS_CONFIRMATION, NO_MATCH, PROVEN
from tests.test_project_materials import MATTE, _cfg, _project

U1_04 = ["Snapmaker U1 (0.4 nozzle)"]


def _sys(folder: Path, name: str, *, printers=U1_04, vendor="Snapmaker", ftype="PLA", inherits=None, instantiation="true"):
    doc = {"type": "filament", "from": "system", "instantiation": instantiation, "name": name,
           "filament_vendor": [vendor], "filament_type": [ftype]}
    if printers is not None:
        doc["compatible_printers"] = printers
    if inherits:
        doc["inherits"] = inherits
    (folder / f"{name}.json").write_text(json.dumps(doc), "utf-8")


def _user(root: Path, name: str, *, folder="default", filename=None, **keys) -> Path:
    """A user preset exactly as Orca writes one: only what differs, plus identity."""
    d = root / "user" / folder / "filament"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"name": name, "from": "User", "is_custom_defined": "0", "version": "2.2.49.2", **keys}
    path = d / (filename or f"{name}.json")
    path.write_text(json.dumps(doc), "utf-8")
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A system catalogue, an Orca data folder for user presets, and a data folder for Studio's own files."""
    system = tmp_path / "orca" / "Snapmaker"
    fil = system / "filament"
    fil.mkdir(parents=True)
    _sys(fil, MATTE)
    _sys(fil, "Generic PETG @U1 0.4 nozzle", vendor="Generic", ftype="PETG")
    _sys(fil, "Acme PLA @U1", vendor="Acme")
    data = tmp_path / "orca-data"
    monkeypatch.setenv("SNAPSTUDIO_ORCA_PROFILES_DIR", str(system))
    monkeypatch.setenv("SNAPSTUDIO_ORCA_DATA_DIR", str(data))
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "studio-data"))
    return type("World", (), {"system": system, "fil": fil, "data": data, "tmp": tmp_path})


def cat():
    return pc.load_default()


def _tree(*roots: Path) -> dict:
    out = {}
    for root in roots:
        for p in sorted(root.rglob("*")) if root.exists() else []:
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            else:
                out[str(p)] = "dir"
    return out


# --- discovery -----------------------------------------------------------------------------------------

def test_a_user_preset_is_discovered_with_its_identity(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE, filament_type=["PLA"])
    c = cat()
    assert c.source["user_presets"] == 1 and c.source["presets"] == 3
    r = c.evaluate("Yoopai PLA+", "0.4")
    assert r["status"] == PROVEN and r["source"] == "user" and r["location"] == "default"
    assert r["ref"] == "user:default/Yoopai PLA+.json" and r["preset_name"] == "Yoopai PLA+"
    rec = c.entries["Yoopai PLA+"]["records"][0]
    assert (rec["parent"], rec["file"], rec["size"] == path.stat().st_size, rec["mtime_ns"] == path.stat().st_mtime_ns) == \
        (MATTE, "Yoopai PLA+.json", True, True)
    assert rec["vendor"] == "Snapmaker" and rec["filament_type"] == "PLA"        # inherited, not invented


def test_an_inherited_u1_compatibility_is_evidence_and_says_so(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    rec = cat().entries["Yoopai PLA+"]["records"][0]
    assert rec["proof"] == "inherited" and rec["nozzles"] == {"0.4"}
    assert cat().evaluate("Yoopai PLA+", "0.2")["status"] == NO_MATCH            # the parent does not fit 0.2 mm


def test_an_explicit_u1_list_on_the_user_preset_is_evidence(world):
    _user(world.data, "My Own PETG", compatible_printers=U1_04, filament_type=["PETG"], filament_vendor=["Me"])
    r = cat().evaluate("My Own PETG", "0.4")
    assert r["status"] == PROVEN and r["proof"] == "listed"


def test_a_user_preset_that_does_not_say_which_printers_is_confirmable_not_proven(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    r = cat().evaluate("Mystery PLA", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["confirmable"] is True
    assert r["preset_name"] == "Mystery PLA" and "does not say which printers" in r["reason"]
    assert cat().evaluate("Mystery PLA", "0.6")["confirmable"] is True            # unknown for every nozzle


def test_a_user_preset_listing_only_other_printers_is_not_proven_for_the_u1(world):
    _user(world.data, "Prusa Only", compatible_printers=["Prusa MK4 (0.4 nozzle)"])
    r = cat().evaluate("Prusa Only", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and "other printers" in r["reason"]


def test_a_parent_that_is_not_u1_compatible_gives_no_evidence(world):
    _sys(world.fil, "Other Vendor PLA", printers=["Creality K1 (0.4 nozzle)"], instantiation="false")
    _user(world.data, "Child Of Other", inherits="Other Vendor PLA")
    assert cat().evaluate("Child Of Other", "0.4")["status"] == NEEDS_CONFIRMATION


def test_unreadable_oversized_and_non_json_files_are_ignored_and_info_files_are_not_read(world):
    d = world.data / "user" / "default" / "filament"
    _user(world.data, "Fine One", inherits=MATTE)
    (d / "broken.json").write_text("{not json", "utf-8")
    (d / "huge.json").write_text(json.dumps({"name": "Huge", "pad": "x" * 1_200_000}), "utf-8")
    (d / "Fine One.info").write_text("user_id = 123\nsync_info = SECRET-ACCOUNT-TOKEN\n", "utf-8")
    (d / "notes.txt").write_text("hi", "utf-8")
    c = cat()
    assert c.source["user_presets"] == 1 and "Huge" not in c.entries
    assert "SECRET-ACCOUNT-TOKEN" not in json.dumps(c.source) + json.dumps(sorted(c.entries))
    # only <data>/user/<id>/filament is looked at: a sibling folder is never opened
    (world.data / "user" / "default" / "machine").mkdir()
    (world.data / "user" / "default" / "machine" / "Printer.json").write_text(json.dumps({"name": "Printer"}), "utf-8")
    assert "Printer" not in cat().entries


def test_a_missing_or_empty_orca_data_folder_leaves_the_system_catalogue_alone(world):
    assert cat().source["user_presets"] == 0
    (world.data / "user" / "default" / "filament").mkdir(parents=True)
    assert cat().source["user_presets"] == 0 and len(cat()) == 3


def test_default_user_roots_follow_the_platform_and_the_override():
    assert pc.default_user_roots({"SNAPSTUDIO_ORCA_DATA_DIR": "X"}, "win32") == [Path("X") / "user"]
    assert pc.default_user_roots({"APPDATA": r"C:\Users\p\AppData\Roaming"}, "win32") == \
        [Path(r"C:\Users\p\AppData\Roaming") / "Snapmaker_Orca" / "user"]
    assert pc.default_user_roots({"HOME": "/home/p"}, "linux") == [Path("/home/p/.config") / "Snapmaker_Orca" / "user"]
    assert pc.default_user_roots({}, "win32") == [] and pc.default_user_roots({}, "darwin") == []


# --- collisions -------------------------------------------------------------------------------------------

def test_a_system_and_a_user_preset_with_one_name_are_ambiguous_and_resolved_by_the_person(world):
    _user(world.data, "Acme PLA @U1", inherits="Acme PLA @U1")
    c = cat()
    r = c.evaluate("Acme PLA @U1", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["preset_name"] is None and len(r["choices"]) == 2
    assert {x["source"] for x in r["choices"]} == {"system", "user"}
    assert c.evaluate("Acme PLA @U1", "0.4", source="system")["status"] == PROVEN
    user = c.evaluate("Acme PLA @U1", "0.4", ref="user:default/Acme PLA @U1.json")
    assert user["status"] == PROVEN and user["source"] == "user"
    assert c.evaluate("Acme PLA @U1", "0.4", ref="user:default/gone.json")["status"] == NO_MATCH


def test_two_user_presets_with_one_name_are_ambiguous(world):
    _user(world.data, "Twin PLA", folder="default", inherits=MATTE)
    _user(world.data, "Twin PLA", folder="12345", inherits=MATTE)
    r = cat().evaluate("Twin PLA", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and sorted(x["location"] for x in r["choices"]) == ["12345", "default"]
    assert cat().evaluate("Twin PLA", "0.4", ref="user:12345/Twin PLA.json")["status"] == PROVEN


def test_a_user_preset_and_its_nozzle_variant_claiming_one_nozzle_are_ambiguous(world):
    _user(world.data, "Foo PLA", inherits=MATTE)
    _user(world.data, "Foo PLA 0.4 nozzle", inherits=MATTE)
    r = cat().evaluate("Foo PLA", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["candidates"] == ["Foo PLA", "Foo PLA 0.4 nozzle"]


def test_a_system_name_with_a_user_look_alike_in_another_case_is_never_picked_silently(world):
    _user(world.data, "acme pla @u1", inherits=MATTE)
    r = cat().evaluate("Acme PLA @U1", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["preset_name"] is None


def test_a_generic_suggestion_never_picks_between_a_system_and_a_user_preset(world):
    _sys(world.fil, "Generic PLA @U1")
    assert cat().suggest_generic("PLA", "0.4")["base_name"] == "Generic PLA @U1"
    _user(world.data, "Generic PLA @U1", inherits=MATTE)
    assert cat().suggest_generic("PLA", "0.4") is None


# --- mappings ----------------------------------------------------------------------------------------------

def _save(store, catalog, name, *, sid="9", accept=False, **pin):
    return store.put(scope=mm.SCOPE_SPOOL, provider="spoolease", spool_id=sid, origin=mm.SOURCE_MANUAL,
                     preset=catalog.evaluate(name, "0.4", **pin), catalog=catalog, accept_unproven=accept)


SPOOL = {"id": "9", "vendor": "Yoopai", "material": "PLA", "subtype": "Matte"}


def test_the_spoolease_path_needs_confirmation_first_then_becomes_usable(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    store = mm.Store(str(world.tmp / "m.json"))
    spool = {**SPOOL, "slicer_filament": "Yoopai PLA+"}
    first = mm.resolve(cat(), store, "spoolease", spool, "0.4")
    assert (first["status"], first["match_source"], first["preset_name"], first["source"]) == \
        (NEEDS_CONFIRMATION, mm.SOURCE_EXACT_NAME, "Yoopai PLA+", "user")           # slicer_filament alone is never proven
    _save(store, cat(), "Yoopai PLA+", ref="user:default/Yoopai PLA+.json")
    again = mm.resolve(cat(), store, "spoolease", spool, "0.4")
    assert (again["status"], again["match_source"], again["source"]) == (PROVEN, mm.SOURCE_SAVED_SPOOL, "user")


def test_an_unproven_user_preset_can_be_remembered_only_when_the_person_confirmed_it(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    store = mm.Store(str(world.tmp / "m.json"))
    with pytest.raises(ValueError):
        _save(store, cat(), "Mystery PLA", ref="user:default/Mystery PLA.json")            # not confirmed
    row = _save(store, cat(), "Mystery PLA", accept=True, ref="user:default/Mystery PLA.json")
    assert row["proof"] == "user_confirmed" and row["source"] == "user" and row["ref"] == "user:default/Mystery PLA.json"
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == PROVEN and got["proof"] == "user_confirmed"


def test_a_deleted_user_preset_invalidates_the_mapping(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE)
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Yoopai PLA+")
    assert mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")["status"] == PROVEN
    path.unlink()
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NO_MATCH and got["preset_name"] is None and got["match_source"] == mm.SOURCE_NONE


def test_a_renamed_user_preset_invalidates_the_mapping(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE)
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Yoopai PLA+")
    path.unlink()
    _user(world.data, "Yoopai PLA Plus", inherits=MATTE)
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NO_MATCH and got["preset_name"] is None


def test_a_replaced_user_preset_is_stale_and_a_tuned_one_is_not(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE, nozzle_temperature=["215"])
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Yoopai PLA+")
    path.write_text(json.dumps({"name": "Yoopai PLA+", "from": "User", "inherits": MATTE, "nozzle_temperature": ["230"]}), "utf-8")
    assert mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")["status"] == PROVEN          # tuning a temperature is not a new preset
    path.write_text(json.dumps({"name": "Yoopai PLA+", "from": "User", "inherits": MATTE, "filament_type": ["PETG"]}), "utf-8")
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NEEDS_CONFIRMATION and got["stale"] is True                      # a different kind of filament is


def test_a_mapping_whose_user_preset_stops_being_compatible_is_downgraded(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE)
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Yoopai PLA+")
    path.write_text(json.dumps({"name": "Yoopai PLA+", "from": "User", "compatible_printers": ["Prusa MK4 (0.4 nozzle)"]}), "utf-8")
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NEEDS_CONFIRMATION and got["confirmable"] is True       # a preset for another printer is not applied


def test_a_mapping_turns_ambiguous_when_a_system_preset_of_that_name_appears(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Yoopai PLA+", ref="user:default/Yoopai PLA+.json")
    assert mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")["status"] == PROVEN          # pinned to the user file
    _user(world.data, "Yoopai PLA+", folder="999", inherits=MATTE)                            # a second user preset appears
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == PROVEN and got["ref"] == "user:default/Yoopai PLA+.json"         # still the one the person pinned
    # an old mapping with no pin cannot choose between two
    old = mm.Store(str(world.tmp / "old.json"))
    _save(old, cat(), "Yoopai PLA+", ref="user:default/Yoopai PLA+.json")
    row = json.loads(Path(old.path).read_text())["mappings"][0]
    row["ref"] = None
    Path(old.path).write_text(json.dumps({"schema": mm.SCHEMA, "mappings": [row]}))
    assert mm.resolve(cat(), old, "spoolease", SPOOL, "0.4")["status"] == NEEDS_CONFIRMATION


def test_mappings_are_never_keyed_by_filament_or_setting_id(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE, setting_id="SHARED-ID", filament_id="SHARED-ID")
    store = mm.Store(str(world.tmp / "m.json"))
    row = _save(store, cat(), "Yoopai PLA+")
    assert "SHARED-ID" not in json.dumps(row) and "setting_id" not in row and "filament_id" not in row


# --- the picker and Prepare ---------------------------------------------------------------------------------

def test_user_presets_appear_in_the_picker_with_their_source_and_proof(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    _user(world.data, "Acme PLA @U1", inherits="Acme PLA @U1")
    out = service.material_presets("0.4")
    rows = {(r["preset_name"], r["source"]): r for r in out["presets"]}
    y = rows[("Yoopai PLA+", "user")]
    assert (y["status"], y["proof"], y["location"], y["ref"], y["parent"], y["ambiguous"]) == \
        ("proven", "inherited", "default", "user:default/Yoopai PLA+.json", MATTE, False)
    m = rows[("Mystery PLA", "user")]
    assert m["status"] == "needs_confirmation" and "does not say which printers" in m["reason"]
    assert rows[(MATTE, "system")]["ref"] is None and rows[(MATTE, "system")]["status"] == "proven"
    assert rows[("Acme PLA @U1", "system")]["ambiguous"] is True and rows[("Acme PLA @U1", "user")]["ambiguous"] is True
    assert out["source"]["user_presets"] == 3


def test_a_user_preset_is_used_by_prepare_once_the_person_confirms_it(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    src = _project(world.tmp)
    with pytest.raises(ValueError, match="does not say which printers"):
        service.convert(str(src), str(world.tmp / "o1"), "preserve", False,
                        {"selections": [{"slot": 0, "preset": "Mystery PLA", "ref": "user:default/Mystery PLA.json"}]})
    res = service.convert(str(src), str(world.tmp / "o2"), "preserve", False, {"selections": [
        {"slot": 0, "preset": "Mystery PLA", "ref": "user:default/Mystery PLA.json", "source": "user", "accept_unproven": True,
         "spool": {"provider": "spoolease", "id": 9, "vendor": "Yoopai", "material": "PLA", "subtype": "Matte"}}]})
    import zipfile
    out = json.loads(zipfile.ZipFile(res["output_path"]).read("Metadata/project_settings.config"))
    assert out["filament_settings_id"][0] == "Mystery PLA"
    s = res["settings_summary"]["project_materials"]["fidelity"]["slots"][0]
    assert (s["selection"]["preset_source"], s["selection"]["preset_proof"]) == ("user", "user_confirmed")
    assert "user_preset_unproven" in [d["code"] for d in s["discrepancies"]]
    assert "(a preset you made)" in s["line"]


def test_a_proven_user_preset_needs_no_extra_confirmation_and_is_recorded_as_such(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    res = service.convert(str(_project(world.tmp)), str(world.tmp / "o"), "preserve", False,
                          {"selections": [{"slot": 1, "preset": "Yoopai PLA+"}]})
    s = res["settings_summary"]["project_materials"]["fidelity"]["slots"][1]
    assert (s["selection"]["preset_source"], s["selection"]["preset_proof"]) == ("user", "inherited")
    assert "user_preset_unproven" not in [d["code"] for d in s["discrepancies"]]


def test_prepare_and_mapping_reject_bad_pins_and_flags(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    src = _project(world.tmp)
    for bad in ({"ref": 5}, {"source": "cloud"}, {"accept_unproven": "yes"}):
        with pytest.raises(ValueError):
            service.convert(str(src), str(world.tmp / "o"), "preserve", False,
                            {"selections": [{"slot": 0, "preset": "Yoopai PLA+", **bad}]})
        with pytest.raises(ValueError):
            service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 1,
                                              "preset": "Yoopai PLA+", **bad})


def test_the_mapping_endpoint_remembers_a_user_preset_and_the_next_analysis_uses_it(world, monkeypatch):
    from snapstudio_core import material_providers as providers
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    monkeypatch.setattr(providers, "read", lambda *a, **k: {
        "available": True, "slots": [], "spools": [{"id": "9", "vendor": "Yoopai", "material": "PLA", "subtype": "Matte",
                                                     "color": "#FF0000", "remaining_g": 400.0, "remaining_quality": "tracked",
                                                     "remaining_as_of": None, "archived": False, "slicer_filament": "Yoopai PLA+"}]})
    kw = dict(provider="spoolease", provider_url="http://192.168.1.50")
    first = service.project_materials(str(_project(world.tmp)), **kw)["slots"][0]["candidates"][0]["mapping"]
    assert (first["status"], first["match_source"], first["source"]) == (NEEDS_CONFIRMATION, mm.SOURCE_EXACT_NAME, "user")
    service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 9, "preset": "Yoopai PLA+",
                                      "ref": "user:default/Yoopai PLA+.json", "source": "user", "origin": "exact_name"})
    second = service.project_materials(str(_project(world.tmp)), **kw)["slots"][0]["candidates"][0]["mapping"]
    assert (second["status"], second["match_source"], second["source"]) == (PROVEN, mm.SOURCE_SAVED_SPOOL, "user")


# --- read-only ----------------------------------------------------------------------------------------------------

def test_nothing_in_the_orca_folders_is_ever_written(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    (world.data / "user" / "default" / "filament" / "Yoopai PLA+.info").write_text("sync_info = x\n", "utf-8")
    before = _tree(world.system, world.data)
    c = cat()
    c.evaluate("Yoopai PLA+", "0.4"); c.evaluate("Mystery PLA", "0.4"); c.suggest_generic("PLA", "0.4")
    service.material_presets("0.4")
    service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 9, "preset": "Mystery PLA",
                                      "ref": "user:default/Mystery PLA.json", "accept_unproven": True})
    service.project_materials(str(_project(world.tmp)))
    service.convert(str(_project(world.tmp, name="p2.3mf")), str(world.tmp / "o"), "preserve", False,
                    {"selections": [{"slot": 0, "preset": "Yoopai PLA+"}]})
    assert _tree(world.system, world.data) == before
    # Studio's own file is the only thing written, and it is somewhere else
    assert (world.tmp / "studio-data" / mm.FILE_NAME).exists()
