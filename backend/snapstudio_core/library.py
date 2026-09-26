"""Local project library — a SQLite *index* of what the user has opened and
converted. It stores file PATHS + the doctor/convert summary, never file
contents (files stay where the user keeps them; local-first). Pure stdlib
(`sqlite3`), so it freezes cleanly in the sidecar.

Dates are ISO-8601 UTC strings (e.g. "2026-06-18T20:00:00Z"). Callers pass the
timestamp in (the engine never reads the wall clock itself), keeping it testable.
"""
from __future__ import annotations
import sqlite3
from collections.abc import Callable

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  source_path TEXT NOT NULL UNIQUE,
  source_family TEXT,
  output_path TEXT,
  verdict TEXT,
  score INTEGER,
  filament_count INTEGER,
  last_action TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS project_tags (
  project_id INTEGER, tag_id INTEGER,
  PRIMARY KEY (project_id, tag_id)
);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY, project_id INTEGER,
  action TEXT, detail TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS spools (
  id INTEGER PRIMARY KEY,
  host TEXT NOT NULL,
  slot INTEGER NOT NULL,
  material TEXT,
  subtype TEXT,
  color TEXT,
  vendor TEXT,
  starting_g REAL,
  remaining_g REAL,
  remaining_quality TEXT,
  remaining_as_of TEXT,
  notes TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(host, slot)
);
"""


class LibraryVersionError(RuntimeError):
    """The library DB was written by a newer app version than this one understands."""


# version N -> N+1 migration callables. Empty until the schema actually evolves;
# add migrations here (e.g. _MIGRATIONS[1] = _v1_to_v2) when bumping SCHEMA_VERSION.
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the DB to SCHEMA_VERSION. Checks the recorded ``PRAGMA user_version``
    FIRST: a newer DB is refused without touching it. Otherwise applies the additive
    `CREATE TABLE IF NOT EXISTS` schema and runs migrations. Never drops/rewrites rows."""
    cur = conn.execute("PRAGMA user_version").fetchone()[0]
    if cur > SCHEMA_VERSION:
        raise LibraryVersionError(
            f"library DB is version {cur} but this app supports {SCHEMA_VERSION}; "
            "update Snapmaker Studio to open it.")
    conn.executescript(_SCHEMA)
    if cur == SCHEMA_VERSION:
        return
    # cur < SCHEMA_VERSION: a fresh DB (0) or an older one. The base schema matches
    # version 1, so jump 0->1 with no data change; run any registered step migrations.
    for v in range(max(cur, 1), SCHEMA_VERSION):
        mig = _MIGRATIONS.get(v)
        if mig:
            mig(conn)
    with conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _migrate(conn)
    except Exception:
        conn.close()   # don't leak the connection if migration refuses the DB
        raise
    return conn


def upsert_project(conn: sqlite3.Connection, *, name: str, source_path: str,
                   source_family: str | None = None, output_path: str | None = None,
                   verdict: str | None = None, score: int | None = None,
                   filament_count: int | None = None, last_action: str | None = None,
                   updated_at: str) -> int:
    """Insert or update a project keyed by source_path. Returns the row id."""
    with conn:
        conn.execute(
            """INSERT INTO projects
                 (name, source_path, source_family, output_path, verdict, score,
                  filament_count, last_action, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_path) DO UPDATE SET
                 name=excluded.name, source_family=excluded.source_family,
                 output_path=COALESCE(excluded.output_path, projects.output_path),
                 verdict=excluded.verdict, score=excluded.score,
                 filament_count=excluded.filament_count,
                 last_action=excluded.last_action, updated_at=excluded.updated_at""",
            (name, source_path, source_family, output_path, verdict, score,
             filament_count, last_action, updated_at),
        )
    row = conn.execute("SELECT id FROM projects WHERE source_path=?", (source_path,)).fetchone()
    return int(row["id"])


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def search_projects(conn: sqlite3.Connection, query: str = "", tag: str | None = None) -> list[dict]:
    sql = "SELECT p.* FROM projects p"
    params: list = []
    if tag:
        sql += (" JOIN project_tags pt ON pt.project_id=p.id"
                " JOIN tags t ON t.id=pt.tag_id AND t.name=?")
        params.append(tag)
    if query:
        sql += (" WHERE " if "WHERE" not in sql else " AND ") + "p.name LIKE ?"
        params.append(f"%{query}%")
    sql += " ORDER BY p.updated_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM project_tags WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM history WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def add_tag(conn: sqlite3.Connection, project_id: int, tag: str) -> None:
    with conn:
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (tag,))
        tid = conn.execute("SELECT id FROM tags WHERE name=?", (tag,)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO project_tags(project_id, tag_id) VALUES (?,?)",
                     (project_id, tid))


def add_history(conn: sqlite3.Connection, project_id: int, action: str, detail: str, at: str) -> None:
    with conn:
        conn.execute("INSERT INTO history(project_id, action, detail, at) VALUES (?,?,?,?)",
                     (project_id, action, detail, at))


def get_history(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM history WHERE project_id=? ORDER BY at DESC",
                        (project_id,)).fetchall()
    return [dict(r) for r in rows]


# --- local/manual spools -----------------------------------------------------
#
# A person's own record of what is on a spool, for a printer that has no
# Spoolman or Bambuddy — or for a slot neither of those tracks. Keyed by the
# printer's address plus the slot number, exactly like the U1 connection
# itself is addressed everywhere else in Studio: local-only, never synced,
# never read by anything but the person who typed it in.

def upsert_spool(conn: sqlite3.Connection, *, host: str, slot: int,
                 material: str | None, subtype: str | None, color: str | None,
                 vendor: str | None, starting_g: float | None,
                 remaining_g: float | None, remaining_quality: str | None,
                 remaining_as_of: str | None, notes: str | None,
                 updated_at: str) -> int:
    """Insert or update one local spool record, keyed by (host, slot)."""
    with conn:
        conn.execute(
            """INSERT INTO spools
                 (host, slot, material, subtype, color, vendor, starting_g,
                  remaining_g, remaining_quality, remaining_as_of, notes, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(host, slot) DO UPDATE SET
                 material=excluded.material, subtype=excluded.subtype,
                 color=excluded.color, vendor=excluded.vendor,
                 starting_g=excluded.starting_g, remaining_g=excluded.remaining_g,
                 remaining_quality=excluded.remaining_quality,
                 remaining_as_of=excluded.remaining_as_of, notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (host, slot, material, subtype, color, vendor, starting_g, remaining_g,
             remaining_quality, remaining_as_of, notes, updated_at),
        )
    row = conn.execute("SELECT id FROM spools WHERE host=? AND slot=?", (host, slot)).fetchone()
    return int(row["id"])


def list_spools(conn: sqlite3.Connection, host: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM spools WHERE host=? ORDER BY slot",
                        (host,)).fetchall()
    return [dict(r) for r in rows]


def get_spool(conn: sqlite3.Connection, host: str, slot: int) -> dict | None:
    row = conn.execute("SELECT * FROM spools WHERE host=? AND slot=?",
                       (host, slot)).fetchone()
    return dict(row) if row else None


def delete_spool(conn: sqlite3.Connection, host: str, slot: int) -> None:
    with conn:
        conn.execute("DELETE FROM spools WHERE host=? AND slot=?", (host, slot))


def apply_spool_usage(conn: sqlite3.Connection, *, host: str, slot: int,
                      used_g: float, remaining_quality: str,
                      at: str) -> dict | None:
    """Subtract a confirmed amount used from a spool's remaining weight.

    Only ever called from the one place a person explicitly confirmed "mark
    this much used" — never as a side effect of slicing, sending or printing.
    A spool Studio has no record of, or with no remaining weight to subtract
    from, is left alone rather than guessed at; the caller gets None either
    way and must not invent a row.
    """
    existing = get_spool(conn, host, slot)
    if not existing or existing.get("remaining_g") is None:
        return None
    remaining = max(0.0, round(float(existing["remaining_g"]) - float(used_g), 1))
    with conn:
        conn.execute(
            """UPDATE spools SET remaining_g=?, remaining_quality=?, remaining_as_of=?,
                 updated_at=? WHERE host=? AND slot=?""",
            (remaining, remaining_quality, at, at, host, slot))
    return get_spool(conn, host, slot)
