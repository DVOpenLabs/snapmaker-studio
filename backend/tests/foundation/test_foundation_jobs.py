"""Jobs: idempotency, bounds, cancellation, wedged workers, late results, restart."""
import ast
import glob
import json
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from snapstudio_core.foundation import jobs as J

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FOUNDATION = os.path.join(BACKEND, "snapstudio_core", "foundation")
SESSION = "session-aaaaaaaa"


def key(n):
    return f"request-key-{n:04d}"


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def make(tmp_path):
    created = []

    def build(**kw):
        kw.setdefault("temp_root", str(tmp_path / "tmp"))
        kw.setdefault("tick_interval_s", 0.01)
        m = J.JobManager(**kw)
        created.append(m)
        return m

    yield build
    for m in created:
        m.close(wait_s=0.5)


class Blocker:
    """A cooperative worker that runs until released or cancelled."""

    def __init__(self, result="done"):
        self.started = threading.Event()
        self.release = threading.Event()
        self.result = result

    def __call__(self, ctx):
        self.started.set()
        while not self.release.wait(0.005):
            ctx.check()
        return self.result


def state(m, job_id):
    return m.status(job_id)["state"]


# ------------------------------------------------------------------ basics
def test_job_runs_and_publishes_result(make):
    m = make()
    jid = m.start("demo", {"a": 1}, session_id=SESSION, idempotency_key=key(1), worker=lambda ctx: {"sum": ctx.inputs["a"] + 1})
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert m.result(jid) == {"sum": 2}
    assert m.status(jid)["result_available"] is True


def test_duplicate_start_with_same_key_returns_same_job_even_after_finish(make):
    m = make()
    calls = []
    jid = m.start("demo", {"a": 1}, session_id=SESSION, idempotency_key=key(1), worker=lambda ctx: calls.append(1) or 1)
    again = m.start("demo", {"a": 1}, session_id=SESSION, idempotency_key=key(1), worker=lambda ctx: calls.append(2) or 2)
    assert again == jid
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert m.start("demo", {"a": 1}, session_id=SESSION, idempotency_key=key(1), worker=lambda ctx: 3) == jid
    assert calls == [1]


def test_same_key_different_work_is_refused_and_other_session_is_independent(make):
    m = make()
    gate = Blocker()
    jid = m.start("demo", {"a": 1}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    with pytest.raises(J.JobRefused) as exc:
        m.start("demo", {"a": 2}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    assert exc.value.code == "idempotency_conflict"
    other = m.start("demo", {"a": 1}, session_id="session-bbbbbbbb", idempotency_key=key(1), worker=lambda c: 1)
    assert other != jid
    gate.release.set()


@pytest.mark.parametrize("kw", [
    {"kind": "Bad Kind"}, {"session_id": "x"}, {"idempotency_key": "short"}, {"inputs": [1]},
    {"inputs": {"a": object()}}, {"inputs": {"a": float("nan")}}, {"timeout_s": 0}, {"timeout_s": float("inf")},
])
def test_start_validates_arguments(make, kw):
    m = make()
    args = dict(kind="demo", inputs={}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 1)
    args.update(kw)
    kind, inputs = args.pop("kind"), args.pop("inputs")
    with pytest.raises(ValueError):
        m.start(kind, inputs, **args)


def test_inputs_are_frozen_and_revisioned(make):
    m = make(max_workers=1)
    data = {"nested": {"list": [1, 2]}}
    seen = {"blocked": 0}

    def worker(ctx):
        try:
            ctx.inputs["x"] = 1
        except TypeError:
            seen["blocked"] += 1
        try:
            ctx.inputs["nested"]["y"] = 1
        except TypeError:
            seen["blocked"] += 1
        seen["list"] = list(ctx.inputs["nested"]["list"])
        return ctx.inputs["nested"]["list"][1]

    gate = Blocker()
    m.start("a", {}, session_id=SESSION, idempotency_key=key(0), worker=gate)
    jid = m.start("b", data, session_id=SESSION, idempotency_key=key(1), worker=worker)
    data["nested"]["list"].append(99)           # the caller mutates after start: must not leak in
    rev = m.status(jid)["inputs_revision"]
    gate.release.set()
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert m.result(jid) == 2 and seen == {"blocked": 2, "list": [1, 2]}
    assert rev.startswith("sha256:") and rev == m.status(jid)["inputs_revision"]
    same = make().start("b", {"nested": {"list": [1, 2]}}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 0)
    assert same  # a different manager is a different namespace; revision equality is checked below
    m3 = make()
    j3 = m3.start("b", {"nested": {"list": [1, 2]}}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 0)
    assert m3.status(j3)["inputs_revision"] == rev


def test_status_never_exposes_inputs(make):
    m = make()
    jid = m.start("demo", {"api_key": "SENTINEL-KEY-9f3a"}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 1)
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert "SENTINEL-KEY-9f3a" not in json.dumps(m.status(jid))


# ------------------------------------------------------------------ bounds
def test_per_kind_slot_limit_one(make):
    m = make(max_workers=2)
    first, second = Blocker(), Blocker()
    a = m.start("same", {}, session_id=SESSION, idempotency_key=key(1), worker=first)
    b = m.start("same", {}, session_id=SESSION, idempotency_key=key(2), worker=second)
    assert first.started.wait(2)
    time.sleep(0.05)
    assert state(m, a) == J.RUNNING and state(m, b) == J.QUEUED and not second.started.is_set()
    first.release.set()
    assert second.started.wait(2)
    second.release.set()


def test_waiting_limit_counts_same_kind_jobs_even_with_free_global_slots(make):
    m = make(max_workers=2, max_queue=0)
    first = Blocker()
    a = m.start("same", {}, session_id=SESSION, idempotency_key=key(81), worker=first)
    assert first.started.wait(2)
    with pytest.raises(J.JobRefused) as exc:
        m.start("same", {}, session_id=SESSION, idempotency_key=key(82), worker=Blocker())
    assert exc.value.code == "queue_full"
    assert state(m, a) == J.RUNNING


def test_default_waiting_limit_allows_one_running_and_eight_waiting(make):
    m = make()
    gates = [Blocker() for _ in range(10)]
    accepted = []
    for i, gate in enumerate(gates):
        try:
            accepted.append(m.start("same", {}, session_id=SESSION, idempotency_key=key(100 + i), worker=gate))
        except J.JobRefused as exc:
            assert exc.code == "queue_full"
    assert len(accepted) == 9
    assert wait_for(lambda: sum(state(m, jid) == J.RUNNING for jid in accepted) == 1)
    assert sum(state(m, jid) == J.QUEUED for jid in accepted) == 8


def test_close_keeps_live_owner_until_wedged_worker_stops(tmp_path):
    root, temp = str(tmp_path / "data"), str(tmp_path / "tmp")
    started, release = threading.Event(), threading.Event()

    def wedged(ctx):
        os.makedirs(ctx.temp_dir, exist_ok=True)
        with open(os.path.join(ctx.temp_dir, "owned.tmp"), "w") as fh:
            fh.write("owned")
        started.set()
        release.wait(5)                    # deliberately ignores cancellation
        return "done"

    owner = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False, wedge_grace_s=0)
    job = owner.start("same", {}, session_id=SESSION, idempotency_key=key(91), worker=wedged)
    assert started.wait(2)
    owned_path = os.path.join(temp, owner._instance, job, "owned.tmp")
    owner.close(wait_s=0)
    assert owner._instance in J._LIVE
    early = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False)
    try:
        assert job not in early._jobs
        assert os.path.exists(owned_path)
    finally:
        early.close(wait_s=0)
    release.set()
    assert wait_for(lambda: owner._jobs[job].thread_done.is_set())
    assert wait_for(lambda: owner._instance not in J._LIVE)       # released after the final save
    restored = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False)
    try:
        assert job in restored._jobs
        assert not os.path.exists(owned_path)
    finally:
        restored.close(wait_s=0)


def test_release_is_the_last_persistence_step_after_a_stalled_close_save(tmp_path, monkeypatch):
    root, temp = str(tmp_path / "data"), str(tmp_path / "tmp")
    started, release = threading.Event(), threading.Event()
    in_write, go_write = threading.Event(), threading.Event()

    def worker(ctx):
        started.set()
        release.wait(5)                    # ignores cancellation, then finishes
        return "done"

    owner = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False)
    job = owner.start("same", {}, session_id=SESSION, idempotency_key=key(92), worker=worker)
    assert started.wait(2)
    real_write, state = J.store.write_json, {"armed": True}

    def stalling_write(*args, **kwargs):
        if state["armed"] and threading.current_thread().name == "closer":
            state["armed"] = False
            in_write.set()                 # close() has its (older) snapshot and is stuck persisting it
            go_write.wait(5)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(J.store, "write_json", stalling_write)
    closer = threading.Thread(target=lambda: owner.close(wait_s=0), name="closer")
    closer.start()
    try:
        assert in_write.wait(2)
        release.set()                      # the worker concludes and queues its final terminal save
        assert wait_for(lambda: owner._jobs[job].thread_done.is_set())
        assert owner._instance in J._LIVE
        rival = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False)
        try:
            assert job not in rival._jobs                  # not adopted while the owner is still live
        finally:
            rival.close(wait_s=0)
    finally:
        go_write.set()
        closer.join(5)
    assert wait_for(lambda: owner._instance not in J._LIVE)
    with open(os.path.join(root, "store", "foundation_jobs.json")) as fh:
        disk = json.load(fh)["jobs"]
    mine = [r for r in disk if r["job_id"] == job]
    assert mine and mine[0]["state"] == J.SUCCEEDED         # terminal state was persisted before release
    later = J.JobManager(persist=True, data_dir=root, temp_root=temp, monitor=False)
    try:
        assert later._jobs[job].state == J.SUCCEEDED         # adopted as recorded, not as interrupted
    finally:
        later.close(wait_s=0)


def test_global_workers_bound_and_explicit_queue_full_refusal(make):
    m = make(max_workers=2, max_queue=2)
    gates = [Blocker() for _ in range(5)]
    ids = [m.start(f"k{i}", {}, session_id=SESSION, idempotency_key=key(i), worker=gates[i]) for i in range(4)]
    assert gates[0].started.wait(2) and gates[1].started.wait(2)
    time.sleep(0.05)
    assert [state(m, i) for i in ids] == [J.RUNNING, J.RUNNING, J.QUEUED, J.QUEUED]
    with pytest.raises(J.JobRefused) as exc:
        m.start("k4", {}, session_id=SESSION, idempotency_key=key(4), worker=gates[4])
    assert exc.value.code == "queue_full"
    assert not gates[4].started.is_set()
    # the refused request left no job behind: a retry with the same key is a fresh attempt
    gates[0].release.set()
    assert wait_for(lambda: state(m, ids[2]) == J.RUNNING)
    retry = m.start("k4", {}, session_id=SESSION, idempotency_key=key(4), worker=gates[4])
    assert retry not in ids
    for g in gates:
        g.release.set()


def test_result_size_is_bounded(make):
    m = make(max_result_bytes=100)
    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: {"blob": "x" * 500})
    assert wait_for(lambda: state(m, jid) == J.FAILED)
    assert m.status(jid)["error"]["code"] == "result_too_large"
    with pytest.raises(J.JobRefused):
        m.result(jid)


def test_temp_budget_claims_and_final_scan_are_bounded(make):
    m = make(max_temp_bytes=1000)

    def claims(ctx):
        ctx.claim_temp_bytes(600)
        ctx.claim_temp_bytes(600)

    def writes(ctx):
        with open(ctx.temp_path("big.bin"), "wb") as fh:
            fh.write(b"x" * 2000)
        return "wrote"

    a = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=claims)
    b = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=writes)
    assert wait_for(lambda: state(m, a) == J.FAILED and state(m, b) == J.FAILED)
    assert m.status(a)["error"]["code"] == "temp_budget_exceeded"
    assert m.status(b)["error"]["code"] == "temp_budget_exceeded"
    assert wait_for(lambda: not os.path.exists(os.path.join(m._temp_root, b)))


def test_temp_path_rejects_traversal(make):
    m = make()
    out = {}

    def worker(ctx):
        for bad in ("../x", "a/b", "", ".."):
            try:
                ctx.temp_path(bad)
            except ValueError:
                out[bad] = True

    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=worker)
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert len(out) == 4


# ------------------------------------------------------------------ failures
def test_worker_exception_is_reported_generically_without_leaking_message(make):
    m = make()

    def boom(ctx):
        raise RuntimeError("Authorization: Bearer SENTINEL-KEY-9f3a")

    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=boom)
    assert wait_for(lambda: state(m, jid) == J.FAILED)
    assert "SENTINEL" not in json.dumps(m.status(jid))
    assert m.status(jid)["error"]["code"] == "worker_error"


def test_job_failure_message_is_shown(make):
    m = make()

    def refuse(ctx):
        raise J.JobFailure("no_service", "The local service did not answer.")

    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=refuse)
    assert wait_for(lambda: state(m, jid) == J.FAILED)
    assert m.status(jid)["error"] == {"code": "no_service", "message": "The local service did not answer."}


def test_unknown_and_unfinished_job_answers(make):
    m = make()
    with pytest.raises(J.JobRefused) as exc:
        m.status("job_nope")
    assert exc.value.code == "unknown_job"
    gate = Blocker()
    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    with pytest.raises(J.JobRefused) as exc:
        m.result(jid)
    assert exc.value.code == "not_finished"
    gate.release.set()


# ------------------------------------------------------------------ cancel
def test_cancel_before_start_is_cancelled_and_never_runs(make):
    m = make(max_workers=1)
    gate, ran = Blocker(), threading.Event()
    m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    queued = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: ran.set())
    assert gate.started.wait(2)
    assert m.cancel(queued)["state"] == J.CANCELLED
    gate.release.set()
    time.sleep(0.1)
    assert not ran.is_set() and state(m, queued) == J.CANCELLED
    with pytest.raises(J.JobRefused):
        m.result(queued)


def test_cancel_running_goes_through_cancel_requested_and_slot_stays_until_stopped(make):
    m = make(max_workers=1)
    release_stop = threading.Event()
    started = threading.Event()

    def slow_stopper(ctx):
        started.set()
        ctx.wait(60)                       # woken by cancel
        release_stop.wait(5)               # ...but takes a while to actually stop
        ctx.check()

    a = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=slow_stopper)
    b = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: "b-ran")
    assert started.wait(2)
    assert m.cancel(a)["state"] == J.CANCEL_REQUESTED
    time.sleep(0.1)
    assert state(m, a) == J.CANCEL_REQUESTED and state(m, b) == J.QUEUED    # slot not yet free
    release_stop.set()
    assert wait_for(lambda: state(m, a) == J.CANCELLED)
    assert wait_for(lambda: state(m, b) == J.SUCCEEDED)


def test_late_success_after_cancel_is_not_published_and_temp_removed(make):
    m = make()
    started, finish = threading.Event(), threading.Event()
    paths = {}

    def ignores_then_succeeds(ctx):
        paths["f"] = ctx.temp_path("out.bin")
        open(paths["f"], "wb").write(b"artifact")
        started.set()
        finish.wait(5)
        return {"artifact": paths["f"]}

    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=ignores_then_succeeds)
    assert started.wait(2)
    m.cancel(jid)
    finish.set()
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    st = m.status(jid)
    assert st["late"] is True and st["result_available"] is False
    with pytest.raises(J.JobRefused) as exc:
        m.result(jid)
    assert exc.value.code == "no_result"
    assert wait_for(lambda: not os.path.exists(paths["f"]))


def test_normal_success_keeps_temp_until_discard(make):
    m = make()
    paths = {}

    def worker(ctx):
        paths["f"] = ctx.temp_path("out.bin")
        open(paths["f"], "wb").write(b"artifact")
        return {"artifact": paths["f"]}

    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=worker)
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert os.path.exists(paths["f"])
    assert m.discard(jid) is True
    assert not os.path.exists(paths["f"])
    with pytest.raises(J.JobRefused):
        m.status(jid)


def test_discard_refuses_active_job(make):
    m = make()
    gate = Blocker()
    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    with pytest.raises(J.JobRefused) as exc:
        m.discard(jid)
    assert exc.value.code == "still_active"
    gate.release.set()


# ------------------------------------------------------------------ timeout and wedged
def test_timeout_requests_cancel_and_marks_timed_out(make):
    m = make()
    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=Blocker(), timeout_s=0.1)
    assert wait_for(lambda: state(m, jid) == J.CANCELLED)
    assert m.status(jid)["timed_out"] is True


def test_wedged_thread_keeps_slot_is_reported_and_blocks_its_kind(make):
    m = make(wedge_grace_s=0.1)
    stuck = threading.Event()
    started = threading.Event()

    def ignores_cancel(ctx):
        started.set()
        stuck.wait(10)                      # never looks at ctx.cancelled

    a = m.start("same", {}, session_id=SESSION, idempotency_key=key(1), worker=ignores_cancel)
    b = m.start("same", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: "second")
    assert started.wait(2)
    m.cancel(a)
    assert wait_for(lambda: m.status(a)["wedged"] is True)
    st = m.status(a)
    assert st["state"] == J.CANCEL_REQUESTED and "restart" in st["note"].lower()
    assert m.wedged() == [a]
    time.sleep(0.15)
    assert state(m, b) == J.QUEUED                       # the stuck thread still owns the kind's slot
    stuck.set()                                          # in a test we can let it go; production needs a restart
    assert wait_for(lambda: state(m, b) == J.SUCCEEDED)
    assert m.status(a)["wedged"] is False


def test_wedged_job_holds_a_global_slot(make):
    m = make(max_workers=1, wedge_grace_s=0.05)
    stuck, started = threading.Event(), threading.Event()
    a = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: (started.set(), stuck.wait(10)))
    b = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: "b")
    assert started.wait(2)
    m.cancel(a)
    time.sleep(0.2)
    assert m.status(a)["wedged"] and state(m, b) == J.QUEUED
    stuck.set()
    assert wait_for(lambda: state(m, b) == J.SUCCEEDED)


class ProcessLikeWorker:
    """Implements the worker protocol the way cli_runner will: cancel() asks, kill() forces."""

    def __init__(self):
        self.calls, self.stop = [], threading.Event()

    def run(self, ctx):
        self.stop.wait(10)
        return "late"

    def cancel(self):
        self.calls.append("cancel")

    def kill(self):
        self.calls.append("kill")
        self.stop.set()


def test_protocol_worker_gets_cancel_then_kill_after_grace_and_slot_frees_when_it_stops(make):
    m = make(wedge_grace_s=0.1)
    worker = ProcessLikeWorker()
    jid = m.start("proc", {}, session_id=SESSION, idempotency_key=key(1), worker=worker, timeout_s=0.1)
    assert wait_for(lambda: state(m, jid) in J.TERMINAL, timeout=5)
    assert worker.calls == ["cancel", "kill"]
    assert m.status(jid)["late"] is True and m.status(jid)["timed_out"] is True
    nxt = m.start("proc", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: "next")
    assert wait_for(lambda: state(m, nxt) == J.SUCCEEDED)


# ------------------------------------------------------------------ retention
def test_terminal_jobs_expire_after_ttl(make):
    now = [100.0]
    m = make(result_ttl_s=10, clock=lambda: now[0], monitor=False)
    jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 1)
    assert wait_for(lambda: m._jobs[jid].thread_done.is_set())
    assert m.status(jid)["state"] == J.SUCCEEDED
    now[0] += 11
    with pytest.raises(J.JobRefused) as exc:
        m.status(jid)
    assert exc.value.code == "unknown_job"
    # the key is free again after expiry
    assert m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 1) != jid


# ------------------------------------------------------------------ restart
def run_child(root, code):
    env = {**os.environ, "SNAPSTUDIO_DATA_DIR": root, "PYTHONPATH": BACKEND}
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(code).replace("__ROOT__", repr(root))],
                            cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


CRASHER = """
import os, sys, time
from snapstudio_core.foundation import jobs as J
root = __ROOT__
m = J.JobManager(persist=True, data_dir=root)

def worker(ctx):
    open(ctx.temp_path('partial.bin'), 'wb').write(b'written before the crash')
    print('written', ctx.job_id, flush=True)
    time.sleep(60)

jid = m.start('crashy', {'api_key': 'SENTINEL-KEY-9f3a'}, session_id='session-aaaaaaaa',
              idempotency_key='request-key-0001', worker=worker)
time.sleep(60)
"""


def test_crash_after_file_write_leaves_no_result_and_restart_marks_interrupted_and_cleans_temp(tmp_path):
    root = str(tmp_path / "data")
    proc = run_child(root, CRASHER)
    try:
        line = proc.stdout.readline().decode().strip()
        assert line.startswith("written job_"), proc.stderr.read1().decode() if proc.poll() else line
        job_id = line.split()[1]
        found = glob.glob(os.path.join(root, "job-tmp", "*", job_id, "partial.bin"))
        assert len(found) == 1
        orphan = found[0]
        assert os.path.exists(orphan)
    finally:
        proc.kill()
        proc.wait()
    assert os.path.exists(orphan)                                  # the crash left it behind
    m = J.JobManager(persist=True, data_dir=root, monitor=False)
    try:
        st = m.status(job_id)
        assert st["state"] == J.INTERRUPTED and st["restored"] is True
        assert st["error"]["code"] == "interrupted"
        with pytest.raises(J.JobRefused) as exc:
            m.result(job_id)
        assert exc.value.code == "no_result"
        assert not os.path.exists(orphan) and not os.path.exists(os.path.dirname(orphan))
        # the client's retry after the crash returns the same (interrupted) job and replays nothing
        ran = []
        again = m.start("crashy", {"api_key": "SENTINEL-KEY-9f3a"}, session_id="session-aaaaaaaa",
                        idempotency_key="request-key-0001", worker=lambda c: ran.append(1))
        assert again == job_id and ran == []
        time.sleep(0.1)
        assert state(m, job_id) == J.INTERRUPTED
    finally:
        m.close(wait_s=0.5)
    store_dir = os.path.join(root, "store")
    blob = "".join(open(os.path.join(store_dir, n), encoding="utf-8").read() for n in os.listdir(store_dir) if n.endswith(".json"))
    assert "SENTINEL-KEY-9f3a" not in blob                          # records carry no inputs


def test_restart_keeps_finished_records_and_interrupts_in_flight(tmp_path):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, tick_interval_s=0.01)
    done = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: "ok")
    gate = Blocker()
    running = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=gate)
    queued = m.start("b", {}, session_id=SESSION, idempotency_key=key(3), worker=Blocker())
    assert wait_for(lambda: state(m, done) == J.SUCCEEDED) and gate.started.wait(2)
    assert wait_for(lambda: m.persist_error is None and len(json.load(open(os.path.join(root, "store", "foundation_jobs.json")))["jobs"]) == 3)
    J._LIVE.pop(m._instance)                                            # the first "process" is gone (it never closes)
    m2 = J.JobManager(persist=True, data_dir=root, monitor=False)       # a second "process" starts
    try:
        assert state(m2, done) == J.SUCCEEDED
        assert state(m2, running) == J.INTERRUPTED and state(m2, queued) == J.INTERRUPTED
        with pytest.raises(J.JobRefused):
            m2.result(done)                                              # restored records never carry results
    finally:
        gate.release.set()
        m.close(wait_s=0.5)
        m2.close(wait_s=0.5)


def test_released_manager_never_rewrites_the_store(tmp_path):
    root = str(tmp_path / "data")
    old = J.JobManager(persist=True, data_dir=root, monitor=False)
    jid = old.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: "ok")
    assert wait_for(lambda: state(old, jid) == J.SUCCEEDED)
    old.close(wait_s=0.5)
    assert old._instance not in J._LIVE
    path = os.path.join(root, "store", "foundation_jobs.json")
    with open(path, "rb") as fh:
        before = fh.read()
    old.cancel(jid)                                                     # on a released manager: no write
    old.discard(jid)
    with open(path, "rb") as fh:
        assert fh.read() == before
    assert json.loads(before)["jobs"][0]["job_id"] == jid


def test_failure_code_that_is_not_json_is_bounded_and_persisted(tmp_path):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, monitor=False)

    def bad(ctx):
        raise J.JobFailure(object(), "shown message")

    jid = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=bad)
    assert wait_for(lambda: state(m, jid) == J.FAILED)
    code = m.status(jid)["error"]["code"]
    assert isinstance(code, str) and 0 < len(code) <= 64
    m.close(wait_s=0.5)
    assert m.persist_error is None
    assert m._instance not in J._LIVE
    with open(os.path.join(root, "store", "foundation_jobs.json")) as fh:
        assert json.load(fh)["jobs"][0]["error"]["code"] == code


def test_any_save_exception_and_exhausted_retries_set_persist_error_and_release(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, monitor=False)
    jid = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: "ok")
    assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    assert wait_for(lambda: m.persist_error is None)

    def boom(*a, **k):
        raise TypeError("not serialisable")

    monkeypatch.setattr(J.store, "write_json", boom)
    m._save()
    assert m.persist_error == "job_records_not_saved"                   # a non-store exception is contained
    m.persist_error = None

    def conflict(*a, **k):
        raise J.store.RevisionConflict("lost the race")

    monkeypatch.setattr(J.store, "write_json", conflict)
    m._save()
    assert m.persist_error == "job_records_not_saved"                   # retries exhausted is not silent
    m.close(wait_s=0.5)
    assert m._instance not in J._LIVE                                   # _LIVE is never stranded


def test_second_persisted_manager_leaves_a_live_managers_temp_and_records_alone(tmp_path):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, tick_interval_s=0.01)
    gate = Blocker()
    seen = {}

    def worker(ctx):
        seen["path"] = ctx.temp_path("live.bin")
        open(seen["path"], "wb").write(b"live")
        return gate(ctx)

    jid = m.start("live", {}, session_id=SESSION, idempotency_key=key(1), worker=worker)
    assert wait_for(lambda: "path" in seen and os.path.exists(seen["path"]))
    m2 = J.JobManager(persist=True, data_dir=root, monitor=False)
    try:
        assert os.path.exists(seen["path"])                              # live temp dir untouched
        assert state(m, jid) == J.RUNNING
        with pytest.raises(J.JobRefused):
            m2.status(jid)                                               # not adopted or interrupted by m2
        other = m2.start("other", {}, session_id=SESSION, idempotency_key=key(2), worker=lambda c: 1)
        assert wait_for(lambda: state(m2, other) == J.SUCCEEDED)
        assert wait_for(lambda: {r["job_id"] for r in json.load(open(os.path.join(root, "store", "foundation_jobs.json")))["jobs"]} == {jid, other})
    finally:
        gate.release.set()
        m.close(wait_s=0.5)
        m2.close(wait_s=0.5)


def test_default_manager_is_one_per_process(tmp_path):
    J.reset_default_manager()
    try:
        a = J.default_manager(data_dir=str(tmp_path / "d"))
        assert J.default_manager(data_dir=str(tmp_path / "other")) is a
        J.reset_default_manager()
        assert J.default_manager(data_dir=str(tmp_path / "d")) is not a
    finally:
        J.reset_default_manager()


def test_concurrent_starts_cannot_bypass_the_queue_while_persistence_is_stalled(tmp_path):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, max_workers=1, max_queue=1, monitor=False,
                     temp_root=str(tmp_path / "tmp"))
    entered, proceed = threading.Semaphore(0), threading.Event()
    real_save = m._save

    def stalled():
        entered.release()
        proceed.wait(5)
        real_save()

    m._save = stalled
    results = {}

    def go(i):
        try:
            results[i] = m.start(f"k{i}", {}, session_id=SESSION, idempotency_key=key(i), worker=Blocker())
        except J.JobRefused as exc:
            results[i] = exc.code

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    try:
        assert wait_for(lambda: len(results) >= 4)                     # 6 starts, capacity 2: four refused while stalled
        assert sorted(v for v in results.values() if v == "queue_full") == ["queue_full"] * 4
        accepted = [k for k, v in results.items() if v != "queue_full"]
        assert accepted == [] or len(accepted) <= 2
    finally:
        proceed.set()
        for t in threads:
            t.join(5)
    assert sum(1 for v in results.values() if v != "queue_full") == 2
    assert sum(1 for j in m._jobs.values() if j.state in (J.QUEUED, J.RUNNING)) == 2
    m._save = real_save
    m.close(wait_s=0.5)


def test_a_ready_waiter_cannot_take_the_slot_reserved_by_a_job_still_being_persisted(tmp_path):
    root = str(tmp_path / "data")
    m = J.JobManager(persist=True, data_dir=root, max_workers=1, max_queue=1, monitor=False,
                     temp_root=str(tmp_path / "tmp"))
    entered, proceed = threading.Event(), threading.Event()
    real_save = m._save
    first = []

    def stall_first_only():
        if not first:                                   # only job A's persistence is paused
            first.append(1)
            entered.set()
            proceed.wait(5)
        real_save()

    m._save = stall_first_only
    a_blocker, b_blocker = Blocker(), Blocker()
    out = {}
    ta = threading.Thread(target=lambda: out.setdefault(
        "a", m.start("ka", {}, session_id=SESSION, idempotency_key=key(1), worker=a_blocker)))
    ta.start()
    try:
        assert entered.wait(5)                                       # A holds a reservation, unpersisted
        b = m.start("kb", {}, session_id=SESSION, idempotency_key=key(2), worker=b_blocker)
        assert state(m, b) == J.QUEUED                                # B is ready but may not take A's slot
        assert not b_blocker.started.is_set()
        with pytest.raises(J.JobRefused) as exc:                      # and B counts as the one waiter
            m.start("kc", {}, session_id=SESSION, idempotency_key=key(3), worker=Blocker())
        assert exc.value.code == "queue_full"
    finally:
        proceed.set()
        ta.join(5)
    assert a_blocker.started.wait(5)
    assert state(m, b) == J.QUEUED
    a_blocker.release.set()
    assert b_blocker.started.wait(5)
    b_blocker.release.set()
    m._save = real_save
    m.close(wait_s=0.5)


def test_unreadable_job_records_do_not_stop_the_engine(tmp_path):
    root = str(tmp_path / "data")
    os.makedirs(os.path.join(root, "store"))
    open(os.path.join(root, "store", "foundation_jobs.json"), "wb").write(b'{"schema_version":"foundation_jobs/9","revision":3}')
    m = J.JobManager(persist=True, data_dir=root, monitor=False)
    try:
        assert m.persist_error == "job_records_unreadable"
        jid = m.start("demo", {}, session_id=SESSION, idempotency_key=key(1), worker=lambda c: 1)
        assert wait_for(lambda: state(m, jid) == J.SUCCEEDED)
    finally:
        m.close(wait_s=0.5)
    assert b"foundation_jobs/9" in open(os.path.join(root, "store", "foundation_jobs.json"), "rb").read()


def test_close_cancels_queued_and_asks_running_to_stop(make):
    m = make(max_workers=1)
    gate = Blocker()
    a = m.start("a", {}, session_id=SESSION, idempotency_key=key(1), worker=gate)
    b = m.start("b", {}, session_id=SESSION, idempotency_key=key(2), worker=Blocker())
    assert gate.started.wait(2)
    m.close(wait_s=2)
    assert m._jobs[b].state == J.CANCELLED and m._jobs[a].state == J.CANCELLED


# ------------------------------------------------------------------ guards
def _tree(path):
    return ast.parse(open(path, encoding="utf-8").read())


def test_jobs_module_has_no_subprocess_or_process_calls():
    tree = _tree(os.path.join(FOUNDATION, "jobs.py"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not ({"subprocess", "multiprocessing", "ctypes", "socket", "ssl"} & imported)
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not ({"system", "startfile", "Popen", "popen", "killpg", "terminate"} & attrs)
    assert "Popen" not in names and "os_system" not in names


def test_no_foundation_module_runs_processes():
    for path in glob.glob(os.path.join(FOUNDATION, "*.py")):
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(m.split(".")[0] == "subprocess" for m in mods), os.path.basename(path)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"Popen", "startfile"}, os.path.basename(path)
                if node.attr == "system" and isinstance(node.value, ast.Name) and node.value.id == "os":
                    pytest.fail(f"os.system in {os.path.basename(path)}")
