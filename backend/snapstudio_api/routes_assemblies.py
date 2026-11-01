"""Routes of the Assemblies track: plan a multi-tile project against shared spools.

    POST /assemblies/evaluate  {assembly, supply?, now?}                 -> {report}
    POST /assemblies/save      {assembly, id?, expected_revision?}       -> {id, revision, assembly}
    POST /assemblies/list      {}                                        -> {assemblies}
    POST /assemblies/get       {id}                                      -> {id, revision, assembly}
    POST /assemblies/delete    {id}                                      -> {deleted}

Everything here is local arithmetic and local files: no network request of its own, no printer, no
model file is written (file-path checks are best-effort, see snapstudio_core/localpath.py). The library is only read (to say whether a tile's project is still there and unchanged).
The verdicts are advisory.
"""
from __future__ import annotations

import hashlib
import os
from snapstudio_core import localpath
import sqlite3

from snapstudio_core import paths
from snapstudio_core.assemblies import evaluate as ev
from snapstudio_core.assemblies import store
from snapstudio_core.assemblies.model import AssemblyInputError, read_assembly
from snapstudio_core.foundation.decode import is_finite_number

from . import ext_routes
from . import request_validation as rv

#: A library file larger than this is not re-hashed inside a request; its tile says "unverified".
MAX_HASH_BYTES = 256 * 1024 * 1024


def _refused(exc: AssemblyInputError) -> rv.ValidationError:
    return rv.ValidationError(str(exc))


def _id(data: dict) -> int:
    value = data.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise rv.ValidationError("Missing or invalid 'id'")
    return value


def _now(data: dict):
    value = data.get("now")
    if value is None:
        return None
    if not is_finite_number(value) or value < 0:
        raise rv.ValidationError("Invalid 'now'")
    return value


def _sha256_of(path: str) -> str | None:
    if not localpath.is_local_regular_file(path, max_bytes=MAX_HASH_BYTES):
        return None
    try:
        if os.path.getsize(path) > MAX_HASH_BYTES:
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def library_lookup(project_id: int) -> dict | None:
    """The library row for `project_id`, read-only: {sha256} of its source file, or None when it is gone.

    Opens `library.db` read-only and never creates it; a missing library means no project is in it.
    """
    db = os.path.join(paths.data_dir(create=False), "library.db")
    if not os.path.isfile(db):
        return None
    uri = "file:" + db.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = conn.execute("SELECT source_path FROM projects WHERE id=?", (project_id,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"sha256": None}                      # a locked or unfamiliar library leaves the tile unverified
    if row is None:
        return None
    return {"sha256": _sha256_of(row[0]) if isinstance(row[0], str) else None}


@ext_routes.route("/assemblies/evaluate")
def evaluate(data: dict) -> tuple[int, dict]:
    try:
        assembly = read_assembly(data.get("assembly"))
        now = _now(data)
        supply = ev.read_supply(data.get("supply"), now)
    except AssemblyInputError as exc:
        raise _refused(exc) from None
    lookup = library_lookup if any(t.library is not None for t in assembly.tiles) else None
    return 200, {"report": ev.evaluate(assembly, supply, now=now, lookup=lookup)}


@ext_routes.route("/assemblies/save")
def save(data: dict) -> tuple[int, dict]:
    expected = data.get("expected_revision")
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 0):
        raise rv.ValidationError("Invalid 'expected_revision'")
    assembly_id = _id(data) if data.get("id") is not None else None
    try:
        return 200, store.save(data.get("assembly"), assembly_id, expected)
    except AssemblyInputError as exc:
        raise _refused(exc) from None


@ext_routes.route("/assemblies/list")
def list_saved(data: dict) -> tuple[int, dict]:
    return 200, {"assemblies": store.list_saved()}


@ext_routes.route("/assemblies/get")
def get(data: dict) -> tuple[int, dict]:
    try:
        return 200, store.get(_id(data))
    except AssemblyInputError as exc:
        raise _refused(exc) from None


@ext_routes.route("/assemblies/delete")
def delete(data: dict) -> tuple[int, dict]:
    return 200, {"deleted": store.delete(_id(data))}
