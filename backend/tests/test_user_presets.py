"""Presets the person made in Snapmaker Orca: found read-only, proven only on evidence, never ambiguous
by last-wins, and re-checked every time a remembered mapping is used."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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


def _link_dir(link: Path, target: Path) -> None:
    """A directory symlink, or on Windows a junction (which needs no special right); skips if neither works."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return
    pytest.skip("this account can create neither a symlink nor a junction")


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
    assert r["status"] == PROVEN and r["source"] == "user" and "location" not in r
    assert r["ref"] == pc.user_ref("default", "Yoopai PLA+.json") and r["preset_name"] == "Yoopai PLA+"
    assert r["ref"].startswith("user:") and "default" not in r["ref"] and "Yoopai" not in r["ref"]    # opaque
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
    user = c.evaluate("Acme PLA @U1", "0.4", ref=pc.user_ref("default", "Acme PLA @U1.json"))
    assert user["status"] == PROVEN and user["source"] == "user"
    assert c.evaluate("Acme PLA @U1", "0.4", ref=pc.user_ref("default", "gone.json"))["status"] == NO_MATCH


def test_two_user_presets_with_one_name_are_ambiguous(world):
    _user(world.data, "Twin PLA", folder="default", inherits=MATTE)
    _user(world.data, "Twin PLA", folder="12345", inherits=MATTE)
    r = cat().evaluate("Twin PLA", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and len({x["ref"] for x in r["choices"]}) == 2
    assert all("location" not in x for x in r["choices"])
    pinned = cat().evaluate("Twin PLA", "0.4", ref=pc.user_ref("12345", "Twin PLA.json"))
    # with two Orca account folders Studio cannot tell which one Orca has loaded, so the pick is the person's to confirm
    assert pinned["status"] == NEEDS_CONFIRMATION and pinned["confirmable"] is True and pinned["preset_name"] == "Twin PLA"


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
    _save(store, cat(), "Yoopai PLA+", ref=pc.user_ref("default", "Yoopai PLA+.json"))
    again = mm.resolve(cat(), store, "spoolease", spool, "0.4")
    assert (again["status"], again["match_source"], again["source"]) == (PROVEN, mm.SOURCE_SAVED_SPOOL, "user")


def test_an_unproven_user_preset_can_be_remembered_only_when_the_person_confirmed_it(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    store = mm.Store(str(world.tmp / "m.json"))
    with pytest.raises(ValueError):
        _save(store, cat(), "Mystery PLA", ref=pc.user_ref("default", "Mystery PLA.json"))            # not confirmed
    row = _save(store, cat(), "Mystery PLA", accept=True, ref=pc.user_ref("default", "Mystery PLA.json"))
    assert row["proof"] == "user_confirmed" and row["source"] == "user" and row["ref"] == pc.user_ref("default", "Mystery PLA.json")
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
    _save(store, cat(), "Yoopai PLA+", ref=pc.user_ref("default", "Yoopai PLA+.json"))
    assert mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")["status"] == PROVEN          # pinned to the user file
    old = mm.Store(str(world.tmp / "old.json"))
    _save(old, cat(), "Yoopai PLA+", ref=pc.user_ref("default", "Yoopai PLA+.json"))
    _user(world.data, "Yoopai PLA+", folder="999", inherits=MATTE)                            # a second account folder appears
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    # Studio can no longer tell which account Orca has loaded: the mapping is downgraded, not applied
    assert got["status"] == NEEDS_CONFIRMATION and got["ref"] == pc.user_ref("default", "Yoopai PLA+.json")
    # an old mapping with no pin cannot choose between two
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
    assert (y["status"], y["proof"], y["ref"], y["ambiguous"]) == \
        ("proven", "inherited", pc.user_ref("default", "Yoopai PLA+.json"), False)
    # nothing about where the file lives or what it is called on disk leaves the backend
    assert "location" not in y and "parent" not in y
    blob = json.dumps(out)
    assert "default" not in blob.replace("default_", "") and ".json" not in blob
    m = rows[("Mystery PLA", "user")]
    assert m["status"] == "needs_confirmation" and "does not say which printers" in m["reason"]
    assert rows[(MATTE, "system")]["ref"].startswith("sys:") and rows[(MATTE, "system")]["status"] == "proven"
    assert rows[("Acme PLA @U1", "system")]["ambiguous"] is True and rows[("Acme PLA @U1", "user")]["ambiguous"] is True
    assert out["source"]["user_presets"] == 3


def test_a_user_preset_is_used_by_prepare_once_the_person_confirms_it(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"])
    src = _project(world.tmp)
    with pytest.raises(ValueError, match="does not say which printers"):
        service.convert(str(src), str(world.tmp / "o1"), "preserve", False,
                        {"selections": [{"slot": 0, "preset": "Mystery PLA", "ref": pc.user_ref("default", "Mystery PLA.json")}]})
    res = service.convert(str(src), str(world.tmp / "o2"), "preserve", False, {"selections": [
        {"slot": 0, "preset": "Mystery PLA", "ref": pc.user_ref("default", "Mystery PLA.json"), "source": "user", "accept_unproven": True,
         "fingerprint": cat().evaluate("Mystery PLA", "0.4")["fingerprint"],
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
                                      "ref": pc.user_ref("default", "Yoopai PLA+.json"), "source": "user", "origin": "exact_name"})
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
                                      "ref": pc.user_ref("default", "Mystery PLA.json"), "accept_unproven": True,
                                      "fingerprint": cat().evaluate("Mystery PLA", "0.4")["fingerprint"]})
    service.project_materials(str(_project(world.tmp)))
    service.convert(str(_project(world.tmp, name="p2.3mf")), str(world.tmp / "o"), "preserve", False,
                    {"selections": [{"slot": 0, "preset": "Yoopai PLA+"}]})
    assert _tree(world.system, world.data) == before
    # Studio's own file is the only thing written, and it is somewhere else
    assert (world.tmp / "studio-data" / mm.FILE_NAME).exists()


# --- review repairs --------------------------------------------------------------------------------------------------

def _fp(name, **pin):
    return cat().evaluate(name, "0.4", **pin)["fingerprint"]


def test_a_confirmed_preset_edited_to_list_only_other_printers_is_no_longer_usable(world):
    path = _user(world.data, "Mystery PLA", filament_type=["PLA"])                    # says nothing about printers
    store = mm.Store(str(world.tmp / "m.json"))
    pin = dict(ref=pc.user_ref("default", "Mystery PLA.json"))
    _save(store, cat(), "Mystery PLA", accept=True, **pin)
    assert mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")["status"] == PROVEN
    path.write_text(json.dumps({"name": "Mystery PLA", "from": "User", "filament_type": ["PLA"],
                                "compatible_printers": ["Prusa MK4 (0.4 nozzle)"]}), "utf-8")      # now lists another printer
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NEEDS_CONFIRMATION and got["stale"] is True                  # a different claim is a different preset


def test_a_symlinked_filament_folder_or_file_never_reads_outside_the_user_root(world, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "Elsewhere PLA.json").write_text(json.dumps({"name": "Elsewhere PLA", "inherits": MATTE}), "utf-8")
    user = world.data / "user"
    (user / "default").mkdir(parents=True)
    _link_dir(user / "default" / "filament", outside)
    assert "Elsewhere PLA" not in cat().entries
    _link_dir(user / "linked", outside)
    assert "Elsewhere PLA" not in cat().entries and cat().source["user_presets"] == 0


def test_a_symlinked_preset_file_is_never_read(world, tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"name": "Linked PLA", "inherits": MATTE}), "utf-8")
    d = world.data / "user" / "default" / "filament"
    d.mkdir(parents=True)
    try:
        (d / "Linked PLA.json").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("this account may not create symlinks")
    assert "Linked PLA" not in cat().entries


def test_case_only_look_alikes_are_resolved_by_an_explicit_pin(world):
    _user(world.data, "acme pla @u1", inherits="Acme PLA @U1")
    c = cat()
    assert c.evaluate("Acme PLA @U1", "0.4")["status"] == NEEDS_CONFIRMATION
    assert c.evaluate("Acme PLA @U1", "0.4", source="system")["status"] == PROVEN
    user = c.evaluate("acme pla @u1", "0.4", ref=pc.user_ref("default", "acme pla @u1.json"))
    assert user["status"] == PROVEN and user["source"] == "user" and user["preset_name"] == "acme pla @u1"
    rows = service.material_presets("0.4")["presets"]
    assert {(r["preset_name"], r["source"], r["ambiguous"]) for r in rows if "cme" in r["preset_name"]} == \
        {("Acme PLA @U1", "system", True), ("acme pla @u1", "user", True)}


def test_with_more_than_one_orca_account_folder_nothing_of_the_persons_is_proven(world):
    _user(world.data, "Yoopai PLA+", folder="default", inherits=MATTE)
    assert cat().evaluate("Yoopai PLA+", "0.4")["status"] == PROVEN                     # one account: unambiguous
    _user(world.data, "Other PLA", folder="12345", inherits=MATTE)
    for name in ("Yoopai PLA+", "Other PLA"):
        r = cat().evaluate(name, "0.4")
        assert r["status"] == NEEDS_CONFIRMATION and r["confirmable"] is True
        assert "more than one Orca account folder" in r["reason"]
    assert cat().evaluate(MATTE, "0.4")["status"] == PROVEN                             # Orca's own presets are unaffected


def test_the_persons_say_so_is_tied_to_the_preset_they_were_shown(world):
    path = _user(world.data, "Mystery PLA", filament_type=["PLA"])
    src = _project(world.tmp)
    pin = {"ref": pc.user_ref("default", "Mystery PLA.json"), "source": "user", "accept_unproven": True}
    shown = _fp("Mystery PLA", ref=pin["ref"])
    for bad in ({}, {"fingerprint": "0" * 24}, {"fingerprint": None}):
        with pytest.raises(ValueError, match="changed since you confirmed it"):
            service.convert(str(src), str(world.tmp / "o"), "preserve", False,
                            {"selections": [{"slot": 0, "preset": "Mystery PLA", **pin, **bad}]})
        with pytest.raises(ValueError, match="changed since you confirmed it"):
            service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 1, "preset": "Mystery PLA", **pin, **bad})
    # the file is replaced by a different unproven preset after the person was shown the first one
    path.write_text(json.dumps({"name": "Mystery PLA", "from": "User", "filament_type": ["TPU"], "filament_vendor": ["Other"]}), "utf-8")
    with pytest.raises(ValueError, match="changed since you confirmed it"):
        service.convert(str(src), str(world.tmp / "o"), "preserve", False,
                        {"selections": [{"slot": 0, "preset": "Mystery PLA", **pin, "fingerprint": shown}]})
    ok = service.convert(str(src), str(world.tmp / "o2"), "preserve", False,
                         {"selections": [{"slot": 0, "preset": "Mystery PLA", **pin, "fingerprint": _fp("Mystery PLA", ref=pin["ref"])}]})
    assert ok["output_path"]


def test_the_new_fields_are_validated_strictly_on_every_selection(world):
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    src = _project(world.tmp)
    for bad in ({"accept_unproven": 1}, {"accept_unproven": 0}, {"accept_unproven": "true"}, {"ref": 7}, {"source": "cloud"}):
        with pytest.raises(ValueError):
            service.convert(str(src), str(world.tmp / "o"), "preserve", False,
                            {"selections": [{"slot": 0, "colour": "#112233", **bad}]})      # no preset at all: still rejected
        with pytest.raises(ValueError):
            service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 1,
                                              "preset": "Yoopai PLA+", **bad})


def test_an_unproven_preset_named_for_another_nozzle_is_not_offered_for_this_one(world):
    _user(world.data, "Acme PLA 0.2 nozzle", filament_type=["PLA"])
    c = cat()
    assert c.evaluate("Acme PLA", "0.4")["status"] == NO_MATCH
    assert c.evaluate("Acme PLA", "0.2")["confirmable"] is True
    assert "Acme PLA" not in {r["base_name"] for r in service.material_presets("0.4")["presets"]}


def test_a_confirmed_preset_of_another_material_is_reported_as_a_mismatch(world):
    _user(world.data, "Mystery PLA", filament_type=["PLA"], filament_vendor=["Somebody"])
    pin = {"ref": pc.user_ref("default", "Mystery PLA.json"), "source": "user", "accept_unproven": True,
           "fingerprint": _fp("Mystery PLA", ref=pc.user_ref("default", "Mystery PLA.json"))}
    res = service.convert(str(_project(world.tmp)), str(world.tmp / "o"), "preserve", False, {"selections": [
        {"slot": 2, "preset": "Mystery PLA", **pin,
         "spool": {"provider": "spoolease", "id": 9, "vendor": "Yoopai", "material": "PETG"}}]})
    codes = [d["code"] for d in res["settings_summary"]["project_materials"]["fidelity"]["slots"][2]["discrepancies"]]
    assert "material_mismatch" in codes and "vendor_mismatch" in codes and "user_preset_unproven" in codes


# --- two of Orca's own preset files claiming one name ------------------------------------------------------------------

def _dup(world, name="Dup PLA @U1", vendor="Acme", ftype="PLA"):
    """Two bundled files for one base name and nozzle, as a broken or overlapping profile pack can ship."""
    for filename in ("Dup PLA @U1.json", "Dup PLA @U1 (second file).json"):
        (world.fil / filename).write_text(json.dumps({
            "type": "filament", "from": "system", "instantiation": "true", "name": name,
            "compatible_printers": U1_04, "filament_vendor": [vendor], "filament_type": [ftype]}), "utf-8")
    return [pc.system_ref("Dup PLA @U1.json"), pc.system_ref("Dup PLA @U1 (second file).json")]


def test_two_system_files_with_one_name_are_both_listed_and_individually_selectable(world):
    first, second = _dup(world)
    c = cat()
    amb = c.evaluate("Dup PLA @U1", "0.4")
    assert amb["status"] == NEEDS_CONFIRMATION and amb["preset_name"] is None
    assert sorted(x["ref"] for x in amb["choices"]) == sorted([first, second])
    rows = [r for r in service.material_presets("0.4")["presets"] if r["base_name"] == "Dup PLA @U1"]
    assert len(rows) == 2 and all(r["ambiguous"] and r["source"] == "system" and r["status"] == "proven" for r in rows)
    assert sorted(r["ref"] for r in rows) == sorted([first, second])
    for ref in (first, second):                                     # each one, by its own pin, is usable on its own
        r = c.evaluate("Dup PLA @U1", "0.4", ref=ref)
        assert r["status"] == PROVEN and r["ref"] == ref and r["preset_name"] == "Dup PLA @U1"


def test_a_pinned_system_record_is_used_by_prepare_and_an_unpinned_name_is_refused(world):
    first, _ = _dup(world)
    src = _project(world.tmp)
    with pytest.raises(ValueError, match="not a proven installed preset"):
        service.convert(str(src), str(world.tmp / "o1"), "preserve", False,
                        {"selections": [{"slot": 0, "preset": "Dup PLA @U1"}]})
    ok = service.convert(str(src), str(world.tmp / "o2"), "preserve", False,
                         {"selections": [{"slot": 0, "preset": "Dup PLA @U1", "ref": first, "source": "system"}]})
    assert ok["output_path"]


def test_a_saved_mapping_reuses_that_exact_system_record_and_never_its_sibling(world):
    first, second = _dup(world)
    store = mm.Store(str(world.tmp / "m.json"))
    row = _save(store, cat(), "Dup PLA @U1", ref=first)
    assert row["ref"] == first and row["source"] == "system"
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert (got["status"], got["ref"], got["match_source"]) == (PROVEN, first, mm.SOURCE_SAVED_SPOOL)
    (world.fil / "Dup PLA @U1.json").unlink()                                      # the pinned record disappears
    gone = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert gone["status"] == NO_MATCH and gone["preset_name"] is None             # the sibling is NOT silently used
    assert cat().evaluate("Dup PLA @U1", "0.4", ref=second)["status"] == PROVEN   # it is still there, just not what was confirmed


def test_replacing_the_pinned_system_record_invalidates_the_mapping(world):
    first, _ = _dup(world)
    store = mm.Store(str(world.tmp / "m.json"))
    _save(store, cat(), "Dup PLA @U1", ref=first)
    (world.fil / "Dup PLA @U1.json").write_text(json.dumps({
        "type": "filament", "from": "system", "instantiation": "true", "name": "Dup PLA @U1",
        "compatible_printers": U1_04, "filament_vendor": ["Acme"], "filament_type": ["PETG"]}), "utf-8")
    got = mm.resolve(cat(), store, "spoolease", SPOOL, "0.4")
    assert got["status"] == NEEDS_CONFIRMATION and got["stale"] is True


def test_system_and_user_collisions_stay_explicit_with_a_ref_on_both(world):
    _user(world.data, "Acme PLA @U1", inherits="Acme PLA @U1")
    r = cat().evaluate("Acme PLA @U1", "0.4")
    refs = {x["source"]: x["ref"] for x in r["choices"]}
    assert refs["system"].startswith("sys:") and refs["user"].startswith("user:")
    assert cat().evaluate("Acme PLA @U1", "0.4", ref=refs["system"])["source"] == "system"
    assert cat().evaluate("Acme PLA @U1", "0.4", ref=refs["user"])["source"] == "user"


def test_no_path_or_file_name_leaves_the_backend_for_any_preset(world, tmp_path):
    _dup(world)
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    blob = json.dumps(service.material_presets("0.4")) + json.dumps(cat().evaluate("Dup PLA @U1", "0.4"))
    for leak in (".json", str(tmp_path), "(second file)", "orca-data", "filament/", "filament\\", "default"):
        assert leak not in blob.replace("default_", ""), leak
    assert all(r["ref"].startswith(("sys:", "user:")) for r in service.material_presets("0.4")["presets"])


def test_the_line_for_a_preset_the_person_made_does_not_promise_what_orca_may_not_do(world):
    """Measured on Orca 2.4.0 (isolated profile): a project naming a user preset opened as a Customized Preset with the
    project's own values. Studio says only what is certain for those, and keeps the stronger sentence for Orca's own."""
    _user(world.data, "Yoopai PLA+", inherits=MATTE)
    mine = service.convert(str(_project(world.tmp)), str(world.tmp / "o1"), "preserve", False,
                           {"selections": [{"slot": 1, "preset": "Yoopai PLA+"}]})
    line = mine["settings_summary"]["project_materials"]["fidelity"]["slots"][1]["line"]
    assert "come from the installed" not in line
    assert "Studio cannot confirm Snapmaker Orca will apply" in line and "Customized Preset" in line
    assert "Check the filament in Orca before slicing" in line
    # nothing else about a slot using the person's own preset promises that Orca applies its values
    lines = mine["settings_summary"]["project_materials"]["fidelity"]["lines"]
    for text in lines:
        if "Yoopai PLA+" in text:
            assert "takes them from" not in text and "apply the installed preset" not in text and "come from the installed" not in text, text
    system = service.convert(str(_project(world.tmp, name="p2.3mf")), str(world.tmp / "o2"), "preserve", False,
                             {"selections": [{"slot": 1, "preset": MATTE}]})
    assert "come from the installed" in system["settings_summary"]["project_materials"]["fidelity"]["slots"][1]["line"]


def test_a_user_preset_whose_name_says_another_nozzle_is_never_proven_for_this_one(world):
    """Its compatible_printers (inherited from a 0.4 parent) say 0.4, its name says 0.2: the name is what Orca writes."""
    _user(world.data, "Foo PLA 0.2 nozzle", inherits=MATTE)
    c = cat()
    assert c.evaluate("Foo PLA", "0.4")["status"] == NO_MATCH
    assert "Foo PLA" not in {r["base_name"] for r in service.material_presets("0.4")["presets"]}
    assert c.evaluate("Foo PLA", "0.2")["status"] == NO_MATCH                         # the parent only fits 0.4


def test_a_fingerprint_the_client_sends_must_match_even_for_a_proven_preset(world):
    path = _user(world.data, "Yoopai PLA+", inherits=MATTE)
    src = _project(world.tmp)
    ref = pc.user_ref("default", "Yoopai PLA+.json")
    shown = cat().evaluate("Yoopai PLA+", "0.4", ref=ref)["fingerprint"]
    ok = service.convert(str(src), str(world.tmp / "o1"), "preserve", False,
                         {"selections": [{"slot": 0, "preset": "Yoopai PLA+", "ref": ref, "fingerprint": shown}]})
    assert ok["output_path"]
    path.write_text(json.dumps({"name": "Yoopai PLA+", "from": "User", "inherits": MATTE, "filament_type": ["PETG"]}), "utf-8")
    for call in (
        lambda: service.convert(str(src), str(world.tmp / "o2"), "preserve", False,
                                {"selections": [{"slot": 0, "preset": "Yoopai PLA+", "ref": ref, "fingerprint": shown}]}),
        lambda: service.material_mapping_confirm({"scope": "spool", "provider": "spoolease", "spool_id": 1, "preset": "Yoopai PLA+",
                                                  "ref": ref, "fingerprint": shown}),
    ):
        with pytest.raises(ValueError, match="changed since you confirmed it"):
            call()
    # a client that sends no fingerprint is unchanged
    assert service.convert(str(src), str(world.tmp / "o3"), "preserve", False,
                           {"selections": [{"slot": 0, "preset": MATTE}]})["output_path"]
