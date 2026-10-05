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

# Bumping this is a ONE-WAY upgrade for whoever's local DB was already at a
# lower version: `_migrate` refuses (LibraryVersionError, never silently
# downgrades or drops data) to open a DB whose recorded `user_version` is
# HIGHER than what the running app understands. A person who upgrades
# Studio, opens it once (migrating their local library.db to this version),
# and then reinstalls an older release will see that refusal on their own
# library until they upgrade again. There is no reverse migration — schema
# changes here are additive only, and going backwards is not supported.
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
CREATE TABLE IF NOT EXISTS nozzle_confirmations (
  host TEXT NOT NULL,
  port INTEGER NOT NULL,
  toolhead INTEGER NOT NULL,
  diameter REAL,
  confirmed_at TEXT,
  PRIMARY KEY (host, port, toolhead)
);
CREATE TABLE IF NOT EXISTS nozzle_confirmation_meta (
  host TEXT NOT NULL,
  port INTEGER NOT NULL,
  revision INTEGER NOT NULL,
  PRIMARY KEY (host, port)
);
CREATE TABLE IF NOT EXISTS project_sources (
  project_id INTEGER PRIMARY KEY,
  site TEXT NOT NULL,
  page_url TEXT,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  imported_at TEXT NOT NULL
);
"""
# v1.2 added `nozzle_confirmations` and `nozzle_confirmation_meta` above as
# CREATE TABLE IF NOT EXISTS statements. This does NOT bump SCHEMA_VERSION: a
# v1.1.0 install opening a DB that merely carries two extra tables it has
# never heard of is harmless (it never queries them), so refusing that DB
# would only break downgrade for no protective gain. Only a change to an
# EXISTING table's shape, or new data an older version would misinterpret,
# is worth the one-way refusal SCHEMA_VERSION guards. v1.4 adds `project_sources`
# (where an in-app Model Browser download came from) on the same terms.


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
        conn.execute("DELETE FROM project_sources WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def upsert_source(conn: sqlite3.Connection, *, project_id: int, site: str,
                  page_url: str | None, filename: str, sha256: str,
                  size_bytes: int, imported_at: str) -> None:
    """Record where a project's file came from (one row per project)."""
    with conn:
        conn.execute(
            """INSERT INTO project_sources
                 (project_id, site, page_url, filename, sha256, size_bytes, imported_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                 site=excluded.site, page_url=excluded.page_url,
                 filename=excluded.filename, sha256=excluded.sha256,
                 size_bytes=excluded.size_bytes, imported_at=excluded.imported_at""",
            (project_id, site, page_url, filename, sha256, size_bytes, imported_at))


def get_source(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM project_sources WHERE project_id=?",
                       (project_id,)).fetchone()
    return dict(row) if row else None


def list_sources(conn: sqlite3.Connection) -> dict[int, dict]:
    """Every provenance row keyed by project_id (list_projects stays join-free)."""
    return {r["project_id"]: dict(r)
            for r in conn.execute("SELECT * FROM project_sources").fetchall()}


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


def get_spool_by_id(conn: sqlite3.Connection, spool_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM spools WHERE id=?", (spool_id,)).fetchone()
    return dict(row) if row else None


def delete_spool_by_id(conn: sqlite3.Connection, spool_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM spools WHERE id=?", (spool_id,))


def rewrite_spool_host(conn: sqlite3.Connection, *, old_host: str, slot: int, new_host: str) -> None:
    """A2.5/A1.3: fold exactly one legacy alias into its canonical spelling,
    in place — every field kept, only the host string changes. Only ever
    called when the caller has already proven there is no OTHER row already
    at (new_host, slot) (a second alias, or the canonical row itself), so the
    UNIQUE(host, slot) constraint can never be hit here."""
    if old_host == new_host:
        return
    with conn:
        conn.execute("UPDATE spools SET host=? WHERE host=? AND slot=?",
                     (new_host, old_host, slot))


def list_all_spools(conn: sqlite3.Connection) -> list[dict]:
    """Every local spool row, across every host as stored. Used to detect two
    stored host spellings that canonicalise to the same printer (an alias
    collision) — the per-host lookups above cannot see that on their own."""
    rows = conn.execute("SELECT * FROM spools ORDER BY host, slot").fetchall()
    return [dict(r) for r in rows]


# --- per-printer, per-toolhead nozzle confirmations --------------------------
#
# A person's own record of which nozzle is fitted, for a printer/firmware that
# does not report it live. Keyed by (canonical host, port) — never the raw
# string the user typed, so "U1.local " and "u1.local" share one record. A
# monotonic `revision` in `nozzle_confirmation_meta` never regresses and is
# never deleted (clearing leaves the meta row as a tombstone), so a stale
# desktop write can always be detected and refused (409) rather than silently
# clobbering a newer one.

class StaleRevision(RuntimeError):
    """`expected_revision` did not match the stored revision. Carries the
    current one so the caller can tell the user to reload."""

    def __init__(self, current_revision: int):
        super().__init__("stale")
        self.current_revision = current_revision


def _ensure_nozzle_meta_row(conn: sqlite3.Connection, host: str, port: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO nozzle_confirmation_meta(host, port, revision) VALUES (?, ?, 0)",
        (host, port))


def get_nozzle_confirmations(conn: sqlite3.Connection, host: str,
                             port: int) -> tuple[dict[int, dict], int]:
    """Every confirmed toolhead for (host, port), keyed by toolhead index, plus
    the current revision. B3 (Opus M1): a pure read — never inserts the meta
    tombstone row itself (a printer nobody has ever confirmed anything for
    simply has no meta row, and reads revision 0); only `confirm`/`clear`
    (which need a row to conditionally UPDATE) create it, inside their own
    write transaction."""
    rows = conn.execute(
        "SELECT toolhead, diameter, confirmed_at FROM nozzle_confirmations "
        "WHERE host=? AND port=? ORDER BY toolhead", (host, port)).fetchall()
    rev_row = conn.execute(
        "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
        (host, port)).fetchone()
    revision = int(rev_row["revision"]) if rev_row else 0
    confirmed = {int(r["toolhead"]): {"diameter": r["diameter"], "confirmed_at": r["confirmed_at"]}
                for r in rows}
    return confirmed, revision


def _bump_nozzle_revision(conn: sqlite3.Connection, host: str, port: int,
                          expected_revision: int) -> int:
    """One conditional write, checked by rowcount: the whole concurrency guard.
    Two connections racing the same `expected_revision` can only ever produce
    one success and one `StaleRevision` — never a lost update."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_nozzle_meta_row(conn, host, port)
        cur = conn.execute(
            "UPDATE nozzle_confirmation_meta SET revision = revision + 1 "
            "WHERE host=? AND port=? AND revision=?", (host, port, expected_revision))
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
                (host, port)).fetchone()
            conn.rollback()
            raise StaleRevision(int(row["revision"]) if row else 0)
        row = conn.execute(
            "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
            (host, port)).fetchone()
        new_revision = int(row["revision"])
        conn.commit()
        return new_revision
    except sqlite3.OperationalError:
        conn.rollback()
        raise


def replace_nozzle_confirmations(conn: sqlite3.Connection, host: str, port: int,
                                 diameters: list[float | None], at: str,
                                 expected_revision: int) -> int:
    """Atomic replace of every toolhead's confirmation for (host, port).

    Bumping the revision and writing the rows happen in the SAME transaction
    that the revision check guards, so a losing writer never gets to touch a
    row at all — it raises `StaleRevision` before the DELETE/INSERT below run.
    ``None`` in `diameters` means "not sure": stored as an explicit row with no
    diameter and no timestamp, distinct from a toolhead nobody has ever confirmed.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_nozzle_meta_row(conn, host, port)
        cur = conn.execute(
            "UPDATE nozzle_confirmation_meta SET revision = revision + 1 "
            "WHERE host=? AND port=? AND revision=?", (host, port, expected_revision))
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
                (host, port)).fetchone()
            conn.rollback()
            raise StaleRevision(int(row["revision"]) if row else 0)
        conn.execute("DELETE FROM nozzle_confirmations WHERE host=? AND port=?", (host, port))
        for toolhead, diameter in enumerate(diameters):
            conn.execute(
                "INSERT INTO nozzle_confirmations(host, port, toolhead, diameter, confirmed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (host, port, toolhead, diameter, at if diameter is not None else None))
        row = conn.execute(
            "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
            (host, port)).fetchone()
        new_revision = int(row["revision"])
        conn.commit()
        return new_revision
    except sqlite3.OperationalError:
        conn.rollback()
        raise


def clear_nozzle_confirmations(conn: sqlite3.Connection, host: str, port: int,
                               expected_revision: int) -> int:
    """Remove every stored confirmation for (host, port). The meta row (and its
    revision, freshly bumped) is kept — a tombstone, so a later confirm/clear
    can still be revision-guarded against a desktop that never reloaded."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_nozzle_meta_row(conn, host, port)
        cur = conn.execute(
            "UPDATE nozzle_confirmation_meta SET revision = revision + 1 "
            "WHERE host=? AND port=? AND revision=?", (host, port, expected_revision))
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
                (host, port)).fetchone()
            conn.rollback()
            raise StaleRevision(int(row["revision"]) if row else 0)
        conn.execute("DELETE FROM nozzle_confirmations WHERE host=? AND port=?", (host, port))
        row = conn.execute(
            "SELECT revision FROM nozzle_confirmation_meta WHERE host=? AND port=?",
            (host, port)).fetchone()
        new_revision = int(row["revision"])
        conn.commit()
        return new_revision
    except sqlite3.OperationalError:
        conn.rollback()
        raise
