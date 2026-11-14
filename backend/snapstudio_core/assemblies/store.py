"""`assemblies.db`: saved assembly definitions, through `foundation.store`.

Only definitions are saved. Spool readings are time-sensitive, so supply is supplied with each
evaluation and never stored. `tile_refs` records which library project (id + sha256) each tile
points at so "which assemblies use this project" is one query; it has no foreign key into the
library, which is a different database that the user can change or delete from.
"""
from __future__ import annotations

import datetime
import json
from typing import Any

from snapstudio_core.foundation import store as fstore

from .model import Assembly, AssemblyInputError, read_assembly

STORE_NAME = "assemblies"
VERSION = 1
MAX_SAVED = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assemblies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  doc TEXT NOT NULL,
  revision INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tile_refs (
  assembly_id INTEGER NOT NULL,
  tile_id TEXT NOT NULL,
  library_project_id INTEGER NOT NULL,
  library_sha256 TEXT,
  PRIMARY KEY (assembly_id, tile_id)
);
CREATE INDEX IF NOT EXISTS tile_refs_by_project ON tile_refs (library_project_id);
"""


class NotFound(AssemblyInputError):
    """No saved assembly has that id."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open():
    return fstore.open_store(STORE_NAME, _SCHEMA, VERSION)


def _refs(assembly: Assembly) -> list:
    return [(t.tile_id, t.library.project_id, t.library.sha256) for t in assembly.tiles if t.library is not None]


def save(raw: Any, assembly_id: int | None = None, expected_revision: int | None = None) -> dict:
    """Validate and store `raw`. New when `assembly_id` is None. An update must name the revision it
    was read at; a different stored revision is a `RevisionConflict` and nothing is written."""
    assembly = read_assembly(raw)
    doc = json.dumps(assembly.to_dict(), sort_keys=True, separators=(",", ":"))
    with _open() as conn:
        with fstore.transaction(conn):
            if assembly_id is None:
                if conn.execute("SELECT COUNT(*) FROM assemblies").fetchone()[0] >= MAX_SAVED:
                    raise AssemblyInputError("There are too many saved assemblies. Delete one first.")
                cur = conn.execute("INSERT INTO assemblies (name, doc, revision, updated_at) VALUES (?,?,?,?)",
                                   (assembly.name, doc, 1, _now()))
                assembly_id, revision = int(cur.lastrowid), 1
            else:
                row = conn.execute("SELECT revision FROM assemblies WHERE id=?", (assembly_id,)).fetchone()
                if row is None:
                    raise NotFound("That assembly is not saved.")
                if expected_revision is None or row[0] != expected_revision:
                    raise fstore.RevisionConflict("the document changed since it was read")
                revision = row[0] + 1
                conn.execute("UPDATE assemblies SET name=?, doc=?, revision=?, updated_at=? WHERE id=?",
                             (assembly.name, doc, revision, _now(), assembly_id))
                conn.execute("DELETE FROM tile_refs WHERE assembly_id=?", (assembly_id,))
            conn.executemany("INSERT INTO tile_refs VALUES (?,?,?,?)",
                             [(assembly_id, t, p, s) for t, p, s in _refs(assembly)])
    return {"id": assembly_id, "revision": revision, "assembly": assembly.to_dict()}


def get(assembly_id: int) -> dict:
    with _open() as conn:
        row = conn.execute("SELECT id, doc, revision, updated_at FROM assemblies WHERE id=?",
                           (assembly_id,)).fetchone()
    if row is None:
        raise NotFound("That assembly is not saved.")
    return {"id": row[0], "revision": row[2], "updated_at": row[3], "assembly": json.loads(row[1])}


def list_saved() -> list:
    with _open() as conn:
        rows = conn.execute("SELECT id, name, doc, revision, updated_at FROM assemblies "
                            "ORDER BY updated_at DESC, id DESC").fetchall()
    return [{"id": r[0], "name": r[1], "tiles": len(json.loads(r[2]).get("tiles", [])),
             "revision": r[3], "updated_at": r[4]} for r in rows]


def delete(assembly_id: int) -> bool:
    """Remove a saved definition. Never touches a library project or any model file."""
    with _open() as conn:
        with fstore.transaction(conn):
            conn.execute("DELETE FROM tile_refs WHERE assembly_id=?", (assembly_id,))
            cur = conn.execute("DELETE FROM assemblies WHERE id=?", (assembly_id,))
    return cur.rowcount > 0


def assemblies_for_project(project_id: int, sha256: str | None = None) -> list:
    """Saved assemblies with a tile that points at this library project (and checksum, when given)."""
    sql = ("SELECT r.assembly_id, a.name, r.tile_id, r.library_sha256 FROM tile_refs r "
           "JOIN assemblies a ON a.id = r.assembly_id WHERE r.library_project_id=?")
    args: list = [project_id]
    if sha256 is not None:
        sql += " AND r.library_sha256=?"
        args.append(sha256.lower())
    with _open() as conn:
        rows = conn.execute(sql + " ORDER BY r.assembly_id, r.tile_id", args).fetchall()
    return [{"assembly_id": r[0], "name": r[1], "tile_id": r[2], "sha256": r[3]} for r in rows]
