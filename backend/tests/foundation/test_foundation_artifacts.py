"""Byte identity, snapshots, derivations, pin registry, eviction and sweep."""
import hashlib
import json
import os

import pytest

from snapstudio_core.foundation import artifacts as a
from snapstudio_core.foundation.decode import Decoded

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = "2026-01-10T00:00:00Z"
NOW_EPOCH = 1768003200.0   # 2026-01-10T00:00:00Z
DAY = 86400


def codes(diags):
    return {d.code for d in diags}


def ls(directory):
    """Snapshot directory entries, ignoring the persistent admission lock file."""
    return [n for n in os.listdir(directory) if not n.startswith(".admission")]


def load(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path, data: bytes):
    path.write_bytes(data)
    return str(path)


def age(path, days):
    t = NOW_EPOCH - days * DAY
    os.utime(path, (t, t))


def snap(path, snapdir, **kw):
    return a.snapshot(str(path), kw.pop("role", "original"), snapshot_dir=str(snapdir), **kw)


def aid(data: bytes) -> str:
    return a.make_artifact_id(sha(data), len(data))


# -- artifact ref -------------------------------------------------------------
def test_artifact_ref_fixture_round_trips():
    raw = load("artifact_ref")
    dec = a.ArtifactRef.from_dict(raw)
    assert dec.valid_for_evaluation and dec.value.to_dict() == raw
    assert dec.value.artifact_id == f"sha256:{'a' * 64}:1234"


def test_artifact_id_mismatch_is_an_error():
    raw = load("artifact_ref")
    raw["artifact_id"] = f"sha256:{'a' * 64}:999"
    dec = a.ArtifactRef.from_dict(raw)
    assert dec.value is None and "artifact_id_mismatch" in codes(dec.diagnostics)


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r["bytes"].update(sha256="xyz"), "wrong_type"),
    (lambda r: r["bytes"].update(size_bytes=-1), "out_of_range"),
    (lambda r: r.update(role="mystery"), "bad_enum"),
    (lambda r: r.pop("bytes"), "missing_field"),
])
def test_artifact_ref_bad_documents_rejected(mutate, code):
    raw = load("artifact_ref")
    mutate(raw)
    dec = a.ArtifactRef.from_dict(raw)
    assert dec.value is None and code in codes(dec.diagnostics)


def test_artifact_create_validation():
    for args in [("zz", 1, "original", "n"), ("a" * 64, -1, "original", "n"), ("a" * 64, True, "original", "n"),
                 ("a" * 64, 1, "nope", "n")]:
        with pytest.raises(ValueError):
            a.ArtifactRef.create(*args)


def test_unknown_schema_artifact_preserved_opaque():
    raw = load("unknown_schema_version")
    dec = a.ArtifactRef.from_dict(raw)
    assert dec.value is None and dec.raw == raw


# -- same_bytes ---------------------------------------------------------------
def test_same_size_replacement_is_detected(tmp_path):
    src = write(tmp_path / "m.stl", b"AAAA" * 100)
    ref = snap(src, tmp_path / "snaps").value
    # Same length, same (restored) mtime: only hashing can tell.
    st = os.stat(src)
    write(tmp_path / "m.stl", b"BBBB" * 100)
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.path.getsize(src) == ref.bytes.size_bytes
    assert a.same_bytes(ref, src) == a.CHANGED
    # The private copy is untouched, so analysis of the copy stays on the original bytes.
    copy = a.snapshot_copy_path(ref, str(tmp_path / "snaps"))
    assert copy and a.same_bytes(ref, copy) == a.SAME


def test_same_bytes_states(tmp_path):
    src = write(tmp_path / "m.stl", b"x" * 10)
    ref = snap(src, tmp_path / "s").value
    assert a.same_bytes(ref, src) == a.SAME
    assert a.same_bytes(ref, str(tmp_path / "gone")) == a.MISSING
    assert a.same_bytes(ref, str(tmp_path)) == a.UNREADABLE
    assert a.same_bytes(ref, None) == a.UNVERIFIED and a.same_bytes(ref, "") == a.UNVERIFIED
    assert a.same_bytes("not a ref", src) == a.UNVERIFIED
    write(tmp_path / "m.stl", b"x" * 11)
    assert a.same_bytes(ref, src) == a.CHANGED


# -- snapshot -----------------------------------------------------------------
def test_snapshot_copies_hashes_and_records_locator(tmp_path):
    data = b"hello world"
    src = write(tmp_path / "m.3mf", data)
    dec = snap(src, tmp_path / "s", role="prepared")
    ref = dec.value
    assert dec.valid_for_evaluation and dec.diagnostics == []
    assert ref.artifact_id == aid(data) and ref.role == "prepared" and ref.name == "m.3mf"
    assert ref.locator["path"] == os.path.abspath(src)
    copy = a.snapshot_copy_path(ref, str(tmp_path / "s"))
    assert open(copy, "rb").read() == data
    assert not [n for n in os.listdir(tmp_path / "s") if n.endswith(".tmp")]


def test_generated_role_supported(tmp_path):
    src = write(tmp_path / "g.png", b"png")
    assert snap(src, tmp_path / "s", role="generated").value.role == "generated"
    with pytest.raises(ValueError):
        snap(src, tmp_path / "s", role="nonsense")


def test_snapshot_missing_and_directory_do_not_raise(tmp_path):
    assert codes(snap(tmp_path / "nope", tmp_path / "s").diagnostics) == {"file_missing"}
    assert codes(snap(tmp_path, tmp_path / "s").diagnostics) == {"not_a_file"}


def test_identical_bytes_dedupe_to_one_snapshot_but_independent_refs(tmp_path):
    one = write(tmp_path / "one.stl", b"same")
    two = write(tmp_path / "two.stl", b"same")
    r1, r2 = snap(one, tmp_path / "s").value, snap(two, tmp_path / "s", role="prepared").value
    assert r1.artifact_id == r2.artifact_id and r1.role != r2.role and r1.name != r2.name
    assert len(ls(tmp_path / "s")) == 1


def test_over_cap_is_hashed_in_place_with_small_injected_cap(tmp_path):
    data = b"z" * 64
    src = write(tmp_path / "big.stl", data)
    dec = snap(src, tmp_path / "s", max_copy_bytes=32)
    assert dec.valid_for_evaluation and codes(dec.diagnostics) == {"not_snapshotted"}
    assert dec.value.artifact_id == aid(data)
    assert a.snapshot_copy_path(dec.value, str(tmp_path / "s")) is None
    assert not (tmp_path / "s").exists() or ls(tmp_path / "s") == []
    # No copy -> analysis must re-verify against the live file every time.
    assert a.same_bytes(dec.value, src) == a.SAME
    write(tmp_path / "big.stl", b"y" * 64)
    assert a.same_bytes(dec.value, src) == a.CHANGED


def test_at_cap_is_still_copied(tmp_path):
    src = write(tmp_path / "m", b"q" * 32)
    dec = snap(src, tmp_path / "s", max_copy_bytes=32)
    assert dec.diagnostics == [] and a.snapshot_copy_path(dec.value, str(tmp_path / "s"))


def test_default_cap_is_512_mib():
    assert a.DEFAULT_MAX_COPY_BYTES == 512 * 1024 * 1024


def test_source_changed_during_copy_flagged(tmp_path, monkeypatch):
    src = write(tmp_path / "m", b"a" * 10)
    real = a._hash_file

    def racing(path):
        out = real(path)
        if path.endswith(".tmp"):          # the source is touched while the copy is being hashed
            write(tmp_path / "m", b"b" * 10)
            os.utime(src, ns=(1, 2))
        return out

    monkeypatch.setattr(a, "_hash_file", racing)
    dec = snap(src, tmp_path / "s")
    assert "source_changed_during_copy" in codes(dec.diagnostics)
    assert dec.value.artifact_id == aid(b"a" * 10)   # identity is the copy's bytes


# -- quota, eviction, pins, sweep ---------------------------------------------
def seed(snapdir, contents, days_old=30):
    snapdir.mkdir(exist_ok=True)
    ids = []
    for c in contents:
        p = snapdir / sha(c)
        p.write_bytes(c)
        age(p, days_old)
        ids.append(aid(c))
    return ids


def test_quota_exceeded_without_registry_refuses_and_deletes_nothing(tmp_path):
    sd = tmp_path / "s"
    seed(sd, [b"1" * 100, b"2" * 100])
    src = write(tmp_path / "new", b"3" * 100)
    from snapstudio_core.foundation import store
    root = str(tmp_path / "data")
    with open(os.path.join(store.store_dir(root), "snapshot_pins.json"), "wb") as fh:
        fh.write(b"\xff{garbage")                   # the persisted registry exists but cannot be read
    dec = snap(src, sd, quota_bytes=250, data_dir=root)
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_quota_exceeded"}
    assert len(ls(sd)) == 2


def test_quota_eviction_removes_oldest_unpinned_first(tmp_path):
    sd = tmp_path / "s"
    old, mid, new = b"o" * 100, b"m" * 100, b"n" * 100
    seed(sd, [old], days_old=40)
    seed(sd, [mid], days_old=20)
    seed(sd, [new], days_old=5)
    reg = a.PinRegistry()
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=300, registry=reg, now=NOW)
    assert dec.valid_for_evaluation
    names = set(ls(sd))
    assert sha(old) not in names                   # oldest went
    assert sha(mid) in names and sha(new) in names and sha(b"i" * 100) in names


def test_quota_eviction_is_pin_aware(tmp_path):
    sd = tmp_path / "s"
    pinned_blob, free_blob = b"p" * 100, b"f" * 100
    ids = seed(sd, [pinned_blob, free_blob], days_old=40)
    age(sd / sha(pinned_blob), 90)                 # the pinned one is also the oldest
    reg = a.PinRegistry()
    reg.pin(ids[0], "checkpoint", "cp-1")
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=250, registry=reg, now=NOW)
    assert dec.valid_for_evaluation
    names = set(ls(sd))
    assert sha(pinned_blob) in names and sha(free_blob) not in names


def test_quota_refuses_when_everything_is_pinned_or_inside_grace(tmp_path):
    sd = tmp_path / "s"
    ids = seed(sd, [b"a" * 100], days_old=40)
    fresh = seed(sd, [b"b" * 100], days_old=0.1)
    reg = a.PinRegistry()
    reg.pin(ids[0], "passport", "pp")
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=250, registry=reg, now=NOW)
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_quota_exceeded"}
    assert len(ls(sd)) == 2 and fresh


def test_quota_with_unreadable_registry_decoded_deletes_nothing(tmp_path):
    sd = tmp_path / "s"
    seed(sd, [b"a" * 100, b"b" * 100])
    bad = a.PinRegistry.from_dict({"schema_version": "snapshot_pins/99"})
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=250, registry=bad, now=NOW)
    assert dec.value is None and len(ls(sd)) == 2


def test_sweep_skips_entirely_when_registry_unreadable(tmp_path):
    sd = tmp_path / "s"
    seed(sd, [b"a" * 10, b"b" * 10], days_old=60)
    for reg in (None, a.PinRegistry.from_dict("{broken"), a.PinRegistry.from_dict({"schema_version": "x"}),
                "registry"):
        res = a.sweep_snapshots(str(sd), reg, now=NOW)
        assert res == {"deleted": [], "skipped_reason": "pin_registry_unreadable"}
    assert len(ls(sd)) == 2


def test_sweep_deletes_unpinned_old_keeps_pinned_and_grace(tmp_path):
    sd = tmp_path / "s"
    passport, workspace, orphan, fresh = b"1" * 5, b"2" * 5, b"3" * 5, b"4" * 5
    ids = seed(sd, [passport, workspace, orphan], days_old=60)
    seed(sd, [fresh], days_old=0.5)                # inside the 24 h grace period
    reg = a.PinRegistry()
    reg.pin(ids[0], "passport", "p-1")
    reg.pin(ids[1], "workspace", "active")
    res = a.sweep_snapshots(str(sd), reg, now=NOW)
    assert res["skipped_reason"] is None and res["deleted"] == [sha(orphan)]
    assert set(ls(sd)) == {sha(passport), sha(workspace), sha(fresh)}


def test_sweep_dry_run_deletes_nothing(tmp_path):
    sd = tmp_path / "s"
    seed(sd, [b"a" * 5], days_old=60)
    res = a.sweep_snapshots(str(sd), a.PinRegistry(), now=NOW, dry_run=True)
    assert len(res["deleted"]) == 1 and len(ls(sd)) == 1


def test_sweep_grace_boundary_and_custom_grace(tmp_path):
    sd = tmp_path / "s"
    seed(sd, [b"a" * 5], days_old=2)
    reg = a.PinRegistry()
    assert a.sweep_snapshots(str(sd), reg, now=NOW, grace_s=3 * DAY)["deleted"] == []
    assert len(a.sweep_snapshots(str(sd), reg, now=NOW, grace_s=1 * DAY)["deleted"]) == 1


def test_sweep_ignores_non_snapshot_names_and_missing_dir(tmp_path):
    sd = tmp_path / "s"
    sd.mkdir()
    (sd / "notes.txt").write_text("x")
    (sd / ".abc.tmp").write_text("x")
    age(sd / "notes.txt", 90)
    assert a.sweep_snapshots(str(sd), a.PinRegistry(), now=NOW)["deleted"] == []
    assert a.sweep_snapshots(str(tmp_path / "none"), a.PinRegistry(), now=NOW)["deleted"] == []


def test_pin_registry_basics_and_validation():
    reg = a.PinRegistry()
    i = aid(b"x")
    reg.pin(i, "checkpoint", "c1")
    reg.pin(i, "checkpoint", "c1")                 # idempotent
    reg.pin(i, "workspace", "w")
    assert reg.holders(i) == [("checkpoint", "c1"), ("workspace", "w")] and reg.is_pinned(i)
    assert reg.unpin(i, "checkpoint", "c1") and not reg.unpin(i, "checkpoint", "c1")
    assert reg.pinned_hashes() == {sha(b"x")}
    reg.unpin(i, "workspace", "w")
    assert not reg.is_pinned(i)
    for bad in [("nope", "checkpoint", "c"), (i, "bogus", "c"), (i, "checkpoint", ""), ("", "checkpoint", "c")]:
        with pytest.raises(ValueError):
            reg.pin(*bad)


def test_pin_registry_round_trip_and_bad_entries():
    reg = a.PinRegistry()
    reg.pin(aid(b"x"), "assembly", "as-1")
    raw = reg.to_dict()
    back = a.PinRegistry.from_dict(raw)
    assert back.valid_for_evaluation and back.value.to_dict() == raw
    raw["pins"][0]["artifact_id"] = "bad"
    assert a.PinRegistry.from_dict(raw).value is None


def test_module_level_pin_helpers_use_given_registry():
    reg = a.PinRegistry()
    i = aid(b"y")
    a.pin_in_memory(i, "calibration", "k", registry=reg)
    assert reg.is_pinned(i) and a.unpin_in_memory(i, "calibration", "k", registry=reg)
    assert a.default_registry() is a.default_registry()


# -- derivation ---------------------------------------------------------------
def test_derivation_fixture_round_trips_imported_and_not():
    raw = load("derivation")
    for imported in (False, True):
        dec = a.Derivation.from_dict(raw, imported=imported)
        assert dec.valid_for_evaluation and dec.value.to_dict() == raw
        assert dec.value.witness == "declared"


def test_multi_input_derivation_id_ignores_input_order():
    ins = [{"kind": "image", "ref": "sha256:" + "1" * 64 + ":3"}, {"kind": "settings", "ref": "preset:a"},
           {"kind": "lut", "ref": "lut:1"}]
    d1 = a.Derivation.create("out", ins, {"tool": "t", "version": "1"})
    d2 = a.Derivation.create("out", list(reversed(ins)), {"tool": "t", "version": "1"})
    d3 = a.Derivation.create("out", ins[:2], {"tool": "t", "version": "1"})
    assert d1.derivation_id == d2.derivation_id != d3.derivation_id
    assert len(d1.inputs) == 3 and d1.witness == "local"


def test_identical_bytes_at_different_derivation_stages_get_distinct_derivations():
    out = aid(b"same output bytes")
    first = a.Derivation.create(out, [{"kind": "artifact", "ref": aid(b"orig")}], {"tool": "prepare"})
    second = a.Derivation.create(out, [{"kind": "artifact", "ref": aid(b"intermediate")}], {"tool": "prepare"})
    assert first.output == second.output
    assert first.derivation_id != second.derivation_id


def test_imported_local_witness_is_downgraded_to_declared():
    local = a.Derivation.create("out", [{"kind": "artifact", "ref": "r"}], {"tool": "t"})
    assert local.witness == "local"
    dec = a.Derivation.from_dict(local.to_dict(), imported=True)
    assert dec.value.witness == "declared"                                   # false parentage never "local"
    assert {"witness_downgraded", "declared_by_missing"} <= codes(dec.diagnostics)
    same_process = a.Derivation.from_dict(local.to_dict())
    assert same_process.value.witness == "local" and same_process.diagnostics == []


def test_imported_derivation_id_is_recomputed_visibly_not_trusted():
    # Known issue: the id of an imported document used to be silently replaced.
    local = a.Derivation.create("out", [{"kind": "artifact", "ref": "r"}], {"tool": "t"})
    raw = local.to_dict()
    dec = a.Derivation.from_dict(raw, imported=True)
    assert dec.value.derivation_id != raw["derivation_id"]       # witness changed -> new content id
    assert "derivation_id_recomputed" in codes(dec.diagnostics)
    forged = load("derivation")
    forged["derivation_id"] = "drv:forged"
    imported = a.Derivation.from_dict(forged, imported=True)
    assert imported.valid_for_evaluation and imported.value.derivation_id == load("derivation")["derivation_id"]
    assert "derivation_id_recomputed" in codes(imported.diagnostics)
    strict = a.Derivation.from_dict(forged)
    assert strict.value is None and "derivation_id_mismatch" in codes(strict.diagnostics)


def test_derivation_create_validation():
    ok = [{"kind": "artifact", "ref": "r"}]
    with pytest.raises(ValueError):
        a.Derivation.create("o", ok, {"tool": "t"}, witness="bogus")
    with pytest.raises(ValueError):
        a.Derivation.create("o", ok, {"tool": "t"}, witness="local", declared_by="x")
    with pytest.raises(ValueError):
        a.Derivation.create("o", ok, {})
    with pytest.raises(ValueError):
        a.Derivation.create("o", [{"kind": "weird", "ref": "r"}], {"tool": "t"})
    with pytest.raises(ValueError):
        a.Derivation.create("o", [{"kind": "image", "ref": ""}], {"tool": "t"})


def test_derivation_decode_errors():
    raw = load("derivation")
    del raw["producer"]
    dec = a.Derivation.from_dict(raw)
    assert dec.value is None and "missing_field" in codes(dec.diagnostics)
    assert isinstance(dec, Decoded)
    assert a.Derivation.from_dict(load("unknown_schema_version"), imported=True).value is None


# -- persisted pins, locks, bounded copy (R2, R3, R5) ---------------------------
import threading
import time

from snapstudio_core.foundation import store


def _old_snap(sd, data, days=3):
    os.makedirs(sd, exist_ok=True)
    p = sd / sha(data)
    p.write_bytes(data)
    age(p, days)
    return p


def test_canonical_pin_persists_and_protects_across_restart_from_sweep_and_eviction(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    keep, drop = b"k" * 100, b"d" * 100
    pk, pd = _old_snap(sd, keep), _old_snap(sd, drop)
    a.pin(aid(keep), "checkpoint", "cp1", data_dir=root)
    assert a.unpin(aid(b"nothing"), "checkpoint", "cp1", data_dir=root) is False
    # restart: nothing in memory is used, the file alone decides
    assert a.load_pin_registry(root).value.holders(aid(keep)) == [("checkpoint", "cp1")]
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=250, now=NOW, data_dir=root)       # registry=None -> persisted
    assert dec.valid_for_evaluation and pk.exists() and not pd.exists()
    swept = a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW)
    assert sha(keep) not in swept["deleted"] and pk.exists()
    assert a.unpin(aid(keep), "checkpoint", "cp1", data_dir=root) is True
    assert a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW)["deleted"] == [sha(keep)]


def test_snapshot_pinned_only_in_persisted_file_survives_eviction_when_registry_none(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    only = b"p" * 100
    p = _old_snap(sd, only, 90)
    doc = {"pins": [{"artifact_id": aid(only), "holder_kind": "passport", "holder_id": "x",
                     "pinned_at": "2026-01-01T00:00:00Z"}]}
    store.write_json("snapshot_pins", doc, expected_revision=0, schema="snapshot_pins", version=1, data_dir=root)
    src = write(tmp_path / "in", b"i" * 100)
    dec = snap(src, sd, quota_bytes=150, now=NOW, data_dir=root)
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_quota_exceeded"} and p.exists()


def test_in_memory_helpers_are_named_as_such_and_do_not_persist(tmp_path):
    root = str(tmp_path / "data")
    reg = a.PinRegistry()
    a.pin_in_memory(aid(b"z"), "workspace", "w", registry=reg)
    assert reg.is_pinned(aid(b"z")) and a.unpin_in_memory(aid(b"z"), "workspace", "w", registry=reg)
    assert a.load_pin_registry(root).value.pinned_hashes() == set()


def _run_blocked_pin(monkeypatch, root, artifact_id, trigger):
    """Run trigger() with a hook that, while the registry lock is held, starts a pin and checks it waits."""
    state = {}

    def pinner():
        a.pin(artifact_id, "checkpoint", "late", data_dir=root)

    def hook():
        t = threading.Thread(target=pinner)
        t.start()
        t.join(0.5)
        state["finished_early"] = not t.is_alive()
        state["thread"] = t

    monkeypatch.setattr(a, "_after_registry_read", hook)
    out = trigger()
    state["thread"].join(10)
    return out, state


def test_pin_waits_for_a_running_sweep_instead_of_slipping_in(tmp_path, monkeypatch):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"s" * 100
    p = _old_snap(sd, blob)
    out, state = _run_blocked_pin(monkeypatch, root, aid(blob),
                                  lambda: a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW))
    assert state["finished_early"] is False                       # the pin was held back by the sweep lock
    assert out["deleted"] == [sha(blob)] and not p.exists()
    assert a.load_pin_registry(root).value.holders(aid(blob)) == [("checkpoint", "late")]   # and then landed


def test_pin_waits_for_running_quota_eviction(tmp_path, monkeypatch):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"e" * 100
    p = _old_snap(sd, blob)
    src = write(tmp_path / "in", b"i" * 100)
    out, state = _run_blocked_pin(monkeypatch, root, aid(blob),
                                  lambda: snap(src, sd, quota_bytes=150, now=NOW, data_dir=root))
    assert state["finished_early"] is False and out.valid_for_evaluation and not p.exists()
    assert a.load_pin_registry(root).value.holders(aid(blob)) == [("checkpoint", "late")]


def test_pin_made_before_sweep_wins(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"w" * 100
    p = _old_snap(sd, blob)
    a.pin(aid(blob), "workspace", "w", data_dir=root)
    assert a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW)["deleted"] == [] and p.exists()


def _grow_source(monkeypatch):
    monkeypatch.setattr(a, "_CHUNK", 10)

    def grow(path, total):
        if total == 10:
            with open(path, "ab") as fh:
                fh.write(b"x" * 200)

    monkeypatch.setattr(a, "_on_copy_chunk", grow)


def test_growing_source_is_aborted_while_copying_and_partial_removed(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    src = write(tmp_path / "grow", b"g" * 40)
    _grow_source(monkeypatch)
    dec = snap(src, sd, max_copy_bytes=60, registry=a.PinRegistry())
    assert dec.value is not None and "not_snapshotted" in codes(dec.diagnostics)
    assert dec.value.bytes.size_bytes == 240                          # hashed in place, never copied
    assert ls(sd) == []                                       # no partial copy, no tmp, no lock left


def test_growing_source_cannot_exceed_the_quota(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    src = write(tmp_path / "grow", b"g" * 40)
    _grow_source(monkeypatch)
    dec = snap(src, sd, quota_bytes=100, registry=a.PinRegistry())
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_quota_exceeded"} and ls(sd) == []


def test_concurrent_snapshots_cannot_both_be_admitted_past_the_quota(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    srcs = [write(tmp_path / f"in{i}", bytes([65 + i]) * 100) for i in range(2)]
    gate = threading.Event()
    first = threading.Event()

    def after_check():
        if not first.is_set():
            first.set()
            gate.wait(0.6)            # hold admission long enough for the second snapshot to arrive

    monkeypatch.setattr(a, "_after_quota_check", after_check)
    results = []

    def go(src):
        results.append(snap(src, sd, quota_bytes=150, registry=a.PinRegistry()))

    threads = [threading.Thread(target=go, args=(s_,)) for s_ in srcs]
    threads[0].start()
    first.wait(5)
    threads[1].start()
    [t.join(20) for t in threads]
    ok = [r for r in results if r.value is not None]
    refused = [r for r in results if r.value is None]
    assert len(ok) == 1 and len(refused) == 1 and codes(refused[0].diagnostics) == {"snapshot_quota_exceeded"}
    assert sum(os.path.getsize(sd / n) for n in os.listdir(sd) if not n.startswith(".")) <= 150


# -- stale supplied registry is additive only (F2) ------------------------------
def test_quota_eviction_ignores_a_stale_empty_supplied_registry_when_the_persisted_one_pins(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"p" * 100
    p = _old_snap(sd, blob)
    stale = a.PinRegistry()                                           # captured before the pin landed
    a.pin(aid(blob), "checkpoint", "cp-late", data_dir=root)          # a concurrent canonical pin
    src = write(tmp_path / "in", b"n" * 100)
    dec = snap(src, sd, quota_bytes=150, registry=stale, now=NOW, data_dir=root)
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_quota_exceeded"}
    assert p.exists()


def test_sweep_ignores_a_stale_empty_supplied_registry_when_the_persisted_one_pins(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"q" * 100
    p = _old_snap(sd, blob)
    stale = a.PinRegistry()
    a.pin(aid(blob), "checkpoint", "cp-late", data_dir=root)
    assert a.sweep_snapshots(str(sd), stale, now=NOW, data_dir=root)["deleted"] == []
    assert p.exists()


def test_supplied_registry_only_adds_protection(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    mem, persisted, orphan = b"m" * 10, b"s" * 10, b"o" * 10
    pm, ps, po = _old_snap(sd, mem), _old_snap(sd, persisted), _old_snap(sd, orphan)
    a.pin(aid(persisted), "checkpoint", "cp", data_dir=root)
    extra = a.PinRegistry()
    extra.pin(aid(mem), "workspace", "w")
    res = a.sweep_snapshots(str(sd), extra, now=NOW, data_dir=root)
    assert res["deleted"] == [sha(orphan)] and pm.exists() and ps.exists() and not po.exists()


def test_stale_supplied_registry_with_unreadable_persisted_registry_deletes_nothing(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    p = _old_snap(sd, b"u" * 10)
    os.makedirs(os.path.join(root, "store"), exist_ok=True)
    with open(os.path.join(root, "store", "snapshot_pins.json"), "wb") as fh:
        fh.write(b"\xff{garbage")
    res = a.sweep_snapshots(str(sd), a.PinRegistry(), now=NOW, data_dir=root)
    assert res == {"deleted": [], "skipped_reason": "pin_registry_unreadable"} and p.exists()


# -- sweep takes the admission lock (N2) ----------------------------------------
def test_sweep_does_not_delete_a_copy_renewed_while_it_waited_for_admission(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    blob = b"r" * 100
    p = _old_snap(sd, blob)
    result = {}
    with a._store.exclusive(os.path.join(str(sd), a._ADMISSION_NAME), wait_s=5):    # a snapshot is mid-admission
        t = threading.Thread(target=lambda: result.update(a.sweep_snapshots_persisted(
            str(sd), data_dir=root, now=NOW)))
        t.start()
        t.join(0.3)
        assert t.is_alive()                                           # the sweep is held back by admission
        os.utime(p, (NOW_EPOCH, NOW_EPOCH))                           # the snapshot renews the grace period
    t.join(20)
    assert result["deleted"] == [] and p.exists()


# -- partial copies and unmeasurable directories (N6) ---------------------------
def test_sweep_removes_only_old_uuid_partials(tmp_path):
    root, sd = str(tmp_path / "data"), tmp_path / "s"
    sd.mkdir()
    old_partial, fresh_partial, other = ".%s.tmp" % ("a" * 32), ".%s.tmp" % ("b" * 32), ".abc.tmp"
    for name in (old_partial, fresh_partial, other):
        (sd / name).write_bytes(b"x" * 5)
    age(sd / old_partial, 3)
    age(sd / fresh_partial, 0.1)
    age(sd / other, 3)
    dry = a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW, dry_run=True)
    assert dry["partials_removed"] == [old_partial] and (sd / old_partial).exists()
    res = a.sweep_snapshots_persisted(str(sd), data_dir=root, now=NOW)
    assert res["partials_removed"] == [old_partial]
    assert not (sd / old_partial).exists() and (sd / fresh_partial).exists() and (sd / other).exists()


def test_unmeasurable_snapshot_directory_refuses_admission(tmp_path, monkeypatch):
    sd = tmp_path / "s"
    sd.mkdir()
    src = write(tmp_path / "in", b"i" * 10)

    def boom(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(a.os, "scandir", boom)
    with pytest.raises(OSError):
        a._dir_bytes(str(sd))
    dec = snap(src, sd, quota_bytes=1000, registry=a.PinRegistry())
    monkeypatch.undo()
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_dir_unavailable"}
    assert ls(sd) == []


def test_blocked_admission_lock_file_is_a_diagnostic_not_a_raw_oserror(tmp_path):
    sd = tmp_path / "s"
    sd.mkdir()
    (sd / ".admission.lock").mkdir()                                  # os.open on this path fails
    src = write(tmp_path / "in", b"i" * 10)
    dec = snap(src, sd, quota_bytes=1000, registry=a.PinRegistry())
    assert dec.value is None and codes(dec.diagnostics) == {"snapshot_dir_unavailable"}
    res = a.sweep_snapshots(str(sd), a.PinRegistry(), now=NOW)
    assert res["skipped_reason"] == "snapshot_dir_locked" and res["deleted"] == []
