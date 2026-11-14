"""P8 recovery tests 1, 2, 8, 9, 10 against the real store under a throwaway data dir.

Evidence label: fixture-tested. All names and bytes are synthetic.
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

from snapstudio_core import workspace_recovery as recovery
from snapstudio_core.foundation import artifacts, store
from snapstudio_core.foundation.observations import Observation


def ref_for(data: bytes, name: str):
    return artifacts.ArtifactRef.create(hashlib.sha256(data).hexdigest(), len(data), "original", name)


def obs():
    return Observation("o1", {"kind": "file", "id": "part"}, "state", "printing",
                       {"provider_instance_id": "fixture", "kind": "live_query", "snapshot_id": "s1"},
                       "2026-10-31T12:00:00Z", "2026-10-31T12:00:00Z", 60)


def test_1_10_restore_marks_historical_and_interrupts_jobs_without_replay(tmp_path):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {"name": "demo"}, "observations": [obs().to_dict()], "files": [],
                         "jobs": [{"job_id": "job-1", "state": "running"},
                                  {"job_id": "job-2", "state": "succeeded"}],
                         "checkpointed_at": "2026-10-31T12:00:00Z"}, data_dir=d)
    restored = recovery.restore(data_dir=d)
    assert restored["observations"][0]["historical"] is True
    assert restored["observations"][0]["usable_for_loadout"] is False
    assert restored["fresh_read_required"] is True
    states = {j["job_id"]: j["state"] for j in restored["jobs"]}
    assert states == {"job-1": "interrupted", "job-2": "succeeded"}
    assert all(j["replayed"] is False for j in restored["jobs"])


def test_2_missing_changed_and_size_equal_replacement_detected(tmp_path):
    d = str(tmp_path)
    same, changed, swapped, gone = (tmp_path / n for n in ("same.3mf", "changed.3mf", "swapped.3mf", "gone.3mf"))
    for path in (same, changed, swapped, gone):
        path.write_bytes(b"AAAAAAAA")
    files = [{"name": p.name, "path": str(p), "artifact": ref_for(b"AAAAAAAA", p.name).to_dict()}
             for p in (same, changed, swapped, gone)]
    recovery.checkpoint({"files": files}, data_dir=d)
    changed.write_bytes(b"AAAAAAAAXX")
    swapped.write_bytes(b"BBBBBBBB")                      # same size, different bytes
    gone.unlink()
    restored = recovery.restore(data_dir=d)
    state = {f["name"]: f["state"] for f in restored["files"]}
    assert state == {"same.3mf": "same", "changed.3mf": "changed", "swapped.3mf": "changed",
                     "gone.3mf": "missing"}
    assert all(f["association"] == "unverified" for f in restored["files"])
    assert "path" not in restored["files"][0]              # the UI sees names only


def test_missing_checkpoint_is_reported_not_invented(tmp_path):
    restored = recovery.restore(data_dir=str(tmp_path))
    assert restored["missing_checkpoint"] is True and restored["fresh_read_required"] is True
    assert restored["observations"] == [] and restored["files"] == []


def test_8_legacy_record_imported_one_way_and_both_mechanisms_coexist(tmp_path):
    d = str(tmp_path)
    legacy_doc = {"schema_version": "job/1", "revision": 3, "record": {
        "savedAt": "2026-10-30T12:00:00Z", "original": {"name": "legacy.3mf", "path": "synthetic/legacy.3mf"}}}
    legacy_path = os.path.join(store.store_dir(d), "job.json")
    with open(legacy_path, "w", encoding="utf-8") as handle:
        json.dump(legacy_doc, handle)
    before = open(legacy_path, "rb").read()
    # Legacy present, no recovery document yet: restore still shows it and writes nothing.
    first = recovery.restore(data_dir=d)
    assert first["legacy_job"]["files"][0]["name"] == "legacy.3mf"
    assert first["legacy_job"]["files"][0]["association"] == "unverified"
    assert not os.path.exists(os.path.join(store.store_dir(d), "recovery.json"))
    # Both present: checkpoint imports it into recovery.json, the legacy file is untouched.
    recovery.checkpoint({"workspace": {"name": "demo"}}, data_dir=d)
    assert open(legacy_path, "rb").read() == before
    assert recovery.restore(data_dir=d)["legacy_job"]["files"][0]["name"] == "legacy.3mf"
    # A browser-held record sent with the checkpoint is imported too, with no legacy store file.
    d2 = str(tmp_path / "other")
    recovery.checkpoint({"jobs": [{"legacy_record": {"savedAt": "x", "original": {"name": "ls.3mf"},
                                                      "sliced": {"name": "ls.gcode"}}}]}, data_dir=d2)
    roles = [f["role"] for f in recovery.restore(data_dir=d2)["legacy_job"]["files"]]
    assert roles == ["original", "sliced"]


def test_damaged_legacy_file_is_not_renamed_by_restore(tmp_path):
    d = str(tmp_path)
    legacy_path = os.path.join(store.store_dir(d), "job.json")
    with open(legacy_path, "wb") as handle:
        handle.write(b"{not json")
    assert recovery.restore(data_dir=d)["legacy_job"] is None
    assert os.path.exists(legacy_path)


def test_secret_like_fields_are_not_persisted(tmp_path):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {"name": "demo", "apiKey": "SENTINEL-KEY-9f3a",
                                       "nested": {"Authorization": "SENTINEL-KEY-9f3a", "ok": 1}}}, data_dir=d)
    raw = open(os.path.join(store.store_dir(d), "recovery.json"), encoding="utf-8").read()
    assert "SENTINEL-KEY-9f3a" not in raw and '"ok":1' in raw


def test_newer_schema_document_is_left_untouched(tmp_path):
    d = str(tmp_path)
    path = os.path.join(store.store_dir(d), "recovery.json")
    newer = json.dumps({"schema_version": "recovery/99", "revision": 5}).encode()
    with open(path, "wb") as handle:
        handle.write(newer)
    with pytest.raises(store.StoreVersionError):
        recovery.checkpoint({}, data_dir=d)
    assert open(path, "rb").read() == newer


# ------------------------------------------------------------------ test 9: crash and lock safety
CHILD_CRASH = (
    "import os, sys\n"
    "from snapstudio_core.foundation import store\n"
    "from snapstudio_core import workspace_recovery as r\n"
    "store._replace = lambda *a, **k: os._exit(7)\n"          # die after the temp file is written, before the swap
    "r.checkpoint({'workspace': {'name': 'NEW'}}, data_dir=sys.argv[1])\n"
)
CHILD_LOCKED = (
    "import sys\n"
    "from snapstudio_core.foundation import store\n"
    "from snapstudio_core import workspace_recovery as r\n"
    "try:\n"
    "    r.checkpoint({'workspace': {'name': 'OTHER'}}, data_dir=sys.argv[1], lock_wait_s=0.3)\n"
    "except store.StoreLockError:\n"
    "    sys.exit(42)\n"
    "sys.exit(0)\n"
)


def run_child(code, data_dir):
    env = dict(os.environ)
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-c", code, data_dir], env=env, timeout=60,
                          capture_output=True).returncode


def test_9_killed_writer_leaves_the_old_document_whole(tmp_path):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {"name": "OLD"}}, data_dir=d)
    assert run_child(CHILD_CRASH, d) == 7
    restored = recovery.restore(data_dir=d)                # parses cleanly: old, never partial
    assert restored["workspace"] == {"name": "OLD"} and restored["revision"] == 1
    recovery.checkpoint({"workspace": {"name": "NEW"}}, data_dir=d)    # and a later save still works
    assert recovery.restore(data_dir=d)["workspace"] == {"name": "NEW"}


def test_9_second_process_writer_is_refused_by_the_lock(tmp_path):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {"name": "OLD"}}, data_dir=d)
    with store.document_lock("recovery", data_dir=d):
        assert run_child(CHILD_LOCKED, d) == 42
    assert recovery.restore(data_dir=d)["workspace"] == {"name": "OLD"}


def test_9_stale_revision_is_refused(tmp_path, monkeypatch):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {"name": "A"}}, data_dir=d)
    real = store.write_json

    def racing(name, doc, *, expected_revision, **kw):      # another writer lands between read and write
        real(name, {"workspace": {"name": "OTHER"}}, expected_revision=expected_revision, **kw)
        return real(name, doc, expected_revision=expected_revision, **kw)

    monkeypatch.setattr(recovery.store, "write_json", racing)
    with pytest.raises(store.RevisionConflict):
        recovery.checkpoint({"workspace": {"name": "B"}}, data_dir=d)
    assert recovery.restore(data_dir=d)["workspace"] == {"name": "OTHER"}


def test_2_path_only_files_are_fingerprinted_at_checkpoint(tmp_path):
    d = str(tmp_path)
    part, absent = tmp_path / "part.3mf", tmp_path / "never-existed.3mf"
    part.write_bytes(b"synthetic-bytes")
    recovery.checkpoint({"files": [{"path": str(part)}, {"path": str(absent)}]}, data_dir=d)
    assert {f["name"]: f["state"] for f in recovery.restore(data_dir=d)["files"]} == {
        "part.3mf": "same", "never-existed.3mf": "unverified"}
    part.write_bytes(b"synthetic-bytez")                     # same size, one byte different
    assert recovery.restore(data_dir=d)["files"][0]["state"] == "changed"


def test_stale_client_revision_is_refused_and_current_one_accepted(tmp_path):
    d = str(tmp_path)
    first = recovery.checkpoint({"workspace": {"name": "A"}}, data_dir=d)["revision"]
    recovery.checkpoint({"workspace": {"name": "B"}}, data_dir=d, expected_revision=first)
    with pytest.raises(store.RevisionConflict):
        recovery.checkpoint({"workspace": {"name": "C"}}, data_dir=d, expected_revision=first)
    assert recovery.restore(data_dir=d)["workspace"] == {"name": "B"}


UNC = r"\\host\share\part.3mf"


def test_unc_and_directory_paths_are_never_opened_or_hashed(tmp_path, monkeypatch):
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda *a, **k: (opened.append(a[0]), real_open(*a, **k))[1])
    entry = recovery._fingerprint({"path": UNC})
    assert "artifact" not in entry
    assert "artifact" not in recovery._fingerprint({"path": str(tmp_path)})
    assert not any(str(p) == UNC for p in opened)


def test_secret_like_keys_in_observations_are_not_persisted(tmp_path):
    d = str(tmp_path)
    recovery.checkpoint({"workspace": {}, "observations": [{"id": "o", "Authorization": "SENTINEL-KEY-9f3a"}]},
                        data_dir=d)
    raw = open(os.path.join(store.store_dir(d), "recovery.json"), encoding="utf-8").read()
    assert "SENTINEL-KEY-9f3a" not in raw
