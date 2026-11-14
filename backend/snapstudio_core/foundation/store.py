"""Local persistence: SQLite stores and revision-checked JSON documents.

Everything lives under `paths.data_dir()`; store names and schemas come from code constants,
never from request bodies. Nothing here touches the network or starts processes.

SQLite: `open_store` opens one file per name, one connection per call (never shared across the
threads of the HTTP server), `isolation_level=None` with explicit `BEGIN IMMEDIATE`, a busy
timeout, and transactional migrations (never `executescript`). A database whose `user_version`
is newer than the code is refused before anything is written.

JSON: `write_json` is revision-checked and atomic (unique same-directory temp file, flush +
fsync, `os.replace` with bounded retries for Windows sharing violations). Writers are
serialised inside a process by a thread lock and across processes by an OS advisory lock on
`<document>.lock` (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows). The OS drops the lock when
the holder exits or is killed, so there is no staleness protocol and no lock-file reclamation: the
lock file is never deleted and may persist, and its contents (pid, token, time) are diagnostics only.
Limits: local filesystems only (advisory locking on network shares is not guaranteed); the lock
protects two Studio sidecars from each other, not external tools editing the files.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from typing import Any, Iterator, Sequence

from snapstudio_core import paths as _paths

from .decode import Decoded, ERROR, diag

MAX_JSON_BYTES = 16 * 1024 * 1024
BUSY_TIMEOUT_MS = 5000
REPLACE_ATTEMPTS = 5
REPLACE_SLEEP_S = 0.02
LOCK_MAX_AGE_S = 60.0                # accepted for API compatibility; OS locks need no staleness limit
LOCK_WAIT_S = 5.0
LOCK_POLL_S = 0.01
_LOCK_OFFSET = 0x40000000            # Windows: the byte that is locked lies far past the diagnostics text
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_SCHEMA_RE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)/(?P<ver>\d+)$")


class StoreError(Exception):
    """Base class of refusals from this module. Messages never carry document content."""


class StoreVersionError(StoreError):
    """The data on disk was written by a newer Studio. It is left untouched."""


class RevisionConflict(StoreError):
    """The document changed since the caller read it."""


class StoreLockError(StoreError):
    """Another live writer holds the lock."""


class StoreTooLarge(StoreError):
    """A document exceeds `MAX_JSON_BYTES`."""


# test seams
_replace = os.replace
_sleep = time.sleep
_clock = time.time


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError("invalid store name")
    return name


def store_dir(data_dir: str | None = None) -> str:
    path = os.path.join(_paths.data_dir(data_dir), "store")
    os.makedirs(path, exist_ok=True)
    return path


# ============================================================================ SQLite
def split_statements(sql: str) -> list[str]:
    """Split a script into complete statements (trigger bodies stay whole). No executescript."""
    out: list[str] = []
    buffer = ""
    for piece in sql.split(";"):
        buffer += piece + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip().rstrip(";").strip():
                out.append(buffer.strip())
            buffer = ""
    if buffer.strip().rstrip(";").strip():
        out.append(buffer.strip().rstrip(";") + ";")
    return out


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """`BEGIN IMMEDIATE` ... `COMMIT`, or `ROLLBACK` when the body raises."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        conn.execute("COMMIT")


def _migrate(conn: sqlite3.Connection, steps: Sequence[tuple[int, str]], target: int) -> None:
    current = _user_version(conn)
    if current > target:
        raise StoreVersionError("store was written by a newer version")
    if current == target:
        return
    with transaction(conn):
        current = _user_version(conn)          # re-read under the write lock: another process may have migrated
        if current > target:
            raise StoreVersionError("store was written by a newer version")
        for version, sql in steps:
            if current < version <= target:
                for statement in split_statements(sql):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {int(version)}")
                current = version
        if current != target:
            raise StoreError("migration steps do not reach the requested version")


@contextlib.contextmanager
def open_store(name: str, schema_sql: str | Sequence[tuple[int, str]], version: int, data_dir: str | None = None
               ) -> Iterator[sqlite3.Connection]:
    """Open (and migrate) the SQLite store `name`. One connection per call; closed on exit.

    `schema_sql` is either one script that brings any older database to `version` (make it
    idempotent: `CREATE TABLE IF NOT EXISTS`) or an ordered list of `(version, sql)` migrations.
    """
    _check_name(name)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    steps = [(version, schema_sql)] if isinstance(schema_sql, str) else sorted(schema_sql)
    path = os.path.join(store_dir(data_dir), name + ".db")
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=True)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        _migrate(conn, steps, version)
        yield conn
    finally:
        conn.close()


# ============================================================================ lock file
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_OWNERS: dict[str, int] = {}                           # lock key -> ident of the thread holding it
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _thread_lock(path: str) -> threading.Lock:
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(_lock_key(path), threading.Lock())


def _try_os_lock(fd: int) -> bool:
    """One non-blocking attempt at the advisory lock on `fd`. False when another holder has it."""
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)           # type: ignore[attr-defined]
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def _writer_lock(path: str, *, wait_s: float, max_age_s: float = LOCK_MAX_AGE_S) -> Iterator[None]:
    """Thread lock, then an OS advisory lock on `path + ".lock"`. `max_age_s` is ignored (no staleness)."""
    lock_path = path + ".lock"
    key = _lock_key(path)
    thread_lock = _thread_lock(path)
    if not thread_lock.acquire(timeout=wait_s):
        raise StoreLockError("another writer is active")
    fd = None
    try:
        deadline = _clock() + wait_s
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            raise StoreLockError("the lock file cannot be opened") from None
        while not _try_os_lock(fd):
            if _clock() >= deadline:
                raise StoreLockError("another writer is active")
            _sleep(LOCK_POLL_S)
        try:                                                # diagnostics only; failure never matters
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps({"pid": os.getpid(), "token": secrets.token_hex(8),
                                     "created": _clock()}).encode("utf-8"))
        except OSError:
            pass
        _PATH_OWNERS[key] = threading.get_ident()
        try:
            yield
        finally:
            _PATH_OWNERS.pop(key, None)
    finally:
        if fd is not None:
            if sys.platform == "win32":
                try:                                        # release explicitly; closing also drops it
                    import msvcrt
                    os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)   # type: ignore[attr-defined]
                except OSError:
                    pass
            os.close(fd)                                    # closing drops the OS lock; the file stays
        thread_lock.release()


def exclusive(path: str, *, wait_s: float = LOCK_WAIT_S, max_age_s: float = LOCK_MAX_AGE_S):
    """Cross-process (and in-process) exclusive lock named after `path` (the file is `path + ".lock"`).

    Raises `StoreLockError` after `wait_s`. Not re-entrant: do not nest it for the same path.
    The lock is an OS advisory lock released when the holder exits or dies; `max_age_s` is accepted
    but ignored. Local filesystems only.
    """
    return _writer_lock(path, wait_s=wait_s, max_age_s=max_age_s)


# ============================================================================ JSON documents
def document_lock(name: str, *, data_dir: str | None = None, wait_s: float = LOCK_WAIT_S,
                  max_age_s: float = LOCK_MAX_AGE_S):
    """Hold the writer lock of the JSON document `name` across a read-modify-write or a dependent action.

    Inside it, pass `lock_held=True` to `write_json` (the lock is not re-entrant).
    """
    return _writer_lock(_json_path(name, data_dir), wait_s=wait_s, max_age_s=max_age_s)


def _json_path(name: str, data_dir: str | None) -> str:
    return os.path.join(store_dir(data_dir), _check_name(name) + ".json")


def _parse_schema(stamp: Any, schema: str) -> int | None:
    match = _SCHEMA_RE.match(stamp) if isinstance(stamp, str) else None
    if not match or match.group("name") != schema:
        return None
    return int(match.group("ver"))


def _load(path: str, schema: str, version: int, *, rename_damaged: bool, locked: bool = False) -> Decoded:
    """Read one document. Never raises. Missing file -> revision 0 empty document marker."""
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return Decoded(f"{schema}/{version}", {"missing": True, "revision": 0}, [], True)
    except OSError:
        return Decoded(None, None, [diag("unreadable", "", ERROR)], False)
    if size > MAX_JSON_BYTES:
        return Decoded(None, None, [diag("too_large", "", ERROR)], False)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
    except OSError:
        return Decoded(None, None, [diag("unreadable", "", ERROR)], False)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        if rename_damaged:
            _rename_damaged(path, raw, locked)
        return Decoded(None, None, [diag("damaged_file", "", ERROR)], False)
    if not isinstance(doc, dict):
        return Decoded(None, None, [diag("not_an_object", "", ERROR)], False, raw=None)
    found = _parse_schema(doc.get("schema_version"), schema)
    if found is None:
        code = "missing_schema_version" if doc.get("schema_version") is None else "unknown_schema_version"
        return Decoded(doc.get("schema_version") if isinstance(doc.get("schema_version"), str) else None,
                       None, [diag(code, "schema_version", ERROR)], False, raw=doc)
    if found > version:
        return Decoded(doc["schema_version"], None, [diag("newer_schema_version", "schema_version", ERROR)],
                       False, raw=doc)
    revision = doc.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return Decoded(doc["schema_version"], None, [diag("bad_revision", "revision", ERROR)], False, raw=doc)
    return Decoded(doc["schema_version"], doc, [], True)


def _rename_damaged(path: str, seen: bytes, locked: bool) -> None:
    """Move damaged bytes aside, only under the writer lock and only if they are still the same bytes."""
    def move() -> None:
        try:
            with open(path, "rb") as handle:
                now = handle.read(MAX_JSON_BYTES + 1)
        except OSError:
            return
        if now != seen:
            return                                          # a writer replaced it meanwhile
        try:
            json.loads(now.decode("utf-8"))
            return                                          # decodes now: not damaged
        except (ValueError, UnicodeDecodeError, RecursionError):
            pass
        target = f"{path}.damaged-{int(_clock())}-{secrets.token_hex(3)}"
        try:
            os.replace(path, target)
        except OSError:
            pass

    if locked:
        move()
        return
    if _PATH_OWNERS.get(_lock_key(path)) == threading.get_ident():
        return                                              # this thread holds the lock already: skip, no stall
    try:
        with _writer_lock(path, wait_s=1.0, max_age_s=LOCK_MAX_AGE_S):
            move()
    except StoreLockError:
        pass                                                # a writer is active; leave the file alone

def read_json(name: str, *, schema: str, version: int, data_dir: str | None = None,
              rename_damaged: bool = True) -> Decoded:
    """Read the JSON document `name`. Never raises on file problems.

    A missing file decodes as `{"missing": True, "revision": 0}`. Undecodable bytes are renamed
    to `<name>.json.damaged-*`. A document with a newer `schema_version` is NOT renamed or
    touched: `value` is None, the bytes stay in `raw`, and a diagnostic `newer_schema_version` says why.

    The rename takes the writer lock. A thread that already holds `document_lock(name)` should pass
    `rename_damaged=False` (the lock is not re-entrant); if it does not, the rename is skipped
    instead of stalling.
    """
    return _load(_json_path(name, data_dir), schema, version, rename_damaged=rename_damaged)


def write_json(name: str, doc: dict, *, expected_revision: int, schema: str, version: int,
               data_dir: str | None = None, lock_wait_s: float = LOCK_WAIT_S,
               lock_max_age_s: float = LOCK_MAX_AGE_S, lock_held: bool = False) -> int:
    """Write `doc` as revision `expected_revision + 1`; returns the new revision.

    `expected_revision` is 0 for a document that does not exist yet. Raises `RevisionConflict`
    when the stored revision differs, `StoreVersionError` when the stored document is newer
    than this code (bytes preserved), `StoreLockError` when another writer holds the lock for
    longer than `lock_wait_s`, `StoreTooLarge` above `MAX_JSON_BYTES`. `lock_held=True` means the
    caller already holds `document_lock(name)` and the lock is not taken again.
    """
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    if not isinstance(doc, dict):
        raise ValueError("document must be an object")
    path = _json_path(name, data_dir)
    new_revision = expected_revision + 1
    body = dict(doc)
    body["schema_version"] = f"{schema}/{version}"
    body["revision"] = new_revision
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise StoreTooLarge("document exceeds the size limit")
    guard = contextlib.nullcontext() if lock_held else _writer_lock(path, wait_s=lock_wait_s,
                                                                       max_age_s=lock_max_age_s)
    with guard:
        current = _load(path, schema, version, rename_damaged=True, locked=True)
        if current.value is None:
            if any(d.code == "newer_schema_version" for d in current.diagnostics):
                raise StoreVersionError("document was written by a newer version")
            if any(d.code in ("too_large", "unreadable", "not_an_object", "unknown_schema_version",
                              "missing_schema_version", "bad_revision") for d in current.diagnostics):
                raise StoreError("stored document is not usable; it was left untouched")
            stored = 0                                       # damaged file was renamed aside
        else:
            stored = current.value["revision"]
        if stored != expected_revision:
            raise RevisionConflict("the document changed since it was read")
        _atomic_replace(path, payload)
    return new_revision


def _atomic_replace(path: str, payload: bytes) -> None:
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                _replace(tmp, path)
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                _sleep(REPLACE_SLEEP_S * (attempt + 1))
        _fsync_dir(os.path.dirname(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _fsync_dir(directory: str) -> None:
    if sys.platform == "win32":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
