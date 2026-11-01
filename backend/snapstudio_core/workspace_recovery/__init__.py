"""Checkpoint and restore local workspace context.

The checkpoint is one revision-checked `recovery.json` written through `foundation.store`. Restore
never replays work and never trusts what it reads: observations come back historical, files are
re-hashed against their recorded identity, jobs that were in flight come back `interrupted`.
The old desktop job record (`store/job.ts`) is imported one way into this document and never
written back, so the two restore mechanisms cannot overwrite each other.
"""

from __future__ import annotations

import hashlib
import os
from snapstudio_core import localpath
import re
from copy import deepcopy
from typing import Any

from snapstudio_core.foundation import artifacts, observations, store

STORE_NAME = "recovery"
SCHEMA = "recovery"
VERSION = 1
_SECRET_KEY = re.compile(r"api[_-]?key|token|authorization|password|secret", re.IGNORECASE)
_MAX_DEPTH = 8
_ROLES = ("original", "prepared", "sliced")
MAX_FINGERPRINT_BYTES = 512 * 1024 * 1024        # larger files are tracked by name only


def _scrub(value: Any, depth: int = 0) -> Any:
    """Copy `value` without any field that looks like a credential; bounded depth."""
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {k: _scrub(v, depth + 1) for k, v in value.items()
                if isinstance(k, str) and not _SECRET_KEY.search(k)}
    if isinstance(value, list):
        return [_scrub(v, depth + 1) for v in value]
    return value


def _fingerprint(item: dict) -> dict:
    """Track a local file by path: record its bytes identity now, read-only. Unreadable stays unverified."""
    path = item.get("path")
    name = item.get("name") if isinstance(item.get("name"), str) else None
    if not isinstance(path, str) or not path:
        return {"name": name or "Unknown file", "path": None}
    entry = {"name": name or os.path.basename(path) or "Unknown file", "path": path}
    if isinstance(item.get("artifact"), dict):
        entry["artifact"] = item["artifact"]
        return entry
    if not localpath.is_local_regular_file(path, max_bytes=MAX_FINGERPRINT_BYTES):
        return entry                                        # network/device/non-regular/oversize: never opened
    try:
        if os.path.getsize(path) > MAX_FINGERPRINT_BYTES:
            return entry
        digest, size = hashlib.sha256(), 0
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        entry["artifact"] = artifacts.ArtifactRef.create(digest.hexdigest(), size, "original",
                                                         entry["name"]).to_dict()
    except OSError:
        pass
    return entry


def _import_legacy(record: Any) -> dict | None:
    """Translate an old `job/1` record into the recovery shape. Association stays unverified."""
    if not isinstance(record, dict) or not isinstance(record.get("original"), dict):
        return None
    return {"schema": "legacy-job-import/1", "saved_at": record.get("savedAt"),
            "files": [{"role": role, "name": item.get("name", "Unknown file"),
                       "path": item.get("path"), "fingerprint": _scrub(item.get("fingerprint")),
                       "association": "unverified"}
                      for role in _ROLES if isinstance((item := record.get(role)), dict)]}


def _legacy_job(data_dir: str | None) -> dict | None:
    """Read the old job store once, without renaming or writing anything."""
    legacy = store.read_json("job", schema="job", version=1, data_dir=data_dir, rename_damaged=False)
    doc = legacy.value
    if not isinstance(doc, dict) or doc.get("missing"):
        return None
    return _import_legacy(doc.get("record", doc))


def _read_recovery(data_dir: str | None):
    current = store.read_json(STORE_NAME, schema=SCHEMA, version=VERSION, data_dir=data_dir)
    if current.value is None:
        if any(d.code == "newer_schema_version" for d in current.diagnostics):
            raise store.StoreVersionError("recovery document was written by a newer version")
        raise store.StoreError("recovery document is unreadable")
    return current


def checkpoint(payload: dict, *, data_dir: str | None = None,
               lock_wait_s: float = store.LOCK_WAIT_S, expected_revision: int | None = None) -> dict:
    """Revision-checked checkpoint; paths stay local and the UI exposes names only.

    A caller that holds the revision it last saw passes it as expected_revision; a mismatch is refused.
    Without one, the check only covers the read-then-write window inside this call (last writer wins)."""
    current = _read_recovery(data_dir)
    if expected_revision is not None and expected_revision != current.value["revision"]:
        raise store.RevisionConflict("checkpoint revision is stale")
    jobs = [item for item in payload.get("jobs", []) if isinstance(item, dict)]
    legacy = next((_import_legacy(item["legacy_record"]) for item in jobs
                   if isinstance(item.get("legacy_record"), dict)), None)
    imported = legacy or _legacy_job(data_dir)
    job_records = [item for item in jobs if isinstance(item.get("job_id"), str)]
    body = {"workspace": _scrub(payload.get("workspace", {})),
            "observations": _scrub(deepcopy(payload.get("observations", []))),
            "files": [_fingerprint(f) for f in _scrub(payload.get("files", [])) if isinstance(f, dict)],
            "jobs": _scrub(job_records),
            "legacy_job": imported, "checkpointed_at": payload.get("checkpointed_at")}
    revision = store.write_json(STORE_NAME, body, expected_revision=current.value["revision"],
                                schema=SCHEMA, version=VERSION, data_dir=data_dir,
                                lock_wait_s=lock_wait_s)
    return {"revision": revision, "checkpointed_at": body["checkpointed_at"],
            "workspace": body["workspace"], "file_count": len(body["files"]),
            "observation_count": len(body["observations"]), "job_count": len(body["jobs"])}


def restore(*, data_dir: str | None = None) -> dict:
    """Preview of what a checkpoint holds. Read-only: nothing is applied or replayed."""
    current = _read_recovery(data_dir)
    if current.value.get("missing"):
        return {"missing_checkpoint": True, "revision": 0, "workspace": {}, "observations": [],
                "files": [], "jobs": [], "legacy_job": _legacy_job(data_dir),
                "fresh_read_required": True}
    doc = deepcopy(current.value)
    docs = []
    for raw in doc.get("observations", []):
        decoded = observations.Observation.from_dict(raw)
        if decoded.value is None:
            continue
        historical = observations.as_historical(decoded.value)
        docs.append({**historical.to_dict(), "usable_for_loadout": False})
    files = []
    for item in doc.get("files", []):
        if not isinstance(item, dict):
            continue
        ref_decoded = artifacts.ArtifactRef.from_dict(item.get("artifact"))
        state = ("unverified" if ref_decoded.value is None
                 else artifacts.same_bytes(ref_decoded.value, localpath.usable_path(item.get("path"))))
        files.append({"name": item.get("name", "Unknown file"), "state": state,
                      "association": "unverified"})
    jobs = []
    for job in doc.get("jobs", []):
        if isinstance(job, dict):
            state = job.get("state")
            interrupted = state in ("queued", "running", "cancel_requested")
            jobs.append({"job_id": job.get("job_id"),
                         "state": "interrupted" if interrupted else state, "replayed": False})
    return {"missing_checkpoint": False, "revision": doc.get("revision", 0),
            "checkpointed_at": doc.get("checkpointed_at"), "workspace": doc.get("workspace", {}),
            "observations": docs, "files": files, "jobs": jobs,
            "legacy_job": doc.get("legacy_job") or _legacy_job(data_dir),
            "fresh_read_required": True}
