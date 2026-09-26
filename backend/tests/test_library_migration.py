"""library.py schema-version / migration scaffold."""
import sqlite3

import pytest

from snapstudio_core import library


def test_new_db_initialized_to_the_current_version(tmp_path):
    conn = library.connect(str(tmp_path / "new.db"))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == library.SCHEMA_VERSION
    finally:
        conn.close()


def test_existing_unversioned_db_migrated_without_data_loss(tmp_path):
    db = str(tmp_path / "old.db")
    # simulate a pre-versioning DB: schema present, user_version 0, one real row
    raw = sqlite3.connect(db)
    raw.executescript(library._SCHEMA)
    raw.execute("PRAGMA user_version = 0")
    raw.execute("INSERT INTO projects (name, source_path, updated_at) VALUES (?,?,?)",
                ("cube", "/x/cube.3mf", "2026-06-22T00:00:00Z"))
    raw.commit(); raw.close()

    conn = library.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == library.SCHEMA_VERSION
        rows = conn.execute("SELECT name, source_path FROM projects").fetchall()
        assert len(rows) == 1 and rows[0][0] == "cube"   # data preserved
    finally:
        conn.close()


def test_a_real_version_1_db_gains_the_spools_table_without_data_loss(tmp_path):
    """A DB written before this session's spools table existed — the schema at
    user_version 1, one real project row, no spools table — opens cleanly and
    gains the new table with nothing lost."""
    db = str(tmp_path / "v1.db")
    raw = sqlite3.connect(db)
    raw.executescript("""
        CREATE TABLE projects (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, source_path TEXT NOT NULL UNIQUE,
          source_family TEXT, output_path TEXT, verdict TEXT, score INTEGER,
          filament_count INTEGER, last_action TEXT, updated_at TEXT
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE project_tags (project_id INTEGER, tag_id INTEGER,
          PRIMARY KEY (project_id, tag_id));
        CREATE TABLE history (id INTEGER PRIMARY KEY, project_id INTEGER,
          action TEXT, detail TEXT, at TEXT);
    """)
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO projects (name, source_path, updated_at) VALUES (?,?,?)",
                ("cube", "/x/cube.3mf", "2026-06-22T00:00:00Z"))
    raw.commit(); raw.close()

    conn = library.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == library.SCHEMA_VERSION
        rows = conn.execute("SELECT name FROM projects").fetchall()
        assert len(rows) == 1 and rows[0][0] == "cube"
        library.upsert_spool(conn, host="u1.local", slot=0, material="PLA", subtype=None,
                             color="#FF0000", vendor=None, starting_g=1000, remaining_g=800,
                             remaining_quality="user_confirmed", remaining_as_of="2026-09-26T00:00:00Z",
                             notes=None, updated_at="2026-09-26T00:00:00Z")
        assert len(library.list_spools(conn, "u1.local")) == 1
    finally:
        conn.close()


def test_future_version_fails_safely(tmp_path):
    db = str(tmp_path / "future.db")
    raw = sqlite3.connect(db)
    raw.executescript(library._SCHEMA)
    raw.execute(f"PRAGMA user_version = {library.SCHEMA_VERSION + 5}")
    raw.commit(); raw.close()

    with pytest.raises(library.LibraryVersionError):
        library.connect(db)
