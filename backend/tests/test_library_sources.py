"""project_sources: the additive provenance table beside the library index."""
import sqlite3

from snapstudio_core import library

_SRC = dict(site="printables.com", page_url="https://www.printables.com/model/1-x",
            filename="x.3mf", sha256="a" * 64, size_bytes=10, imported_at="2026-10-05T00:00:00Z")


def _project(conn, path="/x/a.3mf"):
    return library.upsert_project(conn, name="a.3mf", source_path=path, updated_at="2026-10-05T00:00:00Z")


def test_schema_version_and_projects_columns_unchanged(tmp_path):
    assert library.SCHEMA_VERSION == 2
    conn = library.connect(str(tmp_path / "l.db"))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)")]
        assert cols == ["id", "name", "source_path", "source_family", "output_path",
                        "verdict", "score", "filament_count", "last_action", "updated_at"]
        src = [(r[1], r[2], r[3], r[5]) for r in conn.execute("PRAGMA table_info(project_sources)")]
        assert src == [("project_id", "INTEGER", 0, 1), ("site", "TEXT", 1, 0),
                       ("page_url", "TEXT", 0, 0), ("filename", "TEXT", 1, 0),
                       ("sha256", "TEXT", 1, 0), ("size_bytes", "INTEGER", 1, 0),
                       ("imported_at", "TEXT", 1, 0)]
    finally:
        conn.close()


def test_upsert_get_list_and_overwrite(tmp_path):
    conn = library.connect(str(tmp_path / "l.db"))
    try:
        pid = _project(conn)
        assert library.get_source(conn, pid) is None
        library.upsert_source(conn, project_id=pid, **_SRC)
        assert library.get_source(conn, pid) == {"project_id": pid, **_SRC}
        library.upsert_source(conn, project_id=pid, **{**_SRC, "page_url": None, "size_bytes": 11})
        got = library.get_source(conn, pid)
        assert got["page_url"] is None and got["size_bytes"] == 11
        assert conn.execute("SELECT COUNT(*) FROM project_sources").fetchone()[0] == 1
        assert list(library.list_sources(conn)) == [pid]
        assert "site" not in library.list_projects(conn)[0]   # list_projects stays join-free
    finally:
        conn.close()


def test_delete_project_removes_its_source_only(tmp_path):
    conn = library.connect(str(tmp_path / "l.db"))
    try:
        a, b = _project(conn, "/x/a.3mf"), _project(conn, "/x/b.3mf")
        library.upsert_source(conn, project_id=a, **_SRC)
        library.upsert_source(conn, project_id=b, **_SRC)
        library.delete_project(conn, a)
        assert library.get_source(conn, a) is None
        assert library.get_source(conn, b) is not None
    finally:
        conn.close()


def test_older_db_without_the_table_opens_and_gains_it(tmp_path):
    db = str(tmp_path / "old.db")
    raw = sqlite3.connect(db)
    raw.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
          source_path TEXT NOT NULL UNIQUE, source_family TEXT, output_path TEXT,
          verdict TEXT, score INTEGER, filament_count INTEGER, last_action TEXT, updated_at TEXT);
    """)
    raw.execute("PRAGMA user_version = 2")
    raw.execute("INSERT INTO projects (name, source_path, updated_at) VALUES ('c','/x/c.3mf','t')")
    raw.commit()
    raw.close()
    conn = library.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        pid = conn.execute("SELECT id FROM projects").fetchone()[0]
        library.upsert_source(conn, project_id=pid, **_SRC)
        assert library.get_source(conn, pid)["site"] == "printables.com"
    finally:
        conn.close()
