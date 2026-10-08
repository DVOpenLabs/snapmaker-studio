"""Remembered spool -> installed Orca preset mappings."""
import json
import os

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
    # a provider's text names an installed preset but never proves it on its own
    assert (ok["status"], ok["match_source"]) == (NEEDS_CONFIRMATION, mm.SOURCE_EXACT_NAME)
    assert ok["preset_name"] == "Snapmaker PLA Matte @U1"
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
                        "catalog_fingerprint", "confirmed_at", "spool_id", "source", "ref", "proof"}
    # the exact installed record is kept, for Orca's own presets as well as the person's; the pin is opaque
    assert (row["source"], row["proof"]) == ("system", "evidence")
    assert row["ref"].startswith("sys:") and ".json" not in row["ref"] and "Matte" not in row["ref"]
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


def test_remove_with_an_expected_preset_refuses_a_mapping_replaced_since_it_was_shown(catalog, store):
    kw = dict(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL, catalog=catalog)
    store.put(preset=_proven(catalog), **kw)
    store.put(preset=_proven(catalog, "Snapmaker PLA SnapSpeed @U1"), **kw)      # replaced in another window
    with pytest.raises(mm.StaleMapping):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12",
                     expect_preset_base="Snapmaker PLA Matte @U1")
    assert [r["preset_base"] for r in store.all()] == ["Snapmaker PLA SnapSpeed @U1"]
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12",
                        expect_preset_base="Snapmaker PLA SnapSpeed @U1") is True
    assert store.all() == []


def test_remove_leaves_every_unrelated_mapping_alone(catalog, store):
    for sid in ("1", "2", "3"):
        store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=sid, preset=_proven(catalog),
                  origin=mm.SOURCE_MANUAL, catalog=catalog)
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolease", spool_id="2", preset=_proven(catalog),
              origin=mm.SOURCE_MANUAL, catalog=catalog)
    store.put(scope=mm.SCOPE_SIGNATURE, provider="spoolman", sig=mm.signature("Yoopai", "PLA", "Matte"),
              preset=_proven(catalog), origin=mm.SOURCE_MANUAL, catalog=catalog)
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="2") is True
    left = sorted((r["scope"], r["provider"], r.get("spool_id")) for r in store.all())
    assert left == [("signature", "spoolman", None), ("spool", "spoolease", "2"),
                    ("spool", "spoolman", "1"), ("spool", "spoolman", "3")]


def test_concurrent_saves_and_removals_never_lose_or_resurrect_a_mapping(catalog, store):
    import threading
    preset = _proven(catalog)
    for sid in range(40):
        store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=f"old{sid}", preset=preset,
                  origin=mm.SOURCE_MANUAL, catalog=catalog)
    errors = []

    def save(sid):
        try:
            store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=f"new{sid}", preset=preset,
                      origin=mm.SOURCE_MANUAL, catalog=catalog)
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    def forget(sid):
        try:
            store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=f"old{sid}")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(40)] + \
              [threading.Thread(target=forget, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    ids = sorted(r["spool_id"] for r in store.all())
    assert ids == sorted(f"new{i}" for i in range(40))


def test_remove_compares_the_full_saved_identity_not_only_the_base_name(catalog, store):
    kw = dict(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL, catalog=catalog)
    store.put(preset=_proven(catalog), **kw)
    shown = store.all()[0]
    # replaced by the SAME base name but another installed record / fingerprint
    row = dict(_proven(catalog))
    row["ref"] = "another/record.json"
    row["fingerprint"] = "different"
    store.put(preset=row, **kw)
    with pytest.raises(mm.StaleMapping):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12",
                     expect_preset_base=shown["preset_base"], expect_ref=shown["ref"],
                     expect_fingerprint=shown["fingerprint"])
    assert len(store.all()) == 1
    now = store.all()[0]
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12",
                        expect_preset_base=now["preset_base"], expect_ref=now["ref"],
                        expect_fingerprint=now["fingerprint"]) is True


def test_resolve_hands_back_the_stored_row_for_a_later_forget(catalog, store):
    store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", preset=_proven(catalog),
              origin=mm.SOURCE_MANUAL, catalog=catalog)
    out = mm.resolve(catalog, store, "spoolman", SPOOL, "0.4")
    stored = store.all()[0]
    assert out["saved"] == {"preset_base": stored["preset_base"], "ref": stored["ref"],
                            "fingerprint": stored["fingerprint"]}


def test_two_processes_cannot_interleave_a_save_and_a_forget(catalog, store, tmp_path):
    """A second PYTHON PROCESS (a second running Studio) writes while this one does: nothing is lost."""
    import subprocess, sys, textwrap
    preset = _proven(catalog)
    for i in range(30):
        store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=f"old{i}", preset=preset,
                  origin=mm.SOURCE_MANUAL, catalog=catalog)
    script = textwrap.dedent("""
        import sys, json
        from snapstudio_core import material_mapping as mm
        path, = sys.argv[1:]
        s = mm.Store(path)
        preset = json.loads(sys.stdin.read())
        for i in range(30):
            s.put(scope="spool", provider="spoolman", spool_id=f"new{i}", preset=preset, origin="manual")
    """)
    child = subprocess.Popen([sys.executable, "-c", script, store.path], stdin=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    child.stdin.write(json.dumps(preset)); child.stdin.close()
    for i in range(30):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=f"old{i}")
    assert child.wait(timeout=60) == 0, child.stderr.read()
    assert sorted(r["spool_id"] for r in store.all()) == sorted(f"new{i}" for i in range(30))


def test_exclusive_can_be_nested_without_waiting_for_itself(store):
    import threading
    done = []

    def run():
        with mm._exclusive(store.path):
            with mm._exclusive(store.path):
                done.append(True)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=10)
    assert done == [True] and not t.is_alive()


def test_an_expected_null_identity_is_compared_not_skipped(catalog, store):
    kw = dict(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", origin=mm.SOURCE_MANUAL, catalog=catalog)
    row = dict(_proven(catalog)); row["ref"] = None
    store.put(preset=row, **kw)
    assert store.all()[0]["ref"] is None
    row2 = dict(_proven(catalog)); row2["ref"] = "now/a/real/ref.json"
    store.put(preset=row2, **kw)                                   # replaced meanwhile
    with pytest.raises(mm.StaleMapping):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="12", expect_ref=None)
    assert len(store.all()) == 1


# ---- unreadable is not corrupt (#89) ------------------------------------------------------------

import builtins
import errno as _errno


def _seed(store, n=5):
    rows = [{"scope": "spool", "provider": "spoolman", "spool_id": str(i), "preset_base": "P", "ref": None,
             "fingerprint": None} for i in range(n)]
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    with open(store.path, "w", encoding="utf-8") as fh:
        json.dump({"schema": mm.SCHEMA, "mappings": rows}, fh)
    with open(store.path, "rb") as fh:
        return fh.read()


class _Flaky:
    """Make the first `fail` opens of the mapping file (for reading) raise `exc`; count every attempt."""

    def __init__(self, monkeypatch, path, exc, fail):
        self.attempts, self.fail, self.exc = 0, fail, exc
        real = builtins.open

        def opener(file, *a, **k):
            if str(file) == path and (not a or "r" in str(a[0])):
                self.attempts += 1
                if self.attempts <= self.fail:
                    raise exc
            return real(file, *a, **k)
        monkeypatch.setattr(builtins, "open", opener)
        monkeypatch.setattr(mm.time, "sleep", lambda s: None)       # the bounded back-off, without waiting


_PRESET = {"status": "proven", "base_name": "P", "fingerprint": None, "ref": None, "source": None}
_SHARING = PermissionError(_errno.EACCES, "The process cannot access the file because it is being used by another process")


def _put(store, sid="new"):
    return store.put(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id=sid, preset=dict(_PRESET), origin=mm.SOURCE_MANUAL)


def test_a_transient_read_failure_is_retried_and_a_save_keeps_every_other_mapping(store, monkeypatch):
    _seed(store)
    flaky = _Flaky(monkeypatch, store.path, _SHARING, fail=2)
    _put(store)
    assert flaky.attempts == 3
    assert sorted(r["spool_id"] for r in store.all()) == ["0", "1", "2", "3", "4", "new"]
    assert not os.path.exists(store.path + ".damaged")


def test_a_transient_read_failure_is_retried_and_a_forget_removes_only_the_requested_mapping(store, monkeypatch):
    _seed(store)
    flaky = _Flaky(monkeypatch, store.path, _SHARING, fail=3)
    assert store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="2") is True
    assert flaky.attempts == 4
    assert sorted(r["spool_id"] for r in store.all()) == ["0", "1", "3", "4"]
    assert not os.path.exists(store.path + ".damaged")


def test_a_persistent_access_failure_fails_the_save_and_leaves_the_live_file_alone(store, monkeypatch):
    before = _seed(store)
    flaky = _Flaky(monkeypatch, store.path, _SHARING, fail=10 ** 6)
    with pytest.raises(mm.MappingFileUnavailable) as err:
        _put(store)
    assert flaky.attempts == mm._READ_ATTEMPTS                       # bounded
    assert "in use by another program" in str(err.value) and "Nothing was changed" in str(err.value)
    monkeypatch.undo()
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


def test_a_persistent_access_failure_fails_the_forget_and_leaves_the_live_file_alone(store, monkeypatch):
    before = _seed(store)
    _Flaky(monkeypatch, store.path, _SHARING, fail=10 ** 6)
    with pytest.raises(mm.MappingFileUnavailable):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="1")
    monkeypatch.undo()
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


def test_a_permanent_read_error_is_not_retried_and_is_not_corruption(store, monkeypatch):
    before = _seed(store)
    flaky = _Flaky(monkeypatch, store.path, OSError(_errno.EIO, "input/output error"), fail=10 ** 6)
    with pytest.raises(mm.MappingFileUnavailable) as err:
        _put(store)
    assert flaky.attempts == 1                                       # permanent: no retry
    assert "in use by another program" not in str(err.value)         # and no false promise that waiting helps
    monkeypatch.undo()
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


def test_a_folder_where_the_file_should_be_is_unreadable_not_damaged(store):
    os.makedirs(store.path)                                          # a directory named like the mapping file
    slept = []
    import snapstudio_core.material_mapping as _mm
    original = _mm.time.sleep
    _mm.time.sleep = lambda s: slept.append(s)
    try:
        with pytest.raises(mm.MappingFileUnavailable) as err:
            _put(store)
    finally:
        _mm.time.sleep = original
    assert slept == []                                               # permanent even where Windows says "access denied"
    assert "in use by another program" not in str(err.value) and "Try again" not in str(err.value)
    assert os.path.isdir(store.path) and not os.path.exists(store.path + ".damaged")


def test_reading_only_never_changes_anything_when_the_file_cannot_be_read(store, monkeypatch):
    before = _seed(store)
    _Flaky(monkeypatch, store.path, _SHARING, fail=10 ** 6)
    assert store.all() == [] and store.find("spoolman", "1", None)[0] is None
    monkeypatch.undo()
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe\x00bad bytes", b'{"schema": "other", "mappings": []}', b"[]", b""])
def test_content_that_was_read_and_is_invalid_is_still_confirmed_corruption(store, content):
    os.makedirs(os.path.dirname(store.path))
    with open(store.path, "wb") as fh:
        fh.write(content)
    assert store.all() == []
    _put(store)
    assert os.path.exists(store.path + ".damaged")
    with open(store.path + ".damaged", "rb") as fh:
        assert fh.read() == content                                   # set aside intact, not lost
    assert [r["spool_id"] for r in store.all()] == ["new"]


def test_which_errors_count_as_transient():
    assert mm._is_transient(PermissionError(13, "x"))
    assert mm._is_transient(OSError(_errno.EBUSY, "busy"))
    err = OSError(0, "sharing violation"); err.winerror = 32
    assert mm._is_transient(err)
    for permanent in (IsADirectoryError(21, "dir"), NotADirectoryError(20, "nd"), FileNotFoundError(2, "gone"), OSError(_errno.EIO, "io")):
        assert not mm._is_transient(permanent)


def test_a_file_that_vanishes_mid_read_is_a_failed_read_not_a_missing_file(store, monkeypatch):
    """ENOENT while reading (a cloud or network filesystem) must not read as 'no file', or a save would overwrite it."""
    before = _seed(store)
    real = builtins.open

    class Vanishing:
        def __init__(self, fh): self._fh = fh
        def __enter__(self): self._fh.__enter__(); return self
        def __exit__(self, *a): return self._fh.__exit__(*a)
        def read(self, *a): raise FileNotFoundError(_errno.ENOENT, "gone mid-read")
        def __getattr__(self, n): return getattr(self._fh, n)

    def opener(file, *a, **k):
        fh = real(file, *a, **k)
        return Vanishing(fh) if str(file) == store.path and (not a or "r" in str(a[0])) else fh
    monkeypatch.setattr(builtins, "open", opener)
    monkeypatch.setattr(mm.time, "sleep", lambda s: None)
    with pytest.raises(mm.MappingFileUnavailable) as err:
        _put(store)
    assert "Try again" not in str(err.value)                          # permanent: waiting does not help
    monkeypatch.undo()
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


def test_a_lock_file_that_cannot_be_opened_is_unavailable_not_a_crash(store):
    before = _seed(store)
    os.makedirs(os.path.join(os.path.dirname(store.path), ".material-mappings.lock"))     # a folder where the lock file goes
    with pytest.raises(mm.MappingFileUnavailable):
        _put(store)
    with pytest.raises(mm.MappingFileUnavailable):
        store.remove(scope=mm.SCOPE_SPOOL, provider="spoolman", spool_id="1")
    with open(store.path, "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(store.path + ".damaged")


def test_only_a_transient_failure_says_that_trying_again_may_help():
    assert "Try again in a moment" in str(mm._unavailable(PermissionError(13, "x")))
    assert "Try again" not in str(mm._unavailable(OSError(_errno.EIO, "io")))
    assert "Nothing was changed" in str(mm._unavailable(OSError(_errno.EIO, "io")))


def test_looking_up_mappings_under_a_persistent_failure_is_one_attempt_each_and_never_waits(store, monkeypatch):
    _seed(store)
    flaky = _Flaky(monkeypatch, store.path, _SHARING, fail=10 ** 6)
    slept = []
    monkeypatch.setattr(mm.time, "sleep", lambda s: slept.append(s))
    for i in range(20):
        assert store.find("spoolman", str(i), None)[0] is None
    assert flaky.attempts == 20 and slept == []                      # a lookup per spool must stay cheap
