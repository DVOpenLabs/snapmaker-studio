"""Scene jobs: the bounded, cancellable background build behind /scene/start|status|result|cancel.

Model (frozen by plan v3/v4/v5/v6):

* **One worker thread, at most one queued job.** A new start cancels and replaces the client's own
  earlier work (the newest queued job wins; a running job is marked cancelled at once). The worker
  slot is released only when the thread has actually exited; a replacement therefore waits, queued,
  until the cancelled thread observes the flag (bounded by the cooperative-interruption units in
  ``snapstudio_core.scene_limits``).
* **States** ``queued | running | succeeded | failed | cancelled``. Terminal states are immutable and
  the FIRST terminal wins: a worker finishing after a cancel discards its result. Cancel is legal from
  queued|running and a late cancel on a terminal job is a no-op. There is no stored "expired" state:
  an evicted or unknown id answers 404 EXPIRED.
* **Retention.** A terminal job is kept for ``RESULT_TTL_SECONDS`` or until more than
  ``MAX_TERMINAL_JOBS`` terminal jobs exist (oldest first). Only jobs whose worker has exited are evicted.
* **Deadline.** 60 s wall clock from the moment the job becomes ``running``, observed cooperatively.
  Accepted limitation: a single stuck native/filesystem call cannot be interrupted in-process (there is
  no multiprocessing in the frozen sidecar). The backstop is fail-closed: if the worker is still alive
  ``WEDGE_GRACE_SECONDS`` after a cancel or after the deadline, the job is reported failed with TIMEOUT
  (when it was the deadline) and every new start answers 503 WORKER_WEDGED until the thread exits.
* **Snapshot.** The source is copied once into a private file under
  ``<data>/scene-tmp/<pid>-<nonce>/`` (streamed 1 MiB chunks, hard ceiling), hashed (the revision is the
  SHA-256 of those bytes), and ONLY the copy is parsed. A scene is a consistent snapshot of the file as
  copied. ``SOURCE_CHANGED`` therefore applies only to (a) a file that changed while it was being
  copied, (b) a reused request_id+path whose file now hashes differently from that job's revision, and
  (c) an ``expected_revision`` that differs from the job's revision. It does NOT apply to edits made
  after the snapshot was taken.
* **Snapshot lifetime.** The WORKER deletes its own snapshot in its ``finally`` BEFORE setting
  ``worker_done``. Eviction removes only the snapshot of a terminal job whose worker is done, with a
  missing-file-tolerant unlink. Cancel never deletes a file. A startup sweep removes only
  ``scene-tmp/<pid>-<nonce>`` directories whose pid is dead (or older than 24 h) and tolerates sharing
  violations; it never touches a live process's directory.
* **Nothing here touches the original file except to read it.**
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import secrets
import shutil
import sys
import threading
import time
import uuid

from snapstudio_core import paths as _paths
from snapstudio_core import scene
from snapstudio_core import scene_limits as L
from . import request_validation as rv

ROUTES = ("/scene/start", "/scene/status", "/scene/result", "/scene/cancel")
TERMINAL = ("succeeded", "failed", "cancelled")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,%d}$" % L.MAX_REQUEST_ID_LENGTH)
_REVISION = re.compile(r"^[0-9a-f]{64}$")


class JobError(Exception):
    """An answer the API gives instead of a result: HTTP status, stable code, safe message."""

    def __init__(self, http: int, code: str, message: str, **extra) -> None:
        self.http, self.code, self.message, self.extra = http, code, message, extra
        super().__init__(message)

    def body(self) -> dict:
        return {"error": self.code, "message": self.message, **self.extra}


class Job:
    def __init__(self, job_id: str, request_id: str, path: str, now: float) -> None:
        self.job_id, self.request_id, self.path = job_id, request_id, path
        self.source = path                       # the path as the client gave it (for reading)
        self.state = "queued"
        self.stage: str | None = None
        self.completed: int | None = None
        self.total: int | None = None
        self.error: dict | None = None
        self.revision: str | None = None
        self.result: bytes | None = None
        self.snapshot: str | None = None
        self.created = now
        self.deadline: float | None = None
        self.terminal_at: float | None = None
        self.cancelled_at: float | None = None
        self.worker_done = threading.Event()
        self.cancel_flag = threading.Event()


class _Control(scene.Control):
    def __init__(self, registry: "SceneJobs", job: Job) -> None:
        self.registry, self.job = registry, job

    def check(self) -> None:
        job = self.job
        if job.cancel_flag.is_set() or job.state != "running":
            raise scene.SceneCancelled()
        if self.registry._clock() > job.deadline:
            raise scene.SceneTimeout()

    def progress(self, stage, completed, total) -> None:
        self.job.stage, self.job.completed, self.job.total = stage, completed, total


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists. Errs towards 'alive' when it cannot tell."""
    if pid == os.getpid():
        return True
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5                 # access denied: the process exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259                           # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def sweep_stale(root: str | None = None, *, now: float | None = None) -> list[str]:
    """Remove scene-tmp directories left by engines that are gone. Returns what it removed.

    A ``<pid>-<nonce>`` folder is removed only when its owner pid is NOT running AND the folder is older
    than ``SNAPSHOT_DIR_MIN_AGE_SECONDS``. A folder owned by a live process is never touched, however old
    (pid reuse is an accepted cost: a stale folder next to a recycled pid waits until that pid exits).
    Sharing violations are tolerated and retried at the next start."""
    base = root or os.path.join(_paths.data_dir(create=False), "scene-tmp")
    removed: list[str] = []
    try:
        names = os.listdir(base)
    except OSError:
        return removed
    now = time.time() if now is None else now
    for name in names:
        m = re.match(r"^(\d+)-([0-9a-f]+)$", name)
        full = os.path.join(base, name)
        if not m or not os.path.isdir(full):
            continue
        pid = int(m.group(1))
        if pid == os.getpid():
            continue                                           # our own directory, whatever else is true
        try:
            age = now - os.stat(full).st_mtime
        except OSError:
            continue
        if pid_alive(pid):
            continue                                           # NEVER a live process's folder, whatever its age
        if age < L.SNAPSHOT_DIR_MIN_AGE_SECONDS:
            continue                                           # a just-exited engine's folder is left alone a while
        try:
            shutil.rmtree(full)
            removed.append(name)
        except OSError:
            pass                                               # sharing violation / in use: leave it for next time
    return removed


class SceneJobs:
    def __init__(self, *, clock=time.monotonic, builder=None, snapshot_root: str | None = None,
                 deadline: float = L.JOB_DEADLINE_SECONDS, wedge_grace: float = L.WEDGE_GRACE_SECONDS,
                 ttl: float = L.RESULT_TTL_SECONDS, max_terminal: int = L.MAX_TERMINAL_JOBS) -> None:
        self._clock = clock
        self._builder = builder or scene.build_scene
        self._root = snapshot_root
        self._deadline, self._grace, self._ttl, self._max_terminal = deadline, wedge_grace, ttl, max_terminal
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._by_request: dict[str, Job] = {}
        self._queued: Job | None = None
        self._running: Job | None = None
        self._worker: threading.Thread | None = None
        self._dir: str | None = None
        self._pending: list[list] = []        # [path, attempts, next_try] snapshot files that resisted deletion

    # ------------------------------------------------------------------ public API
    def start(self, path: str, request_id: str) -> dict:
        key = os.path.normcase(os.path.abspath(path))
        ext = os.path.splitext(key)[1].lower()
        if ext not in (".3mf", ".stl"):
            raise JobError(422, "UNSUPPORTED_FORMAT", "Only .3mf and .stl files can be shown.")
        if not os.path.isfile(path):
            raise JobError(400, "INVALID_REQUEST", "That file could not be found.")
        for _attempt in range(2):
            with self._lock:
                self._housekeeping()
                existing = self._by_request.get(request_id)
                if existing is None:
                    return self._create_locked(path, key, request_id)
                self._same_path_or_raise(existing, key)
                revision = existing.revision
            # Hash OUTSIDE the lock (it can be slow), then re-check under it: the retained job may have
            # been evicted meanwhile, and an evicted job must never be handed back.
            if revision is not None and self._current_hash(path) != revision:
                raise JobError(409, "SOURCE_CHANGED", "The file changed since that scene was built. Start a new one.")
            with self._lock:
                self._housekeeping()
                if self._jobs.get(existing.job_id) is existing and self._by_request.get(request_id) is existing:
                    return self._start_body(existing, None)
            # evicted while hashing: go round once more and start a fresh job for the same request
        with self._lock:
            self._housekeeping()
            existing = self._by_request.get(request_id)
            if existing is not None:
                self._same_path_or_raise(existing, key)
                return self._start_body(existing, None)
            return self._create_locked(path, key, request_id)

    def _create_locked(self, path: str, key: str, request_id: str) -> dict:
        if self._wedged():
            raise JobError(503, "WORKER_WEDGED", "The scene worker is stuck. Try again after it recovers.")
        replaced = None
        if self._queued is not None:
            replaced = self._queued.job_id
            self._cancel_locked(self._queued)
            self._queued = None
        if self._running is not None and self._running.state == "running":
            replaced = self._running.job_id
            self._cancel_locked(self._running)
        job = Job(uuid.uuid4().hex, request_id, key, self._clock())
        job.source = path
        self._jobs[job.job_id] = job
        self._by_request[request_id] = job
        self._queued = job
        if self._worker is None:
            self._worker = threading.Thread(target=self._worker_main, name="scene-worker", daemon=True)
            self._worker.start()
        return self._start_body(job, replaced)

    def status(self, job_id: str) -> dict:
        with self._lock:
            self._housekeeping()
            return self._status_body(self._get(job_id))

    def result(self, job_id: str, expected_revision: str | None = None) -> tuple[int, bytes | dict]:
        with self._lock:
            self._housekeeping()
            job = self._get(job_id)
            if expected_revision is not None and job.revision is not None and job.revision != expected_revision:
                raise JobError(409, "SOURCE_CHANGED", "That scene was built from a different version of the file.")
            if job.state == "succeeded":
                return 200, job.result
            if job.state == "failed":
                return 422, {"error": job.error["code"], "message": job.error["message"]}
            if job.state == "cancelled":
                return 409, {"error": "CANCELLED", "message": "That scene was cancelled."}
            return 409, {"error": "NOT_READY", "message": "That scene is not ready yet.", "state": job.state}

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            self._housekeeping()
            job = self._get(job_id)
            if job.state in ("queued", "running"):
                if job is self._queued:
                    self._queued = None
                self._cancel_locked(job)
            body = self._status_body(job)
            self._housekeeping()                               # a cancelled-while-queued job can push past the cap
            return body

    # ------------------------------------------------------------------ introspection (tests, benchmark)
    def snapshot_dir(self) -> str | None:
        return self._dir

    def retained(self) -> int:
        with self._lock:
            return len(self._jobs)

    def wedged(self) -> bool:
        with self._lock:
            return self._wedged()

    def worker_alive(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def close(self, timeout: float = 5.0) -> None:
        """Cancel everything and wait for the worker to exit (tests / orderly shutdown)."""
        with self._lock:
            for job in list(self._jobs.values()):
                if job.state in ("queued", "running"):
                    if job is self._queued:
                        self._queued = None
                    self._cancel_locked(job)
            worker = self._worker
        if worker is not None:
            worker.join(timeout)
            if worker.is_alive():
                return
        with self._lock:
            for entry in list(self._pending):
                self._try_unlink(entry)
            if self._dir and not self._pending:
                shutil.rmtree(self._dir, ignore_errors=True)   # best effort; a later start sweeps what is left

    # ------------------------------------------------------------------ internals (lock held)
    def _same_path_or_raise(self, job: Job, key: str) -> None:
        if job.path != key:
            raise JobError(409, "INVALID_REQUEST", "That request_id is already used for another file.",
                           reason="request_id reused for another path")

    def _get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobError(404, "EXPIRED", "That scene is no longer available.")
        return job

    def _cancel_locked(self, job: Job) -> None:
        if job.state not in ("queued", "running"):
            return
        was_queued = job.state == "queued"
        now = self._clock()
        job.state = "cancelled"
        job.error = {"code": "CANCELLED", "message": "That scene was cancelled."}
        job.terminal_at = job.cancelled_at = now
        job.cancel_flag.set()
        if was_queued:
            job.worker_done.set()                              # it never had a worker or a snapshot

    def _wedged(self) -> bool:
        job = self._running
        if job is None or job.worker_done.is_set():
            return False
        now = self._clock()
        if job.state == "cancelled" and job.cancelled_at is not None and now >= job.cancelled_at + self._grace:
            return True
        return job.deadline is not None and now >= job.deadline + self._grace

    def _housekeeping(self) -> None:
        now = self._clock()
        for entry in list(self._pending):
            if now >= entry[2]:
                self._try_unlink(entry)
        job = self._running
        if (job is not None and job.state == "running" and job.deadline is not None
                and now >= job.deadline + self._grace and not job.worker_done.is_set()):
            self._fail_locked(job, "TIMEOUT", "Building the scene took too long.")      # backstop; the thread is wedged
        evictable = [j for j in self._jobs.values() if j.state in TERMINAL and j.worker_done.is_set()]
        for j in evictable:
            if now - j.terminal_at > self._ttl:
                self._drop(j)
        terminal = [j for j in self._jobs.values() if j.state in TERMINAL]
        excess = len(terminal) - self._max_terminal
        if excess > 0:
            for j in sorted((j for j in terminal if j.worker_done.is_set()), key=lambda j: j.terminal_at)[:excess]:
                self._drop(j)

    def _drop(self, job: Job) -> None:
        if job.snapshot:
            self._defer_unlink(job.snapshot)
            job.snapshot = None
        job.result = None
        self._jobs.pop(job.job_id, None)
        if self._by_request.get(job.request_id) is job:
            del self._by_request[job.request_id]

    def _defer_unlink(self, path: str) -> None:
        """Delete a snapshot file now; if Windows (or anything) still holds it, KEEP the path on a retry list
        with back-off. It is forgotten only when it is gone, or when the process exits (the startup sweep
        of a later engine then removes the folder)."""
        entry = [path, 0, self._clock()]
        if not self._try_unlink(entry) and len(self._pending) < L.MAX_PENDING_UNLINKS:
            self._pending.append(entry)

    def _try_unlink(self, entry: list) -> bool:
        try:
            os.unlink(entry[0])
        except FileNotFoundError:
            pass
        except OSError:
            entry[1] += 1
            entry[2] = self._clock() + min(2.0 ** entry[1], 30.0)       # 2 s, 4 s, ... capped at 30 s
            return False
        if entry in self._pending:
            self._pending.remove(entry)
        return True

    def _fail_locked(self, job: Job, code: str, message: str) -> None:
        if job.state in TERMINAL:
            return                                             # the first terminal state wins
        job.state = "failed"
        job.error = {"code": code, "message": message}
        job.terminal_at = self._clock()
        job.cancel_flag.set()

    def _status_body(self, job: Job) -> dict:
        running = job.state == "running"
        return {"job_id": job.job_id, "request_id": job.request_id, "state": job.state,
                "stage": job.stage if running else None,
                "completed": job.completed if running else None,
                "total": job.total if running else None,
                "error": job.error, "revision": job.revision}

    def _start_body(self, job: Job, replaced: str | None) -> dict:
        return {"job_id": job.job_id, "request_id": job.request_id, "state": job.state,
                "revision": job.revision, "replaced_job_id": replaced}

    # ------------------------------------------------------------------ worker
    def _worker_main(self) -> None:
        try:
            while True:
                with self._lock:
                    job = self._queued
                    if job is None:
                        self._worker = None                    # the slot is released only here, as the thread exits
                        self._housekeeping()
                        return
                    self._queued = None
                    now = self._clock()
                    job.state = "running"
                    job.deadline = now + self._deadline        # the clock starts when the job starts running
                    self._running = job
                try:
                    self._execute(job)
                finally:
                    with self._lock:
                        if self._running is job:
                            self._running = None
                        self._housekeeping()                   # retention does not depend on a client polling
        except BaseException:                                  # noqa: BLE001 - never leave the slot taken
            with self._lock:
                self._worker = None
            raise

    def _execute(self, job: Job) -> None:
        ctl = _Control(self, job)
        try:
            job.stage, job.completed, job.total = "reading", 0, None
            snap = self._snapshot(job, ctl)
            body = self._builder(snap, job.revision, ctl)
            with self._lock:
                if job.state == "running":
                    job.state = "succeeded"
                    job.result = body
                    job.terminal_at = self._clock()
                # else: cancelled / failed first -- the late result is discarded
        except scene.SceneCancelled:
            with self._lock:
                if job.state == "running":
                    self._cancel_locked(job)
        except scene.SceneTimeout:
            with self._lock:
                self._fail_locked(job, "TIMEOUT", "Building the scene took too long.")
        except scene.SceneError as exc:
            with self._lock:
                self._fail_locked(job, exc.code, exc.message)
        except JobError as exc:
            with self._lock:
                self._fail_locked(job, exc.code, exc.message)
        except BaseException as exc:                           # noqa: BLE001
            try:
                from . import server
                server._log_unexpected(exc)
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                self._fail_locked(job, "INTERNAL", "The scene could not be built.")
        finally:
            snap_path = job.snapshot
            if snap_path:
                try:
                    os.unlink(snap_path)                       # the worker deletes its own file ...
                    job.snapshot = None
                except FileNotFoundError:
                    job.snapshot = None
                except OSError:
                    pass                                       # ... and eviction retries if Windows still holds it
            job.worker_done.set()                              # ... BEFORE it signals that it is done

    # ------------------------------------------------------------------ snapshot
    def _snapshot_directory(self) -> str:
        with self._lock:
            if self._dir is None:
                base = self._root or os.path.join(_paths.data_dir(), "scene-tmp")
                self._dir = os.path.join(base, f"{os.getpid()}-{secrets.token_hex(4)}")
            os.makedirs(self._dir, exist_ok=True)      # on EVERY job: something may have removed it
            return self._dir

    def _snapshot(self, job: Job, ctl: _Control) -> str:
        src = job.source
        directory = self._snapshot_directory()
        ext = os.path.splitext(src)[1].lower()
        dest = os.path.join(directory, job.job_id + ext)
        try:
            fh = open(src, "rb")
        except OSError as exc:
            raise JobError(400, "INVALID_REQUEST", "That file could not be read.") from exc
        try:
            st0 = os.fstat(fh.fileno())
            size0 = st0.st_size
            if size0 > L.SNAPSHOT_MAX_BYTES:
                raise scene.SceneError("LIMIT_EXCEEDED", "The file is larger than Studio will open here.")
            try:
                free = shutil.disk_usage(directory).free
            except OSError:
                free = None
            if free is not None and free < size0 + L.DISK_HEADROOM_BYTES:
                raise scene.SceneError("INTERNAL", "There is not enough free disk space to read this file.")
            digest = hashlib.sha256()
            count = 0
            job.snapshot = dest
            try:
                with open(dest, "wb") as out:
                    while True:
                        ctl.check()
                        chunk = fh.read(L.SNAPSHOT_CHUNK_BYTES)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > L.SNAPSHOT_MAX_BYTES or count > size0:
                            break
                        digest.update(chunk)
                        out.write(chunk)
                        ctl.progress("reading", count, size0)
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise scene.SceneError("INTERNAL", "There is not enough free disk space to read this file.") from exc
                raise scene.SceneError("INTERNAL", "Studio could not write its temporary copy of this file.") from exc
            st1 = os.fstat(fh.fileno())
        finally:
            fh.close()
        try:
            st2 = os.stat(src)
        except OSError:
            st2 = None
        changed = (count != size0
                   or (st1.st_size, st1.st_mtime_ns) != (size0, st0.st_mtime_ns)
                   or st2 is None or (st2.st_size, st2.st_mtime_ns) != (size0, st0.st_mtime_ns)
                   or (st0.st_ino and st2 is not None and st2.st_ino and st0.st_ino != st2.st_ino))
        if changed:
            raise scene.SceneError("SOURCE_CHANGED", "The file changed while Studio was reading it.")
        job.revision = digest.hexdigest()
        return dest

    @staticmethod
    def _current_hash(path: str) -> str | None:
        """SHA-256 of the file as it is now (None if it cannot be read or is over the ceiling)."""
        digest = hashlib.sha256()
        total = 0
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(L.SNAPSHOT_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > L.SNAPSHOT_MAX_BYTES:
                        return None
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()


# ----------------------------------------------------------------------------------------------
# HTTP glue (kept out of server.py so that file only gains a route branch)
# ----------------------------------------------------------------------------------------------

_default: SceneJobs | None = None
_default_lock = threading.Lock()


def registry() -> SceneJobs:
    global _default
    with _default_lock:
        if _default is None:
            _default = SceneJobs()
        return _default


def reset_default_for_tests() -> None:
    global _default
    with _default_lock:
        if _default is not None:
            _default.close()
        _default = None


def _request_id(data: dict) -> str:
    value = rv.require_str(data, "request_id")
    if not _REQUEST_ID.match(value):
        raise rv.ValidationError("Invalid 'request_id'")
    return value


def _job_id(data: dict) -> str:
    value = rv.require_str(data, "job_id")
    if len(value) > 128:
        raise rv.ValidationError("Invalid 'job_id'")
    return value


def handle(route: str, data: dict, jobs: SceneJobs | None = None) -> tuple[int, bytes | dict]:
    """Run one /scene/* request. Returns (HTTP status, dict body or pre-serialized bytes)."""
    jobs = jobs or registry()
    if not isinstance(data, dict):
        return 400, {"error": "INVALID_REQUEST", "message": "The request body must be a JSON object."}
    try:
        if route == "/scene/start":
            path = rv.require_bounded_str(data, "path", 4096)
            return 200, jobs.start(path, _request_id(data))
        if route == "/scene/status":
            return 200, jobs.status(_job_id(data))
        if route == "/scene/result":
            expected = data.get("expected_revision")
            if expected is not None and (not isinstance(expected, str) or not _REVISION.match(expected)):
                raise rv.ValidationError("Invalid 'expected_revision'")
            return jobs.result(_job_id(data), expected)
        if route == "/scene/cancel":
            return 200, jobs.cancel(_job_id(data))
    except rv.ValidationError as exc:
        return 400, {"error": "INVALID_REQUEST", "message": str(exc)}
    except JobError as exc:
        return exc.http, exc.body()
    return 404, {"error": "not found"}
