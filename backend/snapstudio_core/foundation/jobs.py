"""Bounded background jobs for the Studio+ tracks.

Modelled on `snapstudio_api.scene_jobs` (session-scoped requests, bounded counts, a slot that is
released only when the worker has really stopped) but separate from it.

States: queued | running | cancel_requested | succeeded | failed | cancelled | interrupted.
`wedged` is a flag, not a state: a thread worker that ignores cancellation keeps its slot and is
reported wedged. A thread cannot be killed; only a sidecar restart frees it, and the status says so.

Two worker classes share one protocol (`Worker`): `run(ctx)`, `cancel()`, `kill()`.
Thread workers are cooperative (they poll `ctx.cancelled`; `kill` does nothing). A subprocess
worker is an object implementing the protocol on top of `engines/cli_runner.py`, which owns every
process handle; this module never starts or touches a process.

Guarantees
- Inputs are copied and frozen at start; `inputs_revision` is their canonical SHA-256.
- `(session_id, idempotency_key)` returns the existing job (a response lost in transit is safe to retry).
- At most `max_workers` slots (default 2), at most `max_queue` waiting jobs (default 8, then an
  explicit `queue_full` refusal) and at most one running job per kind.
- A cancelled or timed-out worker keeps its slot until it has actually stopped.
- A result that arrives after cancellation is never published and its temporary files are removed.
- Results and temporary bytes are bounded.
- Persisted records (optional, via `store`) hold no inputs; on restart, work that was queued or
  running becomes `interrupted` and is never replayed; the temporary files of exactly those
  restored jobs are removed.
- Every manager owns its records (`owner`) and a private temp subdirectory. A manager never adopts,
  interrupts, overwrites or deletes the records or temp files of another manager that is still
  open in this process. `default_manager()` is the process-wide manager the sidecar should use.
- Admission counts every accepted job (running, waiting, and not yet launched while its record is
  being persisted), so concurrent starts cannot exceed `max_workers + max_queue`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Protocol

from snapstudio_core import paths as _paths

from . import store

QUEUED, RUNNING, CANCEL_REQUESTED = "queued", "running", "cancel_requested"
SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = "succeeded", "failed", "cancelled", "interrupted"
STATES = (QUEUED, RUNNING, CANCEL_REQUESTED, SUCCEEDED, FAILED, CANCELLED, INTERRUPTED)
TERMINAL = (SUCCEEDED, FAILED, CANCELLED, INTERRUPTED)

DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_QUEUE = 8
DEFAULT_RESULT_TTL_S = 600.0
DEFAULT_MAX_TEMP_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_WEDGE_GRACE_S = 10.0
MAX_TERMINAL_JOBS = 256
JOBS_STORE = "foundation_jobs"
JOBS_SCHEMA, JOBS_SCHEMA_VERSION = "foundation_jobs", 1

_LIVE: dict[str, "JobManager"] = {}          # managers open in this process, by instance id
_LIVE_LOCK = threading.Lock()
_DEFAULT: "JobManager | None" = None

_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,47}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
WEDGED_NOTE = "The worker ignored cancellation and still holds its slot; restart the Studio engine to free it."


class JobRefused(Exception):
    """A start/result/cancel answer that is a refusal, with a stable `code`."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class JobCancelled(Exception):
    """Raised by `ctx.check()` inside a worker once cancellation is requested."""


class JobLimitError(Exception):
    """A worker exceeded its temp-byte budget."""


class JobFailure(Exception):
    """A worker's own failure with a message that is safe to show. Any other exception is reported generically."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _bounded_code(code: Any) -> str:
    """A failure code that is always a short string, so it can be stored as JSON whatever the worker raised."""
    try:
        text = code if isinstance(code, str) else str(code)
    except Exception:                                           # noqa: BLE001 - a hostile __str__
        return "worker_error"
    return text[:64] or "worker_error"


class Worker(Protocol):
    def run(self, ctx: "JobContext") -> Any: ...
    def cancel(self) -> None: ...
    def kill(self) -> None: ...


class _ThreadWorker:
    def __init__(self, fn: Callable[["JobContext"], Any]) -> None:
        self._fn = fn

    def run(self, ctx: "JobContext") -> Any:
        return self._fn(ctx)

    def cancel(self) -> None:
        pass                       # cooperative: the context's token is the signal

    def kill(self) -> None:
        pass                       # a thread cannot be killed; the job is reported wedged instead


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class JobContext:
    """What a worker sees: frozen inputs, a cancel token, bounded temp space and progress."""

    def __init__(self, job_id: str, inputs: Any, temp_dir: str, max_temp_bytes: int,
                 on_progress: Callable[[str | None, float | None], None]) -> None:
        self.job_id = job_id
        self.inputs = inputs
        self.temp_dir = temp_dir
        self._max_temp = max_temp_bytes
        self._cancel = threading.Event()
        self._progress = on_progress
        self._temp_claimed = 0
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`; True if cancellation arrived."""
        return self._cancel.wait(seconds)

    def progress(self, stage: str | None = None, fraction: float | None = None) -> None:
        self._progress(stage, fraction)

    def temp_path(self, name: str) -> str:
        if not isinstance(name, str) or not name or os.path.basename(name) != name or name in (".", ".."):
            raise ValueError("temp file name must be a plain file name")
        os.makedirs(self.temp_dir, exist_ok=True)
        return os.path.join(self.temp_dir, name)

    def claim_temp_bytes(self, nbytes: int) -> None:
        """Declare `nbytes` more temporary data; raises `JobLimitError` over the job's budget."""
        with self._lock:
            if nbytes < 0 or self._temp_claimed + nbytes > self._max_temp:
                raise JobLimitError("temp_budget_exceeded")
            self._temp_claimed += nbytes


class _Job:
    def __init__(self, job_id: str, kind: str, session_id: str, key: str, inputs_revision: str,
                 now: float, timeout_s: float) -> None:
        self.id, self.kind, self.session_id, self.key = job_id, kind, session_id, key
        self.inputs_revision = inputs_revision
        self.state = QUEUED
        self.created = now
        self.started: float | None = None
        self.cancel_at: float | None = None
        self.finished: float | None = None
        self.timeout_s = timeout_s
        self.timed_out = False
        self.late = False
        self.killed = False
        self.error: dict | None = None
        self.result: Any = None
        self.has_result = False
        self.stage: str | None = None
        self.fraction: float | None = None
        self.inputs: Any = None
        self.worker: Worker | None = None
        self.ctx: JobContext | None = None
        self.thread: threading.Thread | None = None
        self.thread_done = threading.Event()
        self.ready = False                       # becomes True once its record is persisted
        self.launch_reserved = False              # admission reservation while persistence is pending
        self.persist_only = False                # restored record: no thread, no worker


class JobManager:
    def __init__(self, *, max_workers: int = DEFAULT_MAX_WORKERS, max_queue: int = DEFAULT_MAX_QUEUE,
                 result_ttl_s: float = DEFAULT_RESULT_TTL_S, max_temp_bytes: int = DEFAULT_MAX_TEMP_BYTES,
                 max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES, wedge_grace_s: float = DEFAULT_WEDGE_GRACE_S,
                 default_timeout_s: float = DEFAULT_TIMEOUT_S, temp_root: str | None = None,
                 persist: bool = False, data_dir: str | None = None, clock: Callable[[], float] = time.monotonic,
                 tick_interval_s: float = 0.1, monitor: bool = True) -> None:
        if max_workers < 1 or max_queue < 0:
            raise ValueError("invalid limits")
        self.max_workers, self.max_queue = max_workers, max_queue
        self._ttl, self._max_temp, self._max_result = result_ttl_s, max_temp_bytes, max_result_bytes
        self._grace, self._default_timeout = wedge_grace_s, default_timeout_s
        self._clock = clock
        self._data_dir = data_dir
        self._instance = "mgr_" + secrets.token_hex(6)
        self._temp_base = temp_root or os.path.join(_paths.data_dir(data_dir), "job-tmp")
        self._temp_root = os.path.join(self._temp_base, self._instance)      # private to this manager
        self._persist = persist
        self.persist_error: str | None = None
        self._lock = threading.RLock()
        self._persist_lock = threading.Lock()
        self._released = False                    # set under the persist lock once ownership is released
        self._jobs: dict[str, _Job] = {}
        self._order: list[str] = []
        self._by_key: dict[tuple[str, str], str] = {}
        self._closed = threading.Event()
        self._monitor: threading.Thread | None = None
        with _LIVE_LOCK:
            _LIVE[self._instance] = self
        if persist:
            self._restore()
        if monitor:
            self._monitor = threading.Thread(target=self._monitor_loop, args=(tick_interval_s,),
                                             name="foundation-jobs-monitor", daemon=True)
            self._monitor.start()

    # ------------------------------------------------------------------ public API
    def start(self, kind: str, inputs: dict, *, session_id: str, idempotency_key: str,
              worker: Worker | Callable[[JobContext], Any], timeout_s: float | None = None) -> str:
        if not isinstance(kind, str) or not _KIND_RE.match(kind):
            raise ValueError("invalid job kind")
        if not isinstance(session_id, str) or not _SESSION_RE.match(session_id):
            raise ValueError("invalid session id")
        if not isinstance(idempotency_key, str) or not _KEY_RE.match(idempotency_key):
            raise ValueError("invalid idempotency key")
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be an object")
        try:
            canon = _canonical(inputs)
        except (TypeError, ValueError):
            raise ValueError("inputs must be JSON data") from None
        revision = "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()
        timeout = self._default_timeout if timeout_s is None else float(timeout_s)
        if not (timeout > 0 and timeout < float("inf")):
            raise ValueError("invalid timeout")
        if not hasattr(worker, "run"):
            worker = _ThreadWorker(worker)             # a bare callable is a cooperative thread worker
        with self._lock:
            self._tick_locked()
            existing = self._by_key.get((session_id, idempotency_key))
            if existing is not None and existing in self._jobs:
                job = self._jobs[existing]
                if job.kind != kind or job.inputs_revision != revision:
                    raise JobRefused("idempotency_conflict", "That request id was already used for different work.")
                return job.id
            job = _Job("job_" + secrets.token_hex(12), kind, session_id, idempotency_key, revision,
                       self._clock(), timeout)
            job.inputs = freeze(json.loads(canon))
            job.worker = worker
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._by_key[(session_id, idempotency_key)] = job.id
            if self._can_reserve_launch_locked(job):
                job.launch_reserved = True
            elif self._waiting_count_locked() > self.max_queue:
                self._forget_locked(job.id)
                raise JobRefused("queue_full", "Too many jobs are waiting. Try again shortly.")
        self._save()                                    # the record exists on disk before any worker can run
        with self._lock:
            job.ready = True
            self._pump_locked()
        return job.id

    def status(self, job_id: str) -> dict:
        with self._lock:
            self._tick_locked()
            job = self._get(job_id)
            return self._status_locked(job)

    def result(self, job_id: str) -> Any:
        """The published result of a succeeded job. Late, failed, cancelled, interrupted jobs have none."""
        with self._lock:
            self._tick_locked()
            job = self._get(job_id)
            if job.state not in TERMINAL:
                raise JobRefused("not_finished", "The job has not finished.")
            if job.state != SUCCEEDED or job.late or not job.has_result:
                raise JobRefused("no_result", "The job has no result to publish.")
            return copy.deepcopy(job.result)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._get(job_id)
            if job.state == QUEUED:
                self._finish_locked(job, CANCELLED)
            elif job.state == RUNNING:
                self._request_cancel_locked(job)
            status = self._status_locked(job)
        self._save()
        return status

    def discard(self, job_id: str) -> bool:
        """Drop a finished job and its temp files now. Refuses while the worker is still alive."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state not in TERMINAL or not job.thread_done.is_set():
                raise JobRefused("still_active", "The job is still active.")
            self._forget_locked(job_id)
        self._save()
        return True

    def wedged(self) -> list[str]:
        with self._lock:
            self._tick_locked()
            return [j.id for j in self._jobs.values() if self._is_wedged(j)]

    def close(self, *, wait_s: float = 2.0) -> None:
        """Stop the monitor and ask running workers to stop. Never kills; waits briefly for them."""
        self._closed.set()
        with self._lock:
            for job in self._jobs.values():
                if job.state == QUEUED:
                    self._finish_locked(job, CANCELLED)
                elif job.state == RUNNING:
                    self._request_cancel_locked(job)
            threads = [j.thread for j in self._jobs.values() if j.thread is not None]
        deadline = time.monotonic() + wait_s
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if self._monitor is not None:
            self._monitor.join(1.0)
        self._save()
        self._release_live_if_stopped()

    # ------------------------------------------------------------------ internals
    def _get(self, job_id: str) -> _Job:
        job = self._jobs.get(job_id) if isinstance(job_id, str) else None
        if job is None:
            raise JobRefused("unknown_job", "No such job (it may have expired).")
        return job

    def _waiting_count_locked(self) -> int:
        return sum(1 for j in self._jobs.values() if j.state == QUEUED and not j.launch_reserved)

    def _slot_held(self, job: _Job) -> bool:
        return job.thread is not None and not job.thread_done.is_set()

    def _is_wedged(self, job: _Job) -> bool:
        return (self._slot_held(job) and job.cancel_at is not None
                and self._clock() - job.cancel_at >= self._grace)

    def _can_reserve_launch_locked(self, job: _Job) -> bool:
        reserved = [j for j in self._jobs.values() if j.id != job.id and j.launch_reserved
                    and j.state == QUEUED]
        held = [j for j in self._jobs.values() if self._slot_held(j)]
        return (len(held) + len(reserved) < self.max_workers
                and job.kind not in {j.kind for j in held + reserved})

    def _release_live_if_stopped(self) -> None:
        """Drop this manager from _LIVE only as the LAST persistence step.

        An open manager stays discoverable. Once closed with every slot free, release takes the persist
        lock (so any save already in progress has finished), writes a FRESH snapshot of the current
        records, and only then removes the manager. A replacement manager can therefore never adopt a
        record as interrupted while a terminal state is still waiting to be saved.
        """
        with self._persist_lock:
            with self._lock:
                running = any(self._slot_held(job) for job in self._jobs.values())
                closed = self._closed.is_set()
            if not closed or running:
                return
            self._save_locked()                                  # fresh snapshot, persist lock held
            with _LIVE_LOCK:
                _LIVE.pop(self._instance, None)
            self._released = True                                # never write again: a replacement may own the file

    def _pump_locked(self) -> None:
        if self._closed.is_set():
            return
        held = [j for j in self._jobs.values() if self._slot_held(j)]
        busy_kinds = {j.kind for j in held}
        free = self.max_workers - len(held)
        # A reservation is a promise of capacity: reserved jobs launch first, and a reserved job whose
        # record is still being persisted keeps its slot and kind against every unreserved waiter.
        for job_id in self._order:
            job = self._jobs.get(job_id)
            if job is None or job.state != QUEUED or not job.launch_reserved or not job.ready:
                continue
            if free <= 0:
                break
            job.launch_reserved = False
            self._launch_locked(job)
            busy_kinds.add(job.kind)
            free -= 1
        pending = [j for j in self._jobs.values()
                   if j.state == QUEUED and j.launch_reserved and not j.ready]
        free -= len(pending)
        busy_kinds |= {j.kind for j in pending}
        if free <= 0:
            return
        for job_id in self._order:
            job = self._jobs.get(job_id)
            if (job is None or job.state != QUEUED or not job.ready or job.launch_reserved
                    or job.kind in busy_kinds):
                continue
            self._launch_locked(job)
            busy_kinds.add(job.kind)
            free -= 1
            if free <= 0:
                break

    def _launch_locked(self, job: _Job) -> None:
        job.state = RUNNING
        job.started = self._clock()
        job.ctx = JobContext(job.id, job.inputs, os.path.join(self._temp_root, job.id), self._max_temp,
                             lambda stage, frac, j=job: self._set_progress(j, stage, frac))
        job.thread = threading.Thread(target=self._run, args=(job,), name=f"foundation-job-{job.id}", daemon=True)
        job.thread.start()

    @staticmethod
    def _set_progress(job: _Job, stage: str | None, fraction: float | None) -> None:
        job.stage = stage if isinstance(stage, str) else None
        job.fraction = float(fraction) if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) else None

    def _run(self, job: _Job) -> None:
        outcome: tuple = ("failed", None, {"code": "worker_error", "message": "The job failed."})
        try:
            value = job.worker.run(job.ctx)
            size = len(_canonical(value).encode("utf-8")) if value is not None else 0
            if size > self._max_result:
                outcome = ("failed", None, {"code": "result_too_large", "message": "The job result was too large."})
            elif self._temp_bytes(job) > self._max_temp:
                outcome = ("failed", None, {"code": "temp_budget_exceeded", "message": "The job used too much temporary space."})
            else:
                outcome = ("ok", value, None)
        except JobCancelled:
            outcome = ("cancelled", None, None)
        except JobLimitError:
            outcome = ("failed", None, {"code": "temp_budget_exceeded", "message": "The job used too much temporary space."})
        except JobFailure as exc:
            outcome = ("failed", None, {"code": _bounded_code(exc.code), "message": str(exc)})
        except BaseException:                                   # noqa: BLE001 - a worker must never kill the pool
            outcome = ("failed", None, {"code": "worker_error", "message": "The job failed."})
        with self._lock:
            self._conclude_locked(job, outcome)
            job.thread_done.set()                               # the slot is free only from here
            self._pump_locked()
        self._save()
        self._release_live_if_stopped()

    def _conclude_locked(self, job: _Job, outcome: tuple) -> None:
        kind, value, error = outcome
        if job.state in TERMINAL:                               # e.g. interrupted at close; first terminal wins
            self._remove_temp(job)
            return
        if job.state == CANCEL_REQUESTED:
            if kind == "ok":
                job.late = True                                 # finished before the stop was acknowledged
                self._finish_locked(job, SUCCEEDED, error=None)
            elif kind == "cancelled":
                self._finish_locked(job, CANCELLED)
            else:
                self._finish_locked(job, FAILED, error=error)
            self._remove_temp(job)                              # nothing produced after a cancel is published
            return
        if kind == "ok":
            job.result, job.has_result = value, True
            self._finish_locked(job, SUCCEEDED)
        elif kind == "cancelled":
            self._finish_locked(job, CANCELLED)
            self._remove_temp(job)
        else:
            self._finish_locked(job, FAILED, error=error)
            self._remove_temp(job)

    def _finish_locked(self, job: _Job, state: str, *, error: dict | None = None) -> None:
        if job.state in TERMINAL:
            return
        job.state, job.finished, job.error = state, self._clock(), error
        if job.thread is None:
            job.thread_done.set()
        job.inputs = None                                        # frozen inputs are not kept past the end

    def _request_cancel_locked(self, job: _Job) -> None:
        if job.state != RUNNING:
            return
        job.state = CANCEL_REQUESTED
        job.cancel_at = self._clock()
        job.ctx._cancel.set()
        try:
            job.worker.cancel()
        except Exception:                                       # noqa: BLE001 - a broken cancel must not hide the state
            pass

    def _tick_locked(self) -> None:
        now = self._clock()
        for job in list(self._jobs.values()):
            if job.state == RUNNING and job.started is not None and now - job.started >= job.timeout_s:
                job.timed_out = True
                self._request_cancel_locked(job)
            if self._slot_held(job) and job.cancel_at is not None and not job.killed \
                    and now - job.cancel_at >= self._grace:
                job.killed = True                               # process workers die here; a thread just stays wedged
                try:
                    job.worker.kill()
                except Exception:                               # noqa: BLE001
                    pass
        self._evict_locked(now)
        self._pump_locked()

    def _evict_locked(self, now: float) -> None:
        done = [j for j in self._jobs.values() if j.state in TERMINAL and j.thread_done.is_set()]
        done.sort(key=lambda j: j.finished or 0.0)
        excess = max(0, len(done) - MAX_TERMINAL_JOBS)
        for index, job in enumerate(done):
            if index < excess or (job.finished is not None and now - job.finished >= self._ttl):
                self._forget_locked(job.id)

    def _forget_locked(self, job_id: str) -> None:
        job = self._jobs.pop(job_id, None)
        if job is None:
            return
        if job_id in self._order:
            self._order.remove(job_id)
        if self._by_key.get((job.session_id, job.key)) == job_id:
            del self._by_key[(job.session_id, job.key)]
        self._remove_temp(job)

    def _remove_temp(self, job: _Job) -> None:
        shutil.rmtree(os.path.join(self._temp_root, job.id), ignore_errors=True)

    def _temp_bytes(self, job: _Job) -> int:
        total = 0
        for base, _dirs, files in os.walk(os.path.join(self._temp_root, job.id)):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                except OSError:
                    pass
        return total

    def _status_locked(self, job: _Job) -> dict:
        wedged = self._is_wedged(job)
        out = {"job_id": job.id, "kind": job.kind, "state": job.state, "inputs_revision": job.inputs_revision,
               "wedged": wedged, "timed_out": job.timed_out, "late": job.late,
               "stage": job.stage, "fraction": job.fraction, "error": dict(job.error) if job.error else None,
               "result_available": job.state == SUCCEEDED and job.has_result and not job.late}
        if wedged:
            out["note"] = WEDGED_NOTE
        if job.persist_only:
            out["restored"] = True
        return out

    def _monitor_loop(self, interval: float) -> None:
        while not self._closed.wait(interval):
            with self._lock:
                self._tick_locked()

    # ------------------------------------------------------------------ persistence (records only)
    def _records(self) -> list[dict]:
        with self._lock:
            out = []
            for job_id in self._order:
                job = self._jobs.get(job_id)
                if job is None:
                    continue
                out.append({"job_id": job.id, "kind": job.kind, "state": job.state, "session_id": job.session_id,
                            "idempotency_key": job.key, "owner": self._instance, "inputs_revision": job.inputs_revision,
                            "late": job.late, "timed_out": job.timed_out,
                            "error": dict(job.error) if job.error else None})
            return out[-MAX_TERMINAL_JOBS:]

    def _save(self) -> None:
        if not self._persist:
            return
        with self._persist_lock:
            self._save_locked()

    def _save_locked(self) -> None:
        """Write a fresh snapshot of the records. The caller holds the persist lock."""
        if not self._persist or self._released:
            return
        try:
            records = self._records()
        except Exception:                                       # noqa: BLE001
            self.persist_error = "job_records_not_saved"
            return
        for _ in range(3):
            try:
                current = store.read_json(JOBS_STORE, schema=JOBS_SCHEMA, version=JOBS_SCHEMA_VERSION,
                                          data_dir=self._data_dir)
                if current.value is None:
                    self.persist_error = "job_records_unreadable"
                    return
                mine = {r["job_id"] for r in records}
                others = [r for r in (current.value.get("jobs") or []) if isinstance(r, dict)
                          and r.get("job_id") not in mine and r.get("owner") != self._instance]
                merged = (others + records)[-MAX_TERMINAL_JOBS:] if others else records
                store.write_json(JOBS_STORE, {"jobs": merged}, expected_revision=current.value["revision"],
                                 schema=JOBS_SCHEMA, version=JOBS_SCHEMA_VERSION, data_dir=self._data_dir)
                self.persist_error = None
                return
            except store.RevisionConflict:
                continue
            except Exception:                                   # noqa: BLE001 - never strand _LIVE on a save failure
                self.persist_error = "job_records_not_saved"
                return
        self.persist_error = "job_records_not_saved"            # every retry lost the revision race

    def _restore(self) -> None:
        """Mark work that was in flight when the last engine stopped as interrupted. Nothing is replayed."""
        current = store.read_json(JOBS_STORE, schema=JOBS_SCHEMA, version=JOBS_SCHEMA_VERSION, data_dir=self._data_dir)
        records = current.value.get("jobs", []) if current.value else []
        if current.value is None:
            self.persist_error = "job_records_unreadable"
        adopted: list[tuple[str, str]] = []
        for rec in records if isinstance(records, list) else []:
            try:
                job = _Job(rec["job_id"], rec["kind"], rec["session_id"], rec["idempotency_key"],
                           rec["inputs_revision"], self._clock(), self._default_timeout)
                state = rec["state"]
            except (KeyError, TypeError):
                continue
            if state not in STATES or not isinstance(job.id, str):
                continue
            owner = rec.get("owner") if isinstance(rec.get("owner"), str) else ""
            with _LIVE_LOCK:
                live_elsewhere = owner != self._instance and owner in _LIVE
            if live_elsewhere:
                continue                                         # another open manager's work: not ours to touch
            job.state = INTERRUPTED if state in (QUEUED, RUNNING, CANCEL_REQUESTED) else state
            job.persist_only, job.finished = True, self._clock()
            job.late, job.timed_out = bool(rec.get("late")), bool(rec.get("timed_out"))
            job.error = rec.get("error") if isinstance(rec.get("error"), dict) else None
            if job.state == INTERRUPTED and job.error is None:
                job.error = {"code": "interrupted", "message": "The engine stopped before this job finished."}
            job.thread_done.set()
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._by_key[(job.session_id, job.key)] = job.id
            adopted.append((owner, job.id))
        # Orphaned temp files: only those of the jobs just restored (nothing is replayed to use them).
        for owner, job_id in adopted:
            if re.fullmatch(r"[A-Za-z0-9_]+", job_id) is None:
                continue
            paths = [os.path.join(self._temp_base, job_id)]                  # layout before per-manager subdirs
            if re.fullmatch(r"mgr_[0-9a-f]+", owner) is not None:
                paths.append(os.path.join(self._temp_base, owner, job_id))
            for path in paths:
                shutil.rmtree(path, ignore_errors=True)
            if paths[1:]:
                try:
                    os.rmdir(os.path.dirname(paths[1]))                      # only if now empty
                except OSError:
                    pass
        self._save()


def default_manager(*, data_dir: str | None = None, persist: bool = True) -> JobManager:
    """The one process-wide manager. Later calls return it; the arguments only matter on the first call.

    Use this instead of constructing managers: a second manager would split the worker limits."""
    global _DEFAULT
    with _LIVE_LOCK:
        existing = _DEFAULT
    if existing is not None and not existing._closed.is_set():
        return existing
    manager = JobManager(persist=persist, data_dir=data_dir)
    with _LIVE_LOCK:
        if _DEFAULT is not None and not _DEFAULT._closed.is_set():
            winner = _DEFAULT
        else:
            _DEFAULT, winner = manager, manager
    if winner is not manager:
        manager.close(wait_s=0.0)
    return winner


def reset_default_manager() -> None:
    """Close and forget the process-wide manager (tests and orderly shutdown)."""
    global _DEFAULT
    with _LIVE_LOCK:
        manager, _DEFAULT = _DEFAULT, None
    if manager is not None:
        manager.close()
