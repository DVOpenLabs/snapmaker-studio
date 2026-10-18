"""Is a saved job's file still the file the job was made from?

After a restart Studio can offer to pick a job back up: the project that came in,
the prepared copy it wrote, and the sliced G-code that came back. Any of them may
have been moved, deleted or overwritten since. This compares each against the
size and SHA-256 recorded when the job was linked, and reports what it can vouch
for. A file it cannot read, or is too large to hash, is never reported as the same.

It only reads. It does not prepare, slice, send or open anything.
"""
from __future__ import annotations

import hashlib
import os

SCHEMA_VERSION = "job-check/1"

ROLES = ("original", "prepared", "sliced")

#: A job is three files, not a library.
MAX_ENTRIES = 8

#: Hashing is a full read. Past this, identity is size-only and says so.
MAX_HASH_BYTES = 1024 * 1024 * 1024

_CHUNK = 1024 * 1024


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _expectation(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("expected must be an object")
    size, sha = raw.get("size_bytes"), raw.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("expected.size_bytes must be a non-negative integer")
    if sha is not None and not (isinstance(sha, str) and len(sha) == 64):
        raise ValueError("expected.sha256 must be a 64-character hex string or null")
    return {"size_bytes": size, "sha256": sha}


def _check_one(role: str, path: str, expected: dict | None) -> dict:
    out = {"role": role, "path": path}
    try:
        if not os.path.exists(path):
            return {**out, "status": "missing"}
        if not os.path.isfile(path):
            return {**out, "status": "unreadable", "reason": "not a regular file"}
        size = os.stat(path).st_size
        # A size that differs is already a different file; no need to read it.
        if expected is not None and size != expected["size_bytes"]:
            return {**out, "status": "changed", "observed": {"size_bytes": size, "sha256": None}}
        sha = _sha256(path) if size <= MAX_HASH_BYTES else None
        observed = {"size_bytes": size, "sha256": sha}
    except OSError as exc:
        return {**out, "status": "unreadable", "reason": exc.__class__.__name__}

    if expected is None:
        return {**out, "status": "recorded", "observed": observed}
    if sha is None or expected["sha256"] is None:
        return {**out, "status": "unverified", "observed": observed}
    return {**out, "status": "same" if sha == expected["sha256"] else "changed", "observed": observed}


def check(entries: list[dict]) -> dict:
    """Report, per file and in the order given, whether it is still what was recorded.

    Each entry is `{role, path, expected?}` with `expected = {size_bytes, sha256}`.
    Without `expected` the file is only fingerprinted (status `recorded`).
    """
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError(f"at most {MAX_ENTRIES} files can be checked")
    files = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each file must be an object")
        role, path = entry.get("role"), entry.get("path")
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        files.append(_check_one(role, path, _expectation(entry.get("expected"))))
    return {"schema_version": SCHEMA_VERSION, "files": files}
