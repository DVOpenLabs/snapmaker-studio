"""Remembered spool -> installed Orca preset mappings."""
import json

import pytest

from snapstudio_core import material_mapping as mm
from snapstudio_core import preset_catalog
from snapstudio_core.preset_catalog import PROVEN, NEEDS_CONFIRMATION, NO_MATCH


def _preset(folder, name, printers, vendor="Snapmaker", ftype="PLA"):
    (folder / f"{name}.json").write_text(json.dumps({
        "type": "filament", "instantiation": "true", "name": name,
        "compatible_printers": printers, "filament_vendor": [vendor], "filament_type": [ftype]}), "utf-8")


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "Snapmaker"
    fil = root / "filament"
    fil.mkdir(parents=True)
    p4 = ["Snapmaker U1 (0.4 nozzle)"]
    _preset(fil, "Snapmaker PLA Matte @U1", p4)
    _preset(fil, "Snapmaker PLA SnapSpeed @U1", p4)
    _preset(fil, "Generic ASA @U1 0.4 nozzle", p4, "Generic", "ASA")
    return preset_catalog.load(root)


@pytest.fixture
def store(tmp_path):
    return mm.Store(str(tmp_path / "data" / mm.FILE_NAME))


SPOOL = {"id": "12", "vendor": "Yoopai", "material": "PLA", "subtype": "Matte"}


def _proven(catalog, name="Snapmaker PLA Matte @U1"):
    r = catalog.evaluate(name, "0.4")
    assert r["status"] == PROVEN
    return r


def test_nothing_chosen_yet_is_no_match(catalog, store):
    r = mm.resolve(catalog, store, "spoolman", SPOOL, "0.4")
    assert r["status"] == NO_MATCH and r["match_source"] == mm.SOURCE_NONE and r["preset_name"] is None


def test_without_a_catalogue_nothing_is_proven(store):
    r = mm.resolve(None, store, "spoolman", {**SPOOL, "slicer_filament": "Snapmaker PLA Matte @U1"}, "0.4")
    assert r["status"] == NO_MATCH and r["catalog_missing"] is True


def test_spool_mapping_beats_signature_mapping(catalog, store):
    sig = mm.signature("Yoopai", "PLA", "Matte")
    store.put(scope=mm.SCOPE_SIGNATURE, provider="spoolman", sig=sig, origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog), catalog=catalog)
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog, "Snapmaker PLA SnapSpeed @U1"), catalog=catalog)
    r = mm.resolve(catalog, store, "spoolman", SPOOL, "0.4")
    assert (r["status"], r["match_source"], r["base_name"]) == (
        PROVEN, mm.SOURCE_SAVED_SPOOL, "Snapmaker PLA SnapSpeed @U1")
    other = mm.resolve(catalog, store, "spoolman", {**SPOOL, "id": "99"}, "0.4")
    assert (other["match_source"], other["base_name"]) == (mm.SOURCE_SAVED_SIGNATURE, "Snapmaker PLA Matte @U1")


def test_signature_ignores_case_and_spacing_but_not_provider(catalog, store):
    store.put(scope=mm.SCOPE_SIGNATURE, provider="spoolman", sig=mm.signature("Yoopai", "PLA", "Matte"),
              origin=mm.SOURCE_MANUAL, preset=_proven(catalog), catalog=catalog)
    same = {"id": "5", "vendor": "  YOOPAI ", "material": "pla", "subtype": "matte"}
    assert mm.resolve(catalog, store, "spoolman", same, "0.4")["status"] == PROVEN
    assert mm.resolve(catalog, store, "spoolease", same, "0.4")["status"] == NO_MATCH


def test_provider_slicer_filament_is_proven_only_by_the_catalogue(catalog, store):
    ok = mm.resolve(catalog, store, "spoolease", {**SPOOL, "slicer_filament": "Snapmaker PLA Matte @U1"}, "0.4")
    assert (ok["status"], ok["match_source"]) == (PROVEN, mm.SOURCE_EXACT_NAME)
    bogus = mm.resolve(catalog, store, "spoolease", {**SPOOL, "slicer_filament": "Yoopai PLA+"}, "0.4")
    assert bogus["status"] == NO_MATCH and "Yoopai PLA+" in bogus["reason"]
    # a saved mapping outranks the provider's text
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolease", spool_id="12", origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog, "Snapmaker PLA SnapSpeed @U1"), catalog=catalog)
    both = mm.resolve(catalog, store, "spoolease", {**SPOOL, "slicer_filament": "Snapmaker PLA Matte @U1"}, "0.4")
    assert both["base_name"] == "Snapmaker PLA SnapSpeed @U1"


def test_mapping_for_a_preset_that_no_longer_exists_is_not_applied(catalog, store, tmp_path):
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog), catalog=catalog)
    (tmp_path / "Snapmaker" / "filament" / "Snapmaker PLA Matte @U1.json").unlink()
    gone = preset_catalog.load(tmp_path / "Snapmaker")
    r = mm.resolve(gone, store, "spoolman", SPOOL, "0.4")
    assert r["status"] == NO_MATCH and r["preset_name"] is None and r["match_source"] == mm.SOURCE_NONE


def test_mapping_whose_preset_changed_identity_needs_confirmation(catalog, store, tmp_path):
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog), catalog=catalog)
    path = tmp_path / "Snapmaker" / "filament" / "Snapmaker PLA Matte @U1.json"
    doc = json.loads(path.read_text("utf-8"))
    doc["filament_type"] = ["PETG"]              # same name, different preset
    path.write_text(json.dumps(doc), "utf-8")
    changed = preset_catalog.load(tmp_path / "Snapmaker")
    r = mm.resolve(changed, store, "spoolman", SPOOL, "0.4")
    assert r["status"] == NEEDS_CONFIRMATION and r["stale"] is True


def test_only_a_proven_preset_can_be_remembered(catalog, store):
    with pytest.raises(ValueError):
        store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="1", origin=mm.SOURCE_MANUAL,
                  preset=catalog.evaluate("Nope @U1", "0.4"))
    with pytest.raises(ValueError):
        store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="", origin=mm.SOURCE_MANUAL,
                  preset=_proven(catalog))
    with pytest.raises(ValueError):
        store.put(scope=mm.SCOPE_SIGNATURE, provider="spoolman", sig=mm.signature("", "", ""),
                  origin=mm.SOURCE_MANUAL, preset=_proven(catalog))
    with pytest.raises(ValueError):
        store.put(scope="everything", provider="spoolman", spool_id="1", origin=mm.SOURCE_MANUAL,
                  preset=_proven(catalog))


def test_stored_record_holds_names_and_fingerprints_only(catalog, store):
    row = store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL,
                    preset=_proven(catalog), catalog=catalog)
    assert set(row) == {"scope", "provider", "preset_base", "fingerprint", "origin", "profiles_version",
                        "catalog_fingerprint", "confirmed_at", "spool_id"}
    assert row["catalog_fingerprint"] == catalog.fingerprint
    text = open(store.path, encoding="utf-8").read().lower()
    for secret_word in ("key", "token", "password", "secret", "url", "http"):
        assert secret_word not in text


def test_put_replaces_the_same_key_and_remove_deletes(catalog, store):
    kw = dict(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL, catalog=catalog)
    store.put(preset=_proven(catalog), **kw)
    store.put(preset=_proven(catalog, "Snapmaker PLA SnapSpeed @U1"), **kw)
    rows = store.all()
    assert len(rows) == 1 and rows[0]["preset_base"] == "Snapmaker PLA SnapSpeed @U1"
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12") is True
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12") is False
    assert store.all() == []


def test_damaged_or_foreign_file_reads_as_empty_and_is_set_aside_on_write(catalog, store, tmp_path):
    import os
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    open(store.path, "w", encoding="utf-8").write("{not json")
    assert store.all() == []
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="1", origin=mm.SOURCE_MANUAL,
              preset=_proven(catalog), catalog=catalog)
    assert os.path.exists(store.path + ".damaged")
    assert len(store.all()) == 1
    open(store.path, "w", encoding="utf-8").write(json.dumps({"schema": 99, "mappings": [{"preset_base": "x"}]}))
    assert store.all() == []          # a newer schema is not guessed at


def test_missing_file_is_empty(store):
    assert store.all() == []
    assert store.find("spoolman", "1", None) == (None, mm.SOURCE_NONE)


def test_a_spoolease_generic_name_without_the_u1_suffix_is_not_an_installed_preset(catalog, store):
    """Real SpoolEase text is "Generic PLA"; the installed preset is "Generic PLA @U1". Not equal, not guessed."""
    r = mm.resolve(catalog, store, "spoolease", {**SPOOL, "slicer_filament": "Generic ASA"}, "0.4")
    assert r["status"] == NO_MATCH and r["preset_name"] is None
    # the catalogue can still SUGGEST it, as a suggestion that needs confirming
    s = catalog.suggest_generic("ASA", "0.4")
    assert s["status"] == NEEDS_CONFIRMATION and s["base_name"] == "Generic ASA @U1"
