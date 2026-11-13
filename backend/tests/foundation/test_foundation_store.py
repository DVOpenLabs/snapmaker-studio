"""Store: SQLite migrations/versioning and revision-checked atomic JSON documents."""
import ast
import glob
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

from snapstudio_core.foundation import store

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FOUNDATION = os.path.join(BACKEND, "snapstudio_core", "foundation")


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "data")


def codes(decoded):
    return {d.code for d in decoded.diagnostics}


def child_env(root):
    env = dict(os.environ)
    env["SNAPSTUDIO_DATA_DIR"] = root
    env["PYTHONPATH"] = BACKEND + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_child(root, code, **kw):
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(code).replace("__ROOT__", repr(root))],
                            cwd=BACKEND, env={**child_env(root), "PYTHONPATH": BACKEND},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


# ---------------------------------------------------------------- SQLite
SCHEMA_V1 = "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT);"


def test_open_store_creates_schema_and_sets_version(root):
    with store.open_store("demo", SCHEMA_V1, 1, data_dir=root) as conn:
        conn.execute("INSERT INTO t (v) VALUES ('a')")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.isolation_level is None
    with store.open_store("demo", SCHEMA_V1, 1, data_dir=root) as conn:
        assert conn.execute("SELECT v FROM t").fetchall() == [("a",)]
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == store.BUSY_TIMEOUT_MS


def test_newer_user_version_is_refused_without_writing(root):
    with store.open_store("demo", SCHEMA_V1, 3, data_dir=root):
        pass
    path = os.path.join(store.store_dir(root), "demo.db")
    before = open(path, "rb").read()
    with pytest.raises(store.StoreVersionError):
        with store.open_store("demo", SCHEMA_V1, 2, data_dir=root):
            pytest.fail("must not open")
    assert open(path, "rb").read() == before


def test_failed_migration_rolls_back_schema_and_rows(root):
    with store.open_store("demo", [(1, SCHEMA_V1)], 1, data_dir=root) as conn:
        conn.execute("INSERT INTO t (v) VALUES ('keep')")
    bad = [(1, SCHEMA_V1), (2, "ALTER TABLE t ADD COLUMN extra TEXT; INSERT INTO missing_table VALUES (1);")]
    with pytest.raises(Exception):
        with store.open_store("demo", bad, 2, data_dir=root):
            pass
    with store.open_store("demo", [(1, SCHEMA_V1)], 1, data_dir=root) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert [r[1] for r in conn.execute("PRAGMA table_info(t)")] == ["id", "v"]
        assert conn.execute("SELECT v FROM t").fetchall() == [("keep",)]


def test_migrations_apply_in_order_from_older_version(root):
    with store.open_store("demo", [(1, SCHEMA_V1)], 1, data_dir=root) as conn:
        conn.execute("INSERT INTO t (v) VALUES ('x')")
    steps = [(1, SCHEMA_V1), (2, "ALTER TABLE t ADD COLUMN extra TEXT DEFAULT 'd'")]
    with store.open_store("demo", steps, 2, data_dir=root) as conn:
        assert conn.execute("SELECT v, extra FROM t").fetchall() == [("x", "d")]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_split_statements_keeps_trigger_bodies_whole():
    sql = "CREATE TABLE a (x); CREATE TRIGGER g AFTER INSERT ON a BEGIN INSERT INTO a VALUES (1); END; SELECT 1"
    parts = store.split_statements(sql)
    assert len(parts) == 3 and parts[1].startswith("CREATE TRIGGER") and parts[1].endswith("END;")


def test_transaction_helper_rolls_back_on_error(root):
    with store.open_store("demo", SCHEMA_V1, 1, data_dir=root) as conn:
        with pytest.raises(RuntimeError):
            with store.transaction(conn):
                conn.execute("INSERT INTO t (v) VALUES ('gone')")
                raise RuntimeError("boom")
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_connection_per_call_is_not_shared(root):
    with store.open_store("demo", SCHEMA_V1, 1, data_dir=root) as a:
        with store.open_store("demo", SCHEMA_V1, 1, data_dir=root) as b:
            assert a is not b


@pytest.mark.parametrize("bad", ["", "../x", "Demo", "a b", "a.db", "1abc", None, "x" * 60])
def test_store_names_are_validated(root, bad):
    with pytest.raises(ValueError):
        with store.open_store(bad, SCHEMA_V1, 1, data_dir=root):
            pass
    with pytest.raises(ValueError):
        store.read_json(bad, schema="s", version=1, data_dir=root)


def test_store_uses_data_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "env"))
    with store.open_store("demo", SCHEMA_V1, 1):
        pass
    assert os.path.isfile(tmp_path / "env" / "store" / "demo.db")


# ---------------------------------------------------------------- JSON basics
def rw(root, name="doc", **kw):
    return dict(schema="demo_doc", version=1, data_dir=root, **kw)


def test_missing_file_reads_as_revision_zero(root):
    d = store.read_json("doc", **rw(root))
    assert d.value == {"missing": True, "revision": 0} and d.valid_for_evaluation


def test_write_then_read_roundtrip_and_revisions(root):
    assert store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root)) == 1
    d = store.read_json("doc", **rw(root))
    assert d.value["a"] == 1 and d.value["revision"] == 1 and d.schema_version == "demo_doc/1"
    assert store.write_json("doc", {"a": 2}, expected_revision=1, **rw(root)) == 2


def test_delayed_save_with_old_revision_is_rejected(root):
    store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root))
    store.write_json("doc", {"a": 2}, expected_revision=1, **rw(root))
    with pytest.raises(store.RevisionConflict):
        store.write_json("doc", {"a": 3}, expected_revision=1, **rw(root))
    assert store.read_json("doc", **rw(root)).value["a"] == 2


def test_create_when_exists_conflicts(root):
    store.write_json("doc", {}, expected_revision=0, **rw(root))
    with pytest.raises(store.RevisionConflict):
        store.write_json("doc", {}, expected_revision=0, **rw(root))


def test_nan_and_non_objects_refused(root):
    with pytest.raises(ValueError):
        store.write_json("doc", {"a": float("nan")}, expected_revision=0, **rw(root))
    with pytest.raises(ValueError):
        store.write_json("doc", [1], expected_revision=0, **rw(root))
    assert not os.path.exists(os.path.join(store.store_dir(root), "doc.json"))


def test_size_is_bounded(root, monkeypatch):
    monkeypatch.setattr(store, "MAX_JSON_BYTES", 200)
    with pytest.raises(store.StoreTooLarge):
        store.write_json("doc", {"blob": "x" * 500}, expected_revision=0, **rw(root))
    path = os.path.join(store.store_dir(root), "doc.json")
    with open(path, "wb") as fh:
        fh.write(b'{"schema_version":"demo_doc/1","revision":1,"pad":"' + b"x" * 400 + b'"}')
    d = store.read_json("doc", **rw(root))
    assert d.value is None and "too_large" in codes(d)
    assert os.path.exists(path)                       # too large is refused, not renamed


def test_newer_schema_version_is_preserved_untouched(root):
    path = os.path.join(store.store_dir(root), "doc.json")
    original = b'{"schema_version":"demo_doc/9","revision":4,"future":true}'
    open(path, "wb").write(original)
    d = store.read_json("doc", **rw(root))
    assert d.value is None and "newer_schema_version" in codes(d) and d.raw["future"] is True
    with pytest.raises(store.StoreVersionError):
        store.write_json("doc", {"a": 1}, expected_revision=4, **rw(root))
    assert open(path, "rb").read() == original
    assert glob.glob(path + ".damaged*") == []


def test_undecodable_bytes_are_renamed_damaged(root):
    path = os.path.join(store.store_dir(root), "doc.json")
    open(path, "wb").write(b"\xff\xfe{not json")
    d = store.read_json("doc", **rw(root))
    assert d.value is None and "damaged_file" in codes(d)
    assert not os.path.exists(path)
    moved = glob.glob(path + ".damaged-*")
    assert len(moved) == 1 and open(moved[0], "rb").read() == b"\xff\xfe{not json"
    # a fresh document can now be created
    assert store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root)) == 1


def test_foreign_valid_json_is_not_renamed(root):
    path = os.path.join(store.store_dir(root), "doc.json")
    open(path, "wb").write(b'{"hello": 1}')
    d = store.read_json("doc", **rw(root))
    assert d.value is None and "missing_schema_version" in codes(d)
    assert os.path.exists(path)
    with pytest.raises(store.StoreError):
        store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root))
    open(path, "wb").write(b'[1,2]')
    assert "not_an_object" in codes(store.read_json("doc", **rw(root)))
    assert os.path.exists(path)


def test_replace_permission_error_retried_then_succeeds(root, monkeypatch):
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError("sharing violation")
        return real(src, dst)

    monkeypatch.setattr(store, "_replace", flaky)
    monkeypatch.setattr(store, "_sleep", lambda s: None)
    assert store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root)) == 1
    assert calls["n"] == 4
    assert store.read_json("doc", **rw(root)).value["a"] == 1


def test_replace_permission_error_exhausted_keeps_previous_file(root, monkeypatch):
    store.write_json("doc", {"a": 1}, expected_revision=0, **rw(root))
    monkeypatch.setattr(store, "_replace", lambda s, d: (_ for _ in ()).throw(PermissionError("busy")))
    monkeypatch.setattr(store, "_sleep", lambda s: None)
    with pytest.raises(PermissionError):
        store.write_json("doc", {"a": 2}, expected_revision=1, **rw(root))
    monkeypatch.undo()
    d = store.read_json("doc", **rw(root))
    assert d.value["a"] == 1 and d.value["revision"] == 1
    leftovers = [n for n in os.listdir(store.store_dir(root)) if n.endswith(".tmp")]
    assert leftovers == []


def test_temp_name_is_unique_and_same_directory(root, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(store, "_replace", lambda s, d: (seen.append((s, d)), real(s, d))[1])
    store.write_json("doc", {}, expected_revision=0, **rw(root))
    store.write_json("doc", {}, expected_revision=1, **rw(root))
    assert len({s for s, _ in seen}) == 2
    for s, d in seen:
        assert os.path.dirname(s) == os.path.dirname(d) and s.endswith(".tmp")


# ---------------------------------------------------------------- locking
def test_in_process_writers_serialise_revision_race(root):
    import threading
    results = []

    def attempt():
        try:
            results.append(store.write_json("doc", {"n": 1}, expected_revision=0, **rw(root)))
        except store.RevisionConflict:
            results.append("conflict")

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(map(str, results)) == sorted(["1"] + ["conflict"] * 5)


def lock_path(root):
    return os.path.join(store.store_dir(root), "doc.json.lock")


# ---------------------------------------------------------------- multi-process
WRITER = """
import sys, time, os
from snapstudio_core.foundation import store
root = __ROOT__
go = os.path.join(root, 'go')
while not os.path.exists(go):
    time.sleep(0.005)
try:
    store.write_json('doc', {'who': sys.argv[1]}, expected_revision=0, schema='demo_doc', version=1, data_dir=root)
    print('won')
except store.RevisionConflict:
    print('conflict')
"""


def test_concurrent_processes_same_expected_revision_one_wins(root):
    store.store_dir(root)
    procs = []
    for who in ("a", "b"):
        p = subprocess.Popen([sys.executable, "-c", textwrap.dedent(WRITER).replace("__ROOT__", repr(root)), who],
                             cwd=BACKEND, env={**child_env(root), "PYTHONPATH": BACKEND},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        procs.append(p)
    time.sleep(1.0)
    open(os.path.join(root, "go"), "w").close()
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err.decode()
        outs.append(out.decode().strip())
    assert sorted(outs) == ["conflict", "won"]
    d = store.read_json("doc", **rw(root))
    assert d.value["revision"] == 1 and d.value["who"] in ("a", "b")


KILLER = """
import os
from snapstudio_core.foundation import store
root = __ROOT__
rev = 0
big = 'x' * 3_000_000
i = 0
while True:
    i += 1
    rev = store.write_json('doc', {'i': i, 'pad': big}, expected_revision=rev, schema='demo_doc', version=1, data_dir=root)
    if i == 2:
        open(os.path.join(root, 'ready'), 'w').close()
"""


def test_killing_a_writer_mid_write_leaves_old_or_new_never_partial(root):
    store.store_dir(root)
    seen_revisions = set()
    for round_no in range(3):
        ready = os.path.join(root, "ready")
        if os.path.exists(ready):
            os.remove(ready)
        proc = run_child(root, KILLER.replace("rev = 0", "rev = store.read_json('doc', schema='demo_doc', version=1, data_dir=root).value['revision']"))
        deadline = time.time() + 60
        while not os.path.exists(ready) and time.time() < deadline:
            time.sleep(0.01)
        assert os.path.exists(ready), "writer never got going"
        time.sleep(0.05 * (round_no + 1))
        proc.kill()
        proc.wait()
        d = store.read_json("doc", **rw(root))
        assert d.value is not None and "damaged_file" not in codes(d), codes(d)
        assert d.value["pad"] == "x" * 3_000_000 and d.value["i"] >= 1
        assert not glob.glob(os.path.join(store.store_dir(root), "doc.json.damaged-*"))
        seen_revisions.add(d.value["revision"])
        # a stale lock left by the killed process does not block the next writer
        rev = d.value["revision"]
        assert store.write_json("doc", {"i": -1, "pad": "x" * 3_000_000}, expected_revision=rev, **rw(root)) == rev + 1
    assert len(seen_revisions) >= 2


# ---------------------------------------------------------------- guards
def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(("." * node.level) + (node.module or ""))
    return found


NETWORK = {"socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "http"}


def test_only_netguard_may_import_network_modules():
    offenders = []
    for path in glob.glob(os.path.join(FOUNDATION, "*.py")):
        if os.path.basename(path) == "netguard.py":
            continue
        bad = {m for m in _imports(path) if m in NETWORK or m.split(".")[0] in {"socket", "ssl", "urllib3", "requests"}}
        if bad:
            offenders.append((os.path.basename(path), sorted(bad)))
    assert offenders == []


def test_store_has_no_process_or_network_imports():
    mods = _imports(os.path.join(FOUNDATION, "store.py"))
    assert not ({"subprocess", "socket", "ssl"} & mods)
    tree = ast.parse(open(os.path.join(FOUNDATION, "store.py"), encoding="utf-8").read())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "executescript" not in names


# ---------------------------------------------------------------- pin persistence (artifacts <-> store)
import hashlib as _hashlib

from snapstudio_core.foundation import artifacts as art

_NOW = 1768003200.0
_DAY = 86400


def _aid(data: bytes) -> str:
    return art.make_artifact_id(_hashlib.sha256(data).hexdigest(), len(data))


def _snap_file(snapdir, data: bytes, days_old: float):
    os.makedirs(snapdir, exist_ok=True)
    path = os.path.join(snapdir, _hashlib.sha256(data).hexdigest())
    open(path, "wb").write(data)
    t = _NOW - days_old * _DAY
    os.utime(path, (t, t))
    return path


@pytest.fixture
def snapdir(tmp_path):
    return str(tmp_path / "snaps")


def test_pins_persist_across_loads_and_are_revisioned(root):
    a = _aid(b"one")
    art.pin_persisted(a, "passport", "p1", data_dir=root)
    art.pin_persisted(a, "checkpoint", "c1", data_dir=root)
    reg = art.load_pin_registry(root)
    assert reg.valid_for_evaluation and reg.value.holders(a) == [("checkpoint", "c1"), ("passport", "p1")]
    assert store.read_json("snapshot_pins", schema="snapshot_pins", version=1, data_dir=root).value["revision"] == 2
    assert art.unpin_persisted(a, "passport", "p1", data_dir=root) is True
    assert art.unpin_persisted(a, "passport", "p1", data_dir=root) is False
    assert art.load_pin_registry(root).value.holders(a) == [("checkpoint", "c1")]


def test_missing_pin_file_is_an_empty_valid_registry(root):
    reg = art.load_pin_registry(root)
    assert reg.valid_for_evaluation and reg.value.pinned_hashes() == set()


def test_unpin_holder_and_replace_holder_pins(root):
    a, b, c = _aid(b"a"), _aid(b"b"), _aid(b"c")
    for x in (a, b):
        art.pin_persisted(x, "assembly", "asm1", data_dir=root)
    art.pin_persisted(a, "passport", "p1", data_dir=root)
    # superseded: asm1 now references b and c only
    assert art.replace_holder_pins("assembly", "asm1", [b, c], data_dir=root) == {"added": [c], "removed": [a]}
    reg = art.load_pin_registry(root).value
    assert reg.holders(a) == [("passport", "p1")] and reg.holders(c) == [("assembly", "asm1")]
    # deleted: every pin of the holder goes, other holders' pins stay
    assert art.unpin_holder("assembly", "asm1", data_dir=root) == 2
    reg = art.load_pin_registry(root).value
    assert reg.pinned_hashes() == {a.split(":")[1]}


def test_pin_before_persist_orders_pin_first_and_rolls_back_on_failure(root):
    a, b = _aid(b"a"), _aid(b"b")
    art.pin_persisted(b, "workspace", "w1", data_dir=root)          # already held by this holder: must survive rollback
    order = []

    def persist_ok():
        order.append(("persist", art.load_pin_registry(root).value.holders(a)))
        return "saved"

    assert art.pin_before_persist([a], "workspace", "w1", persist_ok, data_dir=root) == "saved"
    assert order == [("persist", [("workspace", "w1")])]              # the pin existed when persist ran

    def persist_fails():
        raise OSError("disk full")

    c = _aid(b"c")
    with pytest.raises(OSError):
        art.pin_before_persist([b, c], "workspace", "w1", persist_fails, data_dir=root)
    reg = art.load_pin_registry(root).value
    assert reg.holders(c) == [] and reg.holders(b) == [("workspace", "w1")] and reg.holders(a) == [("workspace", "w1")]


def test_pin_registry_updates_from_two_processes_do_not_lose_pins(root):
    script = """
import sys
from snapstudio_core.foundation import artifacts as art
root = __ROOT__
for n in range(10):
    art.pin_persisted('sha256:' + ('%064x' % (int(sys.argv[1]) * 100 + n)) + ':1', 'checkpoint', 'c' + sys.argv[1], data_dir=root)
"""
    procs = [subprocess.Popen([sys.executable, "-c", textwrap.dedent(script).replace("__ROOT__", repr(root)), str(i)],
                              cwd=BACKEND, env={**child_env(root), "PYTHONPATH": BACKEND},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in (1, 2)]
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode()
    assert len(art.load_pin_registry(root).value.pinned_hashes()) == 20


def test_sweep_keeps_pinned_snapshots_and_removes_old_unpinned(root, snapdir):
    passport_only, workspace, orphan, fresh = b"passport", b"workspace", b"orphan", b"fresh"
    paths = {n: _snap_file(snapdir, d, 3) for n, d in [("passport", passport_only), ("workspace", workspace), ("orphan", orphan)]}
    paths["fresh"] = _snap_file(snapdir, fresh, 0.1)                 # inside the 24 h grace
    art.pin_persisted(_aid(passport_only), "passport", "p1", data_dir=root)       # referenced only by a passport
    art.pin_persisted(_aid(workspace), "workspace", "active", data_dir=root)      # active, not yet checkpointed
    result = art.sweep_snapshots_persisted(snapdir, data_dir=root, now=_NOW)
    assert result == {"deleted": [_hashlib.sha256(orphan).hexdigest()], "skipped_reason": None,
                      "partials_removed": []}
    assert not os.path.exists(paths["orphan"])
    assert all(os.path.exists(paths[n]) for n in ("passport", "workspace", "fresh"))


def test_unreadable_pin_registry_blocks_sweep_and_quota_eviction(root, snapdir):
    old = _snap_file(snapdir, b"old-unpinned", 5)
    os.makedirs(store.store_dir(root), exist_ok=True)
    pin_file = os.path.join(store.store_dir(root), "snapshot_pins.json")
    for bad in (b"\xff{garbage", b'{"schema_version":"snapshot_pins/7","revision":2,"pins":[]}',
                b'{"schema_version":"snapshot_pins/1","revision":1,"pins":"nope"}'):
        open(pin_file, "wb").write(bad)
        reg = art.load_pin_registry(root)
        assert reg.value is None
        assert art.sweep_snapshots_persisted(snapdir, data_dir=root, now=_NOW) == {
            "deleted": [], "skipped_reason": "pin_registry_unreadable"}
        src = os.path.join(os.path.dirname(snapdir), "src.bin")
        open(src, "wb").write(b"z" * 50)
        res = art.snapshot(src, "original", snapshot_dir=snapdir, quota_bytes=len(b"old-unpinned") + 10,
                           registry=reg, now=_NOW)
        assert res.value is None and any(d.code == "snapshot_quota_exceeded" for d in res.diagnostics)
        assert os.path.exists(old)
        if os.path.exists(pin_file) and b"\xff" not in bad:
            assert open(pin_file, "rb").read() == bad                 # newer / invalid contents untouched
        with pytest.raises(store.StoreError):
            art.pin_persisted(_aid(b"x"), "passport", "p9", data_dir=root)


def test_quota_eviction_uses_the_same_rule_with_a_persisted_registry(root, snapdir):
    keep = _snap_file(snapdir, b"k" * 100, 3)
    drop = _snap_file(snapdir, b"d" * 100, 3)
    young = _snap_file(snapdir, b"y" * 100, 0.2)
    art.pin_persisted(_aid(b"k" * 100), "passport", "p1", data_dir=root)
    src = os.path.join(os.path.dirname(snapdir), "new.bin")
    open(src, "wb").write(b"n" * 100)
    res = art.snapshot(src, "original", snapshot_dir=snapdir, quota_bytes=350,
                       registry=art.load_pin_registry(root), now=_NOW)
    assert res.value is not None
    assert os.path.exists(keep) and os.path.exists(young) and not os.path.exists(drop)


def test_resnapshot_renews_grace_of_existing_copy(root, snapdir):
    data = b"same bytes"
    old = _snap_file(snapdir, data, 5)
    src = os.path.join(os.path.dirname(snapdir), "again.bin")
    open(src, "wb").write(data)
    assert art.snapshot(src, "original", snapshot_dir=snapdir).value is not None
    assert os.path.getmtime(old) > time.time() - 60



def test_damaged_rename_rechecks_bytes_under_the_lock(root, monkeypatch):
    path = os.path.join(store.store_dir(root), "doc.json")
    open(path, "wb").write(b"{broken")
    real = store._writer_lock

    import contextlib

    @contextlib.contextmanager
    def lock_then_repair(p, **kw):
        with real(p, **kw):
            store.write_json  # noqa: B018  (writer finished before we got the lock)
            open(p, "wb").write(json.dumps({"schema_version": "doc/1", "revision": 1}).encode())
            yield

    monkeypatch.setattr(store, "_writer_lock", lock_then_repair)
    store.read_json("doc", **rw(root))
    assert os.path.exists(path) and glob.glob(path + ".damaged-*") == []


# ---------------------------------------------------------------- OS advisory lock (F1)
HOLDER = """
import sys
from snapstudio_core.foundation import store
with store.document_lock('doc', data_dir=__ROOT__):
    print('held', flush=True)
    sys.stdin.readline()
"""

CONTENDER = """
import os, sys, time
from snapstudio_core.foundation import store
root = __ROOT__
inside, viol, log = (os.path.join(root, n) for n in ('inside', 'violation', 'log'))
go = os.path.join(root, 'go')
while not os.path.exists(go):
    time.sleep(0.005)
for i in range(8):
    with store.document_lock('doc', data_dir=root, wait_s=60):
        if os.path.exists(inside):
            open(viol, 'a').write('x')
        open(inside, 'w').write(sys.argv[1])
        time.sleep(0.03)
        open(log, 'a').write(sys.argv[1])
        os.remove(inside)
print('done')
"""


def _start_holder(root):
    holder = run_child(root, HOLDER, stdin=subprocess.PIPE)
    assert holder.stdout.readline().strip() == b"held"
    return holder


def _release_holder(holder):
    holder.stdin.write(b"\n")
    holder.stdin.flush()
    holder.wait(timeout=30)
    for stream in (holder.stdin, holder.stdout, holder.stderr):
        stream.close()


def test_two_processes_contend_with_exactly_one_inside_at_a_time(root):
    os.makedirs(root, exist_ok=True)
    procs = [run_child(root, CONTENDER.replace("sys.argv[1]", repr(tag))) for tag in ("A", "B")]
    open(os.path.join(root, "go"), "w").close()
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0 and out.strip() == b"done", err.decode()
    assert not os.path.exists(os.path.join(root, "violation"))
    log = open(os.path.join(root, "log")).read()
    assert sorted(log) == ["A"] * 8 + ["B"] * 8


def test_killed_holder_releases_the_lock_automatically(root):
    holder = _start_holder(root)
    try:
        with pytest.raises(store.StoreLockError):
            with store.document_lock("doc", data_dir=root, wait_s=0.2):
                pass
        holder.terminate()
        holder.wait(timeout=30)
        with store.document_lock("doc", data_dir=root, wait_s=5):    # no stale-lock timer to wait for
            pass
    finally:
        holder.kill()
        holder.wait()
        for stream in (holder.stdin, holder.stdout, holder.stderr):
            stream.close()


def test_held_lock_times_out_and_is_never_unlinked(root):
    holder = _start_holder(root)
    try:
        with pytest.raises(store.StoreLockError):
            store.write_json("doc", {}, expected_revision=0, lock_wait_s=0.2, **rw(root))
        assert os.path.exists(lock_path(root))                       # a waiter never removes the holder's lock file
        diag = json.loads(open(lock_path(root), "rb").read().decode("utf-8")) if sys.platform != "win32" else None
        assert diag is None or diag["pid"] == holder.pid             # contents are diagnostics only
    finally:
        _release_holder(holder)
    assert store.write_json("doc", {}, expected_revision=0, **rw(root)) == 1
    assert os.path.exists(lock_path(root))                           # the file persists after release


def test_in_process_second_taker_times_out(root):
    with store.document_lock("doc", data_dir=root):
        with pytest.raises(store.StoreLockError):
            import threading
            err = []

            def other():
                try:
                    with store.document_lock("doc", data_dir=root, wait_s=0.1):
                        pass
                except store.StoreLockError as exc:
                    err.append(exc)

            t = threading.Thread(target=other)
            t.start()
            t.join(10)
            raise err[0]


def test_three_parties_never_hold_the_lock_together(root):
    import threading
    parties = 3
    barrier = threading.Barrier(parties)
    state = {"inside": 0, "max": 0, "entries": 0}
    guard = threading.Lock()

    def party():
        barrier.wait()
        for _ in range(25):
            with store.document_lock("doc", data_dir=root, wait_s=30):
                with guard:
                    state["inside"] += 1
                    state["max"] = max(state["max"], state["inside"])
                    state["entries"] += 1
                time.sleep(0.001)
                with guard:
                    state["inside"] -= 1

    threads = [threading.Thread(target=party) for _ in range(parties)]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    assert state["max"] == 1 and state["entries"] == parties * 25 and state["inside"] == 0


def test_os_lock_attempts_alone_exclude_each_other_across_descriptors(root):
    """The OS lock itself (not the thread lock) refuses a second descriptor, and a close frees it."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "x.lock")
    first = os.open(path, os.O_CREAT | os.O_RDWR)
    second = os.open(path, os.O_CREAT | os.O_RDWR)
    try:
        assert store._try_os_lock(first) is True
        assert store._try_os_lock(second) is False
        os.close(first)
        first = None
        assert store._try_os_lock(second) is True
    finally:
        if first is not None:
            os.close(first)
        os.close(second)


def test_rename_damaged_inside_own_document_lock_is_skipped_without_stalling(root):
    path = os.path.join(store.store_dir(root), "doc.json")
    open(path, "wb").write(b"{broken")
    with store.document_lock("doc", data_dir=root):
        started = time.monotonic()
        d = store.read_json("doc", **rw(root))                       # rename_damaged=True by default
        elapsed = time.monotonic() - started
    assert "damaged_file" in codes(d)
    assert elapsed < 0.5                                             # no 1 s wait on our own lock
    assert open(path, "rb").read() == b"{broken" and glob.glob(path + ".damaged-*") == []


def test_read_json_does_not_rename_damaged_file_while_another_process_holds_the_lock(root):
    path = os.path.join(store.store_dir(root), "doc.json")
    open(path, "wb").write(b"{broken")
    holder = _start_holder(root)
    try:
        d = store.read_json("doc", **rw(root))
        assert "damaged_file" in codes(d)
        assert open(path, "rb").read() == b"{broken" and glob.glob(path + ".damaged-*") == []
    finally:
        _release_holder(holder)


def test_an_unopenable_lock_file_raises_store_lock_error(tmp_path):
    target = str(tmp_path / "doc")
    os.mkdir(target + ".lock")                                        # os.open on a directory fails
    with pytest.raises(store.StoreLockError):
        with store.exclusive(target, wait_s=0.1):
            pytest.fail("the lock must not be granted")
    with store.exclusive(str(tmp_path / "other"), wait_s=0.1):         # and the thread lock was released
        pass
