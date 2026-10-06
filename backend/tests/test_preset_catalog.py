"""Installed Orca preset catalogue: what is proven, what needs confirming, what is not there."""
import json
from pathlib import Path

import pytest

from snapstudio_core import preset_catalog
from snapstudio_core.preset_catalog import PROVEN, NEEDS_CONFIRMATION, NO_MATCH


def _preset(folder: Path, name: str, *, instantiation="true", printers=None, inherits=None,
            vendor=None, ftype=None, setting_id=None, filename=None):
    doc = {"type": "filament", "from": "system", "instantiation": instantiation, "name": name}
    if inherits:
        doc["inherits"] = inherits
    if printers is not None:
        doc["compatible_printers"] = printers
    if vendor:
        doc["filament_vendor"] = [vendor]
    if ftype:
        doc["filament_type"] = [ftype]
    if setting_id:
        doc["setting_id"] = setting_id
    (folder / f"{filename or name}.json").write_text(json.dumps(doc), "utf-8")


@pytest.fixture
def profiles(tmp_path):
    root = tmp_path / "profiles" / "Snapmaker"
    fil = root / "filament"
    fil.mkdir(parents=True)
    (tmp_path / "profiles" / "Snapmaker.json").write_text(json.dumps({"version": "2.3.6.0"}), "utf-8")
    u1 = lambda n: [f"Snapmaker U1 ({n} nozzle)"]
    # Matte: plain name is the 0.4 variant, others carry the suffix. Parent holds no printers.
    _preset(fil, "Snapmaker PLA Matte @U1 base", instantiation="false", printers=[])
    _preset(fil, "Snapmaker PLA Matte @U1", inherits="Snapmaker PLA Matte @U1 base",
            printers=u1("0.4"), vendor="Snapmaker", ftype="PLA", setting_id="119531393501")
    _preset(fil, "Snapmaker PLA Matte @U1 0.2 nozzle", inherits="Snapmaker PLA Matte @U1 base",
            printers=u1("0.2"), vendor="Snapmaker", setting_id="119531393501")
    # SnapSpeed shares the ids with Matte on purpose: ids must never be the key.
    _preset(fil, "Snapmaker PLA SnapSpeed @U1", printers=u1("0.4"), vendor="Snapmaker",
            ftype="PLA", setting_id="119531393501")
    # Generic PLA exists for 0.2 only (no 0.4 file at all); Generic ASA has an explicit 0.4 file.
    _preset(fil, "Generic PLA @U1 0.2 nozzle", printers=u1("0.2"), vendor="Generic", ftype="PLA")
    _preset(fil, "Generic ASA @U1 0.4 nozzle", printers=u1("0.4"), vendor="Generic", ftype="ASA")
    # Not U1 at all, and a non-instantiated parent: neither is installed for the U1.
    _preset(fil, "Snapmaker PLA", printers=["Snapmaker A350"], vendor="Snapmaker", ftype="PLA")
    return root


def test_catalogue_reads_only_instantiated_u1_presets(profiles):
    cat = preset_catalog.load(profiles)
    assert sorted(cat.entries) == ["Generic ASA @U1", "Generic PLA @U1",
                                   "Snapmaker PLA Matte @U1", "Snapmaker PLA SnapSpeed @U1"]
    assert cat.source["profiles_version"] == "2.3.6.0"
    matte = cat.entries["Snapmaker PLA Matte @U1"]
    assert matte["nozzles"] == {"0.4": "Snapmaker PLA Matte @U1",
                                "0.2": "Snapmaker PLA Matte @U1 0.2 nozzle"}
    assert matte["filament_type"] == "PLA" and matte["vendor"] == "Snapmaker"


def test_missing_or_empty_folder_is_none_not_an_error(tmp_path):
    assert preset_catalog.load(tmp_path / "nope") is None
    (tmp_path / "filament").mkdir()
    assert preset_catalog.load(tmp_path) is None


def test_exact_name_for_a_supported_nozzle_is_proven(profiles):
    cat = preset_catalog.load(profiles)
    r = cat.evaluate("Snapmaker PLA Matte @U1", "0.4")
    assert r["status"] == PROVEN
    assert r["preset_name"] == "Snapmaker PLA Matte @U1"
    assert r["base_name"] == "Snapmaker PLA Matte @U1"
    # the exact name Orca writes depends on the nozzle
    assert cat.evaluate("Snapmaker PLA Matte @U1", "0.2")["preset_name"].endswith("0.2 nozzle")
    # asking with the suffixed name still lands on the same base preset
    assert cat.evaluate("Snapmaker PLA Matte @U1 0.2 nozzle", "0.4")["status"] == PROVEN
    assert cat.evaluate("  Snapmaker  PLA Matte @U1 ", "0.4")["status"] == PROVEN


def test_installed_preset_without_the_confirmed_nozzle_is_no_match(profiles):
    cat = preset_catalog.load(profiles)
    r = cat.evaluate("Generic PLA @U1", "0.4")
    assert r["status"] == NO_MATCH and "0.4" in r["reason"]
    assert r["base_name"] == "Generic PLA @U1"
    assert cat.evaluate("Generic PLA @U1", "0.2")["status"] == PROVEN
    assert cat.evaluate("Generic ASA @U1", "0.4")["preset_name"] == "Generic ASA @U1 0.4 nozzle"


def test_unknown_legacy_and_empty_names_are_no_match(profiles):
    cat = preset_catalog.load(profiles)
    for name in ("Snapmaker PLA", "My SpoolEase PLA", "", None, "Generic PLA @BBL H2D"):
        assert cat.evaluate(name, "0.4")["status"] == NO_MATCH


def test_letter_case_difference_needs_confirmation(profiles):
    cat = preset_catalog.load(profiles)
    r = cat.evaluate("snapmaker pla matte @u1", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["base_name"] == "Snapmaker PLA Matte @U1"


def test_two_presets_normalising_to_one_name_are_never_picked_silently(tmp_path):
    root = tmp_path / "Snapmaker"
    fil = root / "filament"
    fil.mkdir(parents=True)
    p = ["Snapmaker U1 (0.4 nozzle)"]
    _preset(fil, "Acme PLA @U1", printers=p, vendor="Acme", ftype="PLA")
    _preset(fil, "ACME PLA @U1", printers=p, vendor="Acme", ftype="PLA", filename="acme-other")
    cat = preset_catalog.load(root)
    r = cat.evaluate("Acme PLA @U1", "0.4")
    assert r["status"] == NEEDS_CONFIRMATION
    assert r["candidates"] == ["ACME PLA @U1", "Acme PLA @U1"]
    assert r["preset_name"] is None


def test_filament_and_setting_ids_are_not_the_key(profiles):
    cat = preset_catalog.load(profiles)
    # Matte and SnapSpeed share setting_id; each name still resolves to exactly itself.
    assert cat.entries["Snapmaker PLA Matte @U1"]["setting_id"] == \
        cat.entries["Snapmaker PLA SnapSpeed @U1"]["setting_id"]
    assert cat.evaluate("Snapmaker PLA SnapSpeed @U1", "0.4")["base_name"] == "Snapmaker PLA SnapSpeed @U1"
    assert cat.evaluate("119531393501", "0.4")["status"] == NO_MATCH


def test_generic_suggestion_is_never_proven(profiles):
    cat = preset_catalog.load(profiles)
    s = cat.suggest_generic("asa", "0.4")
    assert s["status"] == NEEDS_CONFIRMATION and s["preset_name"] == "Generic ASA @U1 0.4 nozzle"
    assert s["suggestion"] is True
    assert cat.suggest_generic("PLA", "0.4") is None          # Generic PLA has no 0.4 version
    assert cat.suggest_generic("PLA", "0.2")["preset_name"] == "Generic PLA @U1 0.2 nozzle"
    assert cat.suggest_generic("UNOBTANIUM", "0.4") is None
    assert cat.suggest_generic(None, "0.4") is None


def test_fingerprint_detects_a_changed_preset_identity(profiles):
    cat = preset_catalog.load(profiles)
    r = cat.evaluate("Snapmaker PLA Matte @U1", "0.4")
    assert cat.verify("Snapmaker PLA Matte @U1", r["fingerprint"], "0.4")["status"] == PROVEN
    changed = cat.verify("Snapmaker PLA Matte @U1", "0" * 24, "0.4")
    assert changed["status"] == NEEDS_CONFIRMATION and changed["stale"] is True
    # a preset the catalogue no longer has stays no_match
    assert cat.verify("Gone @U1", r["fingerprint"], "0.4")["status"] == NO_MATCH


def test_catalogue_fingerprint_follows_the_installed_set(profiles):
    a = preset_catalog.load(profiles).fingerprint
    assert preset_catalog.load(profiles).fingerprint == a
    _preset(profiles / "filament", "Generic PETG @U1", printers=["Snapmaker U1 (0.4 nozzle)"],
            vendor="Generic", ftype="PETG")
    assert preset_catalog.load(profiles).fingerprint != a


def test_default_profile_dirs_honour_the_override_and_platform():
    assert preset_catalog.default_profile_dirs({"SNAPSTUDIO_ORCA_PROFILES_DIR": "X"}, "win32") == [Path("X")]
    win = preset_catalog.default_profile_dirs({"ProgramFiles": r"C:\PF"}, "win32")
    assert win[0] == Path(r"C:\PF") / "Snapmaker_Orca" / "resources" / "profiles" / "Snapmaker"
    assert preset_catalog.default_profile_dirs({}, "darwin") == []
    assert preset_catalog.load_default({"SNAPSTUDIO_ORCA_PROFILES_DIR": "does/not/exist"}) is None


def test_real_install_resolves_matte_when_orca_is_present():
    cat = preset_catalog.load_default()
    if cat is None:
        pytest.skip("Snapmaker Orca is not installed on this machine")
    r = cat.evaluate("Snapmaker PLA Matte @U1", "0.4")
    assert r["status"] == PROVEN
    assert cat.evaluate("Snapmaker PLA", "0.4")["status"] == NO_MATCH   # the legacy name
