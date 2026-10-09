"""Scene jobs: state machine, worker model, snapshots, retention, cancellation, wedge backstop, leaks."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import jsonschema
import pytest

from snapstudio_api import scene_jobs as sj
from snapstudio_core import scene, scene_limits as L
from tests import scene_fixtures as fx
from tests.test_scene_contract import assert_valid, sub_validator

RID = iter(range(10**6))


def rid() -> str:
    return f"req-{next(RID):08d}"


def validate(name, obj):
    errors = list(sub_validator(name).iter_errors(obj))
    assert not errors, errors[0].message


def wait_for(fn, timeout=10.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out")


def wait_state(jobs, job_id, *states, timeout=10.0):
    return wait_for(lambda: (lambda s: s if s["state"] in states else None)(jobs.status(job_id)), timeout)


def fake_builder(gate=None, honor_cancel=True, started=None, body=b'{"ok":true}'):
    def builder(path, revision, ctl):
        if started is not None:
            started.set()
        if gate is not None:
            while not gate.wait(0.005):
                if honor_cancel:
                    ctl.check()
        return body
    return builder


@pytest.fixture
def cube(tmp_path):
    return str(fx.bambu_project(tmp_path / "cube.3mf", parts=2, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])]))


@pytest.fixture
def make(tmp_path):
    made = []

    def factory(**kw):
        jobs = sj.SceneJobs(snapshot_root=str(tmp_path / "snap"), **kw)
        made.append(jobs)
        return jobs
    yield factory
    for jobs in made:
        jobs.close()


def snapshot_files(jobs):
    d = jobs.snapshot_dir()
    return [] if d is None or not os.path.isdir(d) else os.listdir(d)


# ------------------------------------------------------------------------------ the happy path

def test_start_status_result_and_snapshot_cleanup(make, cube):
    jobs = make()
    started = jobs.start(cube, rid())
    validate("job_start", started)
    assert started["state"] in ("queued", "running") and started["replaced_job_id"] is None
    status = wait_state(jobs, started["job_id"], "succeeded")
    validate("job_status", status)
    expected = hashlib.sha256(Path(cube).read_bytes()).hexdigest()
    assert status["revision"] == expected and status["stage"] is None
    code, body = jobs.result(started["job_id"])
    assert code == 200 and isinstance(body, bytes)
    sc = json.loads(body)
    assert_valid(sc)
    assert sc["revision"] == expected and sc["counts"]["nodes"] == 3
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []                       # the worker removed its own snapshot
    assert body == scene.serialize(sc)                       # compact bytes, serialized exactly once


def test_original_file_bytes_and_mtime_unchanged_after_a_job(make, cube):
    jobs = make()
    old = os.stat(cube).st_mtime_ns - 5 * 10**9
    os.utime(cube, ns=(old, old))
    before = (Path(cube).read_bytes(), os.stat(cube).st_mtime_ns)
    job = jobs.start(cube, rid())
    wait_state(jobs, job["job_id"], "succeeded")
    jobs.result(job["job_id"])
    assert (Path(cube).read_bytes(), os.stat(cube).st_mtime_ns) == before


def test_result_while_not_ready_and_unknown_job(make, cube):
    gate = threading.Event()
    jobs = make(builder=fake_builder(gate))
    job = jobs.start(cube, rid())
    wait_state(jobs, job["job_id"], "running")
    code, body = jobs.result(job["job_id"])
    assert code == 409 and body["error"] == "NOT_READY" and body["state"] == "running"
    validate("error_response", body)
    gate.set()
    wait_state(jobs, job["job_id"], "succeeded")
    with pytest.raises(sj.JobError) as e:
        jobs.status("0" * 32)
    assert (e.value.http, e.value.code) == (404, "EXPIRED")


def test_failed_job_reports_a_coded_error_with_422(make, tmp_path):
    bad = tmp_path / "bad.3mf"
    bad.write_bytes(b"not a zip" * 20)
    jobs = make()
    job = jobs.start(str(bad), rid())
    status = wait_state(jobs, job["job_id"], "failed")
    assert status["error"]["code"] == "INVALID_ARCHIVE"
    validate("job_status", status)
    code, body = jobs.result(job["job_id"])
    assert code == 422 and body["error"] == "INVALID_ARCHIVE"
    validate("error_response", body)
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []


def test_start_validation(make, tmp_path):
    jobs = make()
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(sj.JobError) as e:
        jobs.start(str(txt), rid())
    assert (e.value.http, e.value.code) == (422, "UNSUPPORTED_FORMAT")
    with pytest.raises(sj.JobError) as e:
        jobs.start(str(tmp_path / "missing.3mf"), rid())
    assert (e.value.http, e.value.code) == (400, "INVALID_REQUEST")


# ------------------------------------------------------------------------------ idempotency and request ids

def test_same_request_id_and_path_returns_the_existing_job(make, cube):
    jobs = make()
    r = rid()
    a = jobs.start(cube, r)
    b = jobs.start(cube, r)
    assert a["job_id"] == b["job_id"] and b["replaced_job_id"] is None
    wait_state(jobs, a["job_id"], "succeeded")
    c = jobs.start(cube, r)                                   # still retained
    assert c["job_id"] == a["job_id"] and c["state"] == "succeeded"
    assert jobs.retained() == 1


def test_request_id_reused_for_another_path_is_a_conflict(make, cube, tmp_path):
    other = fx.plain_cube_3mf(tmp_path / "other.3mf")
    jobs = make()
    r = rid()
    jobs.start(cube, r)
    with pytest.raises(sj.JobError) as e:
        jobs.start(str(other), r)
    assert (e.value.http, e.value.code, e.value.extra["reason"]) == (409, "INVALID_REQUEST", "request_id reused for another path")


def test_reused_request_id_with_changed_file_is_source_changed(make, cube):
    jobs = make()
    r = rid()
    job = jobs.start(cube, r)
    wait_state(jobs, job["job_id"], "succeeded")
    Path(cube).write_bytes(Path(cube).read_bytes() + b"\x00")
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, r)
    assert (e.value.http, e.value.code) == (409, "SOURCE_CHANGED")
    fresh = jobs.start(cube, rid())                           # a fresh request_id starts a new scene
    assert fresh["job_id"] != job["job_id"]


def test_expected_revision_mismatch_is_source_changed(make, cube):
    jobs = make()
    job = jobs.start(cube, rid())
    status = wait_state(jobs, job["job_id"], "succeeded")
    assert jobs.result(job["job_id"], status["revision"])[0] == 200
    with pytest.raises(sj.JobError) as e:
        jobs.result(job["job_id"], "f" * 64)
    assert (e.value.http, e.value.code) == (409, "SOURCE_CHANGED")


def test_source_replaced_mid_job_cannot_tear_the_scene(make, cube):
    """The snapshot is the single source: replacing the original after the copy changes nothing."""
    original = Path(cube).read_bytes()
    seen = {}
    gate = threading.Event()
    started = threading.Event()

    def builder(path, revision, ctl):
        started.set()
        while not gate.wait(0.005):
            ctl.check()
        seen["snapshot"] = Path(path).read_bytes()
        seen["revision"] = revision
        return b"{}"
    jobs = make(builder=builder)
    job = jobs.start(cube, rid())
    started.wait(5)
    Path(cube).write_bytes(b"replaced with something else entirely")
    gate.set()
    status = wait_state(jobs, job["job_id"], "succeeded")
    assert seen["snapshot"] == original
    assert seen["revision"] == status["revision"] == hashlib.sha256(original).hexdigest()


def test_file_changing_during_the_copy_is_source_changed(make, cube, monkeypatch):
    monkeypatch.setattr(L, "SNAPSHOT_CHUNK_BYTES", 256)
    calls = {"n": 0}
    real = sj._Control.progress

    def tamper(self, stage, completed, total):
        calls["n"] += 1
        if calls["n"] == 2 and stage == "reading":
            with open(cube, "ab") as fh:
                fh.write(b"appended while copying")
        real(self, stage, completed, total)
    monkeypatch.setattr(sj._Control, "progress", tamper)
    jobs = make()
    job = jobs.start(cube, rid())
    status = wait_state(jobs, job["job_id"], "failed")
    assert status["error"]["code"] == "SOURCE_CHANGED"
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []


# ------------------------------------------------------------------------------ cancel, replace, races

def test_replace_cancels_the_running_job_and_queues_behind_it(make, cube):
    gate_a = threading.Event()
    started = threading.Event()
    order = []

    def builder(path, revision, ctl):
        order.append(os.path.basename(path))
        started.set()
        if len(order) == 1:
            while not gate_a.wait(0.005):
                ctl.check()
        return b"{}"
    jobs = make(builder=builder)
    a = jobs.start(cube, rid())
    started.wait(5)
    b = jobs.start(cube, rid())
    assert b["replaced_job_id"] == a["job_id"] and b["state"] == "queued"
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    assert jobs.result(a["job_id"])[1]["error"] == "CANCELLED"
    wait_state(jobs, b["job_id"], "succeeded")                # b ran only after a's thread observed the cancel
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    assert len(order) == 2 and not gate_a.is_set()


def test_at_most_one_queued_job_newest_wins(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(builder=fake_builder(gate, honor_cancel=False, started=started))   # holds the worker even when cancelled
    a = jobs.start(cube, rid())
    started.wait(5)
    b = jobs.start(cube, rid())
    c = jobs.start(cube, rid())
    assert c["replaced_job_id"] == b["job_id"]
    assert jobs.status(b["job_id"])["state"] == "cancelled" and jobs.status(c["job_id"])["state"] == "queued"
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    gate.set()
    wait_state(jobs, c["job_id"], "succeeded")


def test_cancel_queued_running_and_terminal_is_idempotent(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    a = jobs.start(cube, rid())
    started.wait(5)
    s = jobs.cancel(a["job_id"])
    assert s["state"] == "cancelled" and s["error"]["code"] == "CANCELLED"
    assert jobs.cancel(a["job_id"])["state"] == "cancelled"
    wait_for(lambda: not jobs.worker_alive())
    b = jobs.start(cube, rid())
    gate.set()
    wait_state(jobs, b["job_id"], "succeeded")
    assert jobs.cancel(b["job_id"])["state"] == "succeeded"   # a late cancel on a terminal job is a no-op
    assert jobs.result(b["job_id"])[0] == 200


def test_cancel_wins_the_race_against_a_worker_that_finishes_anyway(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(builder=fake_builder(gate, honor_cancel=False, started=started, body=b'{"late":true}'))
    a = jobs.start(cube, rid())
    started.wait(5)
    jobs.cancel(a["job_id"])
    gate.set()                                                # the worker now returns a result
    wait_for(lambda: not jobs.worker_alive())
    assert jobs.status(a["job_id"])["state"] == "cancelled"   # first terminal wins; the late result is discarded
    assert jobs.result(a["job_id"]) == (409, {"error": "CANCELLED", "message": "That scene was cancelled."})
    assert jobs._jobs[a["job_id"]].result is None


def test_cancel_after_completion_does_not_change_the_result(make, cube):
    jobs = make(builder=fake_builder())
    a = jobs.start(cube, rid())
    wait_state(jobs, a["job_id"], "succeeded")
    jobs.cancel(a["job_id"])
    assert jobs.result(a["job_id"]) == (200, b'{"ok":true}')


def test_cancel_is_observed_within_two_seconds_on_a_real_scene(make, tmp_path):
    big = fx.big_grid_3mf(tmp_path / "big.3mf", 90_000)
    jobs = make()
    job = jobs.start(str(big), rid())
    wait_for(lambda: jobs.status(job["job_id"])["state"] == "running" and jobs.status(job["job_id"])["stage"] in ("parsing", "encoding"))
    t = time.monotonic()
    jobs.cancel(job["job_id"])
    wait_for(lambda: not jobs.worker_alive(), timeout=5)
    assert time.monotonic() - t <= 2.0
    assert jobs.status(job["job_id"])["state"] == "cancelled"
    assert snapshot_files(jobs) == []


# ------------------------------------------------------------------------------ deadline and wedge

def test_deadline_is_a_timeout_and_the_clock_starts_when_running(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(deadline=0.3, builder=fake_builder(gate, started=started))
    a = jobs.start(cube, rid())
    started.wait(5)
    b = jobs.start(cube, rid())                               # queued: its clock has not started
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    wait_state(jobs, b["job_id"], "running")
    time.sleep(0.05)
    assert jobs.status(b["job_id"])["state"] == "running"
    status = wait_state(jobs, b["job_id"], "failed", timeout=3)
    assert status["error"]["code"] == "TIMEOUT"
    assert jobs.result(b["job_id"])[0] == 422
    wait_for(lambda: not jobs.worker_alive())


def test_worker_that_ignores_cancel_is_wedged_fails_closed_and_recovers(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(wedge_grace=0.25, builder=fake_builder(gate, honor_cancel=False, started=started))
    a = jobs.start(cube, rid())
    started.wait(5)
    jobs.cancel(a["job_id"])
    assert not jobs.wedged()
    b = jobs.start(cube, rid())                               # within the grace period: queued behind the cancelled job
    assert b["state"] == "queued"
    time.sleep(0.4)
    assert jobs.wedged()
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, rid())
    assert (e.value.http, e.value.code) == (503, "WORKER_WEDGED")
    validate("error_response", e.value.body())
    gate.set()                                                # the stuck call finally returns
    wait_state(jobs, b["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    assert not jobs.wedged()
    assert jobs.start(cube, rid())["state"] in ("queued", "running")      # recovered


def test_deadline_wedge_reports_timeout_and_rejects_new_starts(make, cube):
    gate = threading.Event()
    started = threading.Event()
    jobs = make(deadline=0.15, wedge_grace=0.15, builder=fake_builder(gate, honor_cancel=False, started=started))
    a = jobs.start(cube, rid())
    started.wait(5)
    wait_for(lambda: jobs.status(a["job_id"])["state"] == "failed", timeout=3)
    assert jobs.status(a["job_id"])["error"]["code"] == "TIMEOUT"
    assert jobs.wedged()
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, rid())
    assert e.value.code == "WORKER_WEDGED"
    gate.set()
    wait_for(lambda: not jobs.worker_alive())
    assert not jobs.wedged() and jobs.status(a["job_id"])["state"] == "failed"


# ------------------------------------------------------------------------------ retention

def test_ttl_and_terminal_cap_with_an_injected_clock(make, cube):
    now = [1000.0]
    jobs = make(clock=lambda: now[0], builder=fake_builder(), ttl=120.0, max_terminal=8)
    ids = []
    for _ in range(12):
        j = jobs.start(cube, rid())
        wait_state(jobs, j["job_id"], "succeeded")
        wait_for(lambda: not jobs.worker_alive())
        now[0] += 1.0
        ids.append(j["job_id"])
    assert jobs.retained() == 8
    with pytest.raises(sj.JobError) as e:
        jobs.status(ids[0])                                    # oldest evicted
    assert (e.value.http, e.value.code) == (404, "EXPIRED")
    assert jobs.status(ids[-1])["state"] == "succeeded"
    now[0] += 200.0
    with pytest.raises(sj.JobError):
        jobs.status(ids[-1])                                   # TTL: 120 s after it became terminal
    assert jobs.retained() == 0


def test_failed_and_cancelled_jobs_are_retained_like_succeeded_ones(make, cube, tmp_path):
    now = [0.0]
    gate = threading.Event()
    jobs = make(clock=lambda: now[0], builder=fake_builder(gate))
    a = jobs.start(cube, rid())
    wait_state(jobs, a["job_id"], "running")
    jobs.cancel(a["job_id"])
    wait_for(lambda: not jobs.worker_alive())
    now[0] += 119.0
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    now[0] += 2.0
    with pytest.raises(sj.JobError):
        jobs.status(a["job_id"])


def test_eviction_removes_a_snapshot_the_worker_could_not_delete(make, cube, monkeypatch):
    now = [0.0]
    jobs = make(clock=lambda: now[0], builder=fake_builder(), ttl=10.0)
    real_unlink = os.unlink
    state = {"fail": True}

    def flaky(path, *a, **k):
        if state["fail"] and str(path).endswith(".3mf"):
            state["fail"] = False
            raise PermissionError("sharing violation")
        return real_unlink(path, *a, **k)
    monkeypatch.setattr(sj.os, "unlink", flaky)
    j = jobs.start(cube, rid())
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    assert len(snapshot_files(jobs)) == 1                      # the worker's unlink failed
    now[0] += 11.0
    with pytest.raises(sj.JobError):
        jobs.status(j["job_id"])
    assert snapshot_files(jobs) == []                          # eviction retried it (missing-file tolerant)


# ------------------------------------------------------------------------------ snapshot limits

def test_snapshot_ceiling_and_disk_preflight(make, cube, monkeypatch):
    jobs = make()
    monkeypatch.setattr(L, "SNAPSHOT_MAX_BYTES", 1000)
    a = jobs.start(cube, rid())
    assert wait_state(jobs, a["job_id"], "failed")["error"]["code"] == "LIMIT_EXCEEDED"
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []
    monkeypatch.setattr(L, "SNAPSHOT_MAX_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(sj.shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    b = jobs.start(cube, rid())
    status = wait_state(jobs, b["job_id"], "failed")
    assert status["error"]["code"] == "INTERNAL" and "disk" in status["error"]["message"]
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []


def test_response_cap_surfaces_as_limit_exceeded(make, cube, monkeypatch):
    monkeypatch.setattr(L, "MAX_RESPONSE_BYTES", 500)
    jobs = make()
    j = jobs.start(cube, rid())
    assert wait_state(jobs, j["job_id"], "failed")["error"]["code"] == "LIMIT_EXCEEDED"
    assert jobs.result(j["job_id"])[0] == 422


# ------------------------------------------------------------------------------ startup sweep

def test_sweep_removes_only_dead_and_old_directories_and_never_a_live_ones(tmp_path):
    root = tmp_path / "scene-tmp"
    root.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    old = L.SNAPSHOT_DIR_MIN_AGE_SECONDS + 100
    try:
        def mk(name, age_s=0):
            d = root / name
            d.mkdir()
            (d / "x.3mf").write_bytes(b"x")
            if age_s:
                t = time.time() - age_s
                os.utime(d, (t, t))
            return d
        d_dead_old = mk(f"{dead.pid}-aaaa1111", old)
        d_dead_young = mk(f"{dead.pid}-aaaa2222")
        d_live = mk(f"{live.pid}-bbbb2222")
        d_live_ancient = mk(f"{live.pid}-cccc3333", age_s=10 * 24 * 3600)      # a live process's folder, however old
        d_own = mk(f"{os.getpid()}-dddd4444", age_s=10 * 24 * 3600)
        d_junk = mk("not-a-snapshot-dir", old)
        removed = sj.sweep_stale(str(root))
        assert removed == [d_dead_old.name]
        for survivor in (d_dead_young, d_live, d_live_ancient, d_own, d_junk):
            assert survivor.exists(), survivor.name
    finally:
        live.kill()
        live.wait()
    assert sj.sweep_stale(str(tmp_path / "does-not-exist")) == []


def test_sweep_tolerates_a_sharing_violation(tmp_path, monkeypatch):
    root = tmp_path / "scene-tmp"
    root.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    d = root / f"{dead.pid}-aaaa1111"
    d.mkdir()
    t = time.time() - L.SNAPSHOT_DIR_MIN_AGE_SECONDS - 10
    os.utime(d, (t, t))
    real = sj.shutil.rmtree
    monkeypatch.setattr(sj.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(PermissionError("in use")))
    assert sj.sweep_stale(str(root)) == [] and d.exists()          # no crash; left for the next start
    monkeypatch.setattr(sj.shutil, "rmtree", real)
    assert sj.sweep_stale(str(root)) == [d.name]


def test_posix_liveness_branch_by_monkeypatch(monkeypatch):
    monkeypatch.setattr(sj.sys, "platform", "linux")
    calls = []

    def fake_kill(pid, sig):
        calls.append((pid, sig))
        if pid == 111:
            raise ProcessLookupError()
        if pid == 222:
            raise PermissionError()
    monkeypatch.setattr(sj.os, "kill", fake_kill)
    assert sj.pid_alive(111) is False                    # no such process
    assert sj.pid_alive(222) is True                     # exists, not ours: alive
    assert sj.pid_alive(333) is True
    assert sj.pid_alive(os.getpid()) is True and sj.pid_alive(0) is False
    assert (111, 0) in calls


def test_each_registry_uses_its_own_pid_nonce_directory(make, cube):
    a, b = make(builder=fake_builder()), make(builder=fake_builder())
    for jobs in (a, b):
        wait_state(jobs, jobs.start(cube, rid())["job_id"], "succeeded")
    assert a.snapshot_dir() != b.snapshot_dir()
    assert os.path.basename(a.snapshot_dir()).startswith(f"{os.getpid()}-")


# ------------------------------------------------------------------------------ leak gate

def test_fifty_start_cancel_cycles_leave_nothing_behind(make, tmp_path):
    big = str(fx.big_grid_3mf(tmp_path / "g.3mf", 20_000))
    small = str(fx.plain_cube_3mf(tmp_path / "s.3mf"))
    baseline = threading.active_count()
    jobs = make()
    wedged_ever = False
    for i in range(50):
        job = jobs.start(big if i % 2 else small, rid())
        if i % 3 == 0:
            wait_for(lambda: jobs.status(job["job_id"])["state"] != "queued")
        jobs.cancel(job["job_id"])
        wedged_ever = wedged_ever or jobs.wedged()
        assert jobs.retained() <= L.MAX_TERMINAL_JOBS + 2      # + the running/queued pair
    jobs.close()
    wait_for(lambda: not jobs.worker_alive(), timeout=10)
    assert jobs.retained() <= L.MAX_TERMINAL_JOBS               # retained jobs never exceed the cap once idle
    assert all(j.state in sj.TERMINAL for j in jobs._jobs.values())
    assert snapshot_files(jobs) == []                           # temp snapshots = 0
    assert all(j.snapshot is None for j in jobs._jobs.values())
    assert threading.active_count() == baseline                 # thread count back to baseline
    assert not wedged_ever and not jobs.wedged()                # WORKER_WEDGED never occurred


# ------------------------------------------------------------------------------ repair round 1

import contextlib
import errno


def poke(jobs):
    """Any API call runs housekeeping; an unknown id is the cheapest one."""
    with contextlib.suppress(sj.JobError):
        jobs.status("0" * 32)


def test_a10_a_retained_job_evicted_while_hashing_is_never_handed_back(make, cube, monkeypatch):
    now = [0.0]
    jobs = make(clock=lambda: now[0], builder=fake_builder(), ttl=120.0)
    r = rid()
    a = jobs.start(cube, r)
    status = wait_state(jobs, a["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())

    def hash_while_time_passes(path):
        now[0] += 500.0                                       # the TTL expires during the hash
        return status["revision"]
    monkeypatch.setattr(jobs, "_current_hash", hash_while_time_passes)
    b = jobs.start(cube, r)
    assert b["job_id"] != a["job_id"]
    assert jobs.status(b["job_id"])["request_id"] == r        # the returned job is registered
    with pytest.raises(sj.JobError):
        jobs.status(a["job_id"])


def test_a11_a_snapshot_that_resists_deletion_is_retried_with_backoff(make, cube, monkeypatch):
    now = [0.0]
    jobs = make(clock=lambda: now[0], builder=fake_builder(), ttl=10.0)
    real = os.unlink
    fails = {"n": 0}

    def flaky(path, *a, **k):
        if str(path).endswith(".3mf") and fails["n"] < 3:
            fails["n"] += 1
            raise PermissionError("sharing violation")
        return real(path, *a, **k)
    monkeypatch.setattr(sj.os, "unlink", flaky)
    j = jobs.start(cube, rid())
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    assert len(snapshot_files(jobs)) == 1                      # failure 1: the worker's own unlink
    now[0] += 11.0
    poke(jobs)                                                  # TTL eviction: failure 2, path goes on the retry list
    with pytest.raises(sj.JobError):
        jobs.status(j["job_id"])
    assert len(snapshot_files(jobs)) == 1 and len(jobs._pending) == 1
    now[0] += 2.5
    poke(jobs)                                                  # first retry: failure 3, longer back-off
    assert len(snapshot_files(jobs)) == 1 and jobs._pending[0][1] >= 2
    now[0] += 1.0
    poke(jobs)                                                  # not due yet: no attempt
    assert fails["n"] == 3
    now[0] += 10.0
    poke(jobs)                                                  # now it succeeds and the path is forgotten
    assert snapshot_files(jobs) == [] and jobs._pending == []


def test_d2_the_snapshot_directory_is_recreated_for_every_job(make, cube):
    jobs = make(builder=fake_builder())
    first = jobs.start(cube, rid())
    wait_state(jobs, first["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    import shutil
    shutil.rmtree(jobs.snapshot_dir())                          # something removed the per-process folder
    second = jobs.start(cube, rid())
    assert wait_state(jobs, second["job_id"], "succeeded")["error"] is None


def test_d2_only_a_real_enospc_is_reported_as_a_disk_space_problem(make, cube, monkeypatch):
    jobs = make(builder=fake_builder())
    real_open = open

    def failing(code):
        def fake(path, mode="r", *a, **k):
            if "w" in mode and str(path).endswith(".3mf"):
                raise OSError(code, "boom")
            return real_open(path, mode, *a, **k)
        return fake
    monkeypatch.setattr(sj, "open", failing(errno.EACCES), raising=False)
    a = jobs.start(cube, rid())
    msg = wait_state(jobs, a["job_id"], "failed")["error"]["message"]
    assert "disk space" not in msg and "temporary copy" in msg
    wait_for(lambda: not jobs.worker_alive())
    monkeypatch.setattr(sj, "open", failing(errno.ENOSPC), raising=False)
    b = jobs.start(cube, rid())
    assert "disk space" in wait_state(jobs, b["job_id"], "failed")["error"]["message"]


def test_d6a_a_cancelled_job_whose_worker_is_still_running_is_not_evicted(make, cube):
    now = [0.0]
    gate, started = threading.Event(), threading.Event()
    jobs = make(clock=lambda: now[0], ttl=10.0, max_terminal=0, builder=fake_builder(gate, honor_cancel=False, started=started))
    a = jobs.start(cube, rid())
    started.wait(5)
    jobs.cancel(a["job_id"])
    now[0] += 1000.0
    poke(jobs)
    assert jobs.status(a["job_id"])["state"] == "cancelled"     # worker not done: not evictable, whatever the TTL and cap
    gate.set()
    wait_for(lambda: not jobs.worker_alive())
    with pytest.raises(sj.JobError) as e:
        jobs.status(a["job_id"])
    assert e.value.code == "EXPIRED"


def test_d6b_the_deadline_starts_when_the_job_runs_not_when_it_was_created(make, cube):
    gate, started = threading.Event(), threading.Event()
    calls = []

    def builder(path, revision, ctl):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            gate.wait(5)                                         # the first job holds the worker, ignoring cancel
            return b"{}"
        ctl.check()
        return b'{"second":true}'
    jobs = make(deadline=0.4, wedge_grace=30.0, builder=builder)
    a = jobs.start(cube, rid())
    started.wait(5)
    b = jobs.start(cube, rid())                                  # queued behind a
    time.sleep(0.7)                                              # longer than the deadline, all of it spent queued
    gate.set()
    assert wait_state(jobs, b["job_id"], "succeeded", "failed")["state"] == "succeeded"
    assert jobs.status(a["job_id"])["state"] == "cancelled"


def test_d6e_a_size_change_without_an_mtime_change_is_source_changed(make, cube, monkeypatch):
    monkeypatch.setattr(L, "SNAPSHOT_CHUNK_BYTES", 256)
    st = os.stat(cube)
    calls = {"n": 0}
    real = sj._Control.progress

    def tamper(self, stage, completed, total):
        calls["n"] += 1
        if calls["n"] == 2 and stage == "reading":
            with open(cube, "ab") as fh:
                fh.write(b"grown")
            os.utime(cube, ns=(st.st_atime_ns, st.st_mtime_ns))  # put the mtime back: only the size betrays it
        real(self, stage, completed, total)
    monkeypatch.setattr(sj._Control, "progress", tamper)
    jobs = make()
    job = jobs.start(cube, rid())
    assert wait_state(jobs, job["job_id"], "failed")["error"]["code"] == "SOURCE_CHANGED"
    wait_for(lambda: not jobs.worker_alive())
    assert snapshot_files(jobs) == []


def test_close_removes_the_per_process_directory_best_effort(make, cube):
    jobs = make(builder=fake_builder())
    j = jobs.start(cube, rid())
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    d = jobs.snapshot_dir()
    assert os.path.isdir(d)
    jobs.close()
    assert not os.path.exists(d)
