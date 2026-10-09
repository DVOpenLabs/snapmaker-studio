"""Session-based start ordering at the engine boundary.

Invariants (each test name carries its tag):
  I1  Delayed starts cannot become valid through bookkeeping eviction.
  I2  Cancellation cannot be forgotten while the corresponding start remains admissible.
  I3  Idempotency is scoped to (session, request) and ownership is checked consistently on every path.
  I4  Capacity exhaustion or session expiry fails EXPLICITLY; nothing old is ever silently revived.

No sleep decides any outcome: the abandoned start A is held at the pre-registration seam
(`SceneJobs._check_source`, which runs before the registry lock) with a threading.Event, and time is a fake clock.
"""
import os
import threading

import pytest

from snapstudio_api import scene_jobs as sj
from snapstudio_core import scene_limits as L
from tests import scene_fixtures as fx
from tests.test_scene_api import call, server  # noqa: F401  (the loopback server fixture)
from tests.test_scene_contract import sub_validator
from tests.test_scene_jobs import fake_builder, wait_for


def _owner(jobs, job_id):
    job = jobs._jobs.get(job_id)
    return job.client_id if job is not None else None


def st(jobs, job_id):
    """status() presenting the job's own session credential (looked up here, in the TEST, not by the engine)."""
    return jobs.status(job_id, _owner(jobs, job_id))


def cn(jobs, job_id):
    return jobs.cancel(job_id, _owner(jobs, job_id))


def wait_state(jobs, job_id, *states, timeout=10.0):
    return wait_for(lambda: (lambda r: r if r["state"] in states else None)(st(jobs, job_id)), timeout)


@pytest.fixture
def cube(tmp_path):
    return str(fx.plain_cube_3mf(tmp_path / "cube.3mf"))


@pytest.fixture
def make(tmp_path):
    made = []

    def factory(**kw):
        jobs = sj.SceneJobs(snapshot_root=str(tmp_path / "snap"), builder=kw.pop("builder", fake_builder()), **kw)
        made.append(jobs)
        return jobs
    yield factory
    for jobs in made:
        jobs.close()


def sess(jobs) -> str:
    return jobs.open_session()["client_id"]


class HeldStart:
    """Run jobs.start(...) on a thread that blocks at the pre-registration seam until released."""

    def __init__(self, jobs, *args, **kwargs):
        self.entered, self.release = threading.Event(), threading.Event()
        self.result = self.error = None
        real = jobs._check_source

        def seam(path):
            real(path)
            self.entered.set()
            assert self.release.wait(10)
        jobs._check_source = seam
        self.thread = threading.Thread(target=self._run, args=(jobs, args, kwargs), daemon=True)
        self.thread.start()
        assert self.entered.wait(10)
        jobs._check_source = real                 # later starts are not held

    def _run(self, jobs, args, kwargs):
        try:
            self.result = jobs.start(*args, **kwargs)
        except sj.JobError as exc:
            self.error = exc

    def finish(self):
        self.release.set()
        self.thread.join(10)
        assert not self.thread.is_alive()
        return self


def refused(jobs, code, *args, http=None):
    with pytest.raises(sj.JobError) as e:
        jobs.start(*args)
    assert e.value.code == code, (e.value.code, e.value.message)
    if http:
        assert e.value.http == http
    assert not list(sub_validator("error_response").iter_errors(e.value.body()))
    return e.value


# ------------------------------------------------------------------ the session

def test_i4_open_session_shape_and_expiry_ttl(make):
    jobs = make()
    out = jobs.open_session()
    assert set(out) == {"client_id", "ttl_s"} and len(out["client_id"]) == 24 and out["ttl_s"] == L.SESSION_TTL_SECONDS
    assert not list(sub_validator("session").iter_errors(out))
    assert sess(jobs) != out["client_id"]


def test_the_per_session_state_is_constant_size(make, cube):
    jobs = make()
    s = sess(jobs)
    for seq in range(1, 6):
        jobs.start(cube, f"req-{seq:08d}", s, seq)
        jobs.cancel_request(s, f"req-x-{seq:06d}", seq)
    assert set(vars(jobs._sessions[s])) == {"client_id", "last_touch", "watermark", "dead_through", "current"}
    assert not hasattr(jobs, "_tombstones") and not hasattr(jobs, "_clients")


# ------------------------------------------------------------------ I1: a delayed start never becomes valid

@pytest.mark.parametrize("wanted", ["running", "completed", "cancelled", "evicted"])
def test_i1_a_delayed_abandoned_start_is_refused_whatever_became_of_the_wanted_one(make, cube, wanted):
    now = [0.0]
    gate, started = threading.Event(), threading.Event()
    builder = fake_builder(gate, started=started) if wanted == "running" else fake_builder()
    jobs = make(clock=lambda: now[0], builder=builder, ttl=10.0)
    s = sess(jobs)
    a = HeldStart(jobs, cube, "req-A-000001", s, 1)                 # abandoned, delayed in flight
    b = jobs.start(cube, "req-B-000002", s, 2)                      # the wanted start gets in first
    if wanted == "running":
        assert started.wait(10) and st(jobs, b["job_id"])["state"] == "running"
    else:
        wait_state(jobs, b["job_id"], "succeeded")
        wait_for(lambda: not jobs.worker_alive())
    if wanted == "cancelled":
        jobs.cancel_request(s, "req-B-000002", 2)
    if wanted == "evicted":
        now[0] += 60.0
        with pytest.raises(sj.JobError):
            st(jobs, b["job_id"])                                 # B's job is gone from the registry
    a.finish()
    assert a.error is not None and a.error.code in ("STALE_START", "CANCELLED_BEFORE_START")
    if wanted == "cancelled":
        assert a.error.code == "CANCELLED_BEFORE_START"
    elif wanted == "evicted":
        assert a.error.code == "STALE_START"                         # eviction did not make the late start valid
    if wanted == "running":
        assert st(jobs, b["job_id"])["state"] == "running"        # B was neither cancelled nor replaced
        gate.set()
        wait_state(jobs, b["job_id"], "succeeded")
    elif wanted == "completed":
        assert st(jobs, b["job_id"])["state"] == "succeeded"


def test_i1_astra_repro_a_repeat_of_b_at_a_higher_seq_then_the_delayed_a(make, cube):
    jobs = make()
    s = sess(jobs)
    b = jobs.start(cube, "req-B-000001", s, 1)
    wait_state(jobs, b["job_id"], "succeeded")
    a = HeldStart(jobs, cube, "req-A-000002", s, 2)
    err = refused(jobs, "INVALID_REQUEST", cube, "req-B-000001", s, 3, http=400)    # B repeated as seq 3
    assert err.extra["reason"] == "request id reused"
    a.finish()
    assert a.error.code == "STALE_START"                             # the watermark had already moved to 3
    assert st(jobs, b["job_id"])["state"] == "succeeded"
    refused(jobs, "STALE_START", cube, "req-B-000001", s, 3)         # the refused attempt is not an idempotent repeat
    ok = jobs.start(cube, "req-B-000004", s, 4)                      # recovery: fresh request_id, higher seq
    assert wait_state(jobs, ok["job_id"], "succeeded")["state"] == "succeeded"


def test_i1_a_stale_start_cannot_replace_a_running_wanted_start(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    s = sess(jobs)
    a = HeldStart(jobs, cube, "req-A-000001", s, 1)
    b = jobs.start(cube, "req-B-000002", s, 2)
    started.wait(10)
    a.finish()
    assert a.error.code == "STALE_START" and st(jobs, b["job_id"])["state"] == "running"
    gate.set()


def test_i1_an_exact_retry_of_an_evicted_start_is_stale_and_replaces_nothing(make, cube):
    now = [0.0]
    gate, started = threading.Event(), threading.Event()
    calls = []

    def builder(path, revision, ctl):
        calls.append(1)
        if len(calls) == 1:
            return b"{}"
        started.set()
        while not gate.wait(0.005):
            ctl.check()
        return b"{}"
    jobs = make(clock=lambda: now[0], ttl=10.0, builder=builder)
    s, t = sess(jobs), sess(jobs)
    first = jobs.start(cube, "req-E-000001", s, 1)
    wait_state(jobs, first["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    other = jobs.start(cube, "req-O-000001", t, 1)                   # someone else's job is running
    assert started.wait(10)
    now[0] += 60.0
    with pytest.raises(sj.JobError):
        st(jobs, first["job_id"])
    err = refused(jobs, "STALE_START", cube, "req-E-000001", s, 1, http=409)
    assert st(jobs, other["job_id"])["state"] == "running"        # and it did not replace the running job
    gate.set()
    wait_state(jobs, other["job_id"], "succeeded")
    assert err


def test_i1_idempotent_repeat_while_registered_returns_the_same_job(make, cube):
    jobs = make()
    s = sess(jobs)
    b = jobs.start(cube, "req-B-000002", s, 2)
    again = jobs.start(cube, "req-B-000002", s, 2)
    assert again["job_id"] == b["job_id"] and again["replaced_job_id"] is None


def test_i1_equal_seq_with_another_request_or_another_path_is_invalid(make, cube, tmp_path):
    jobs = make()
    s = sess(jobs)
    jobs.start(cube, "req-B-000002", s, 2)
    assert refused(jobs, "INVALID_REQUEST", cube, "req-X-000003", s, 2, http=400).extra["reason"] == "seq reused for another request"
    other = str(fx.plain_cube_3mf(tmp_path / "other.3mf", size=11))
    refused(jobs, "INVALID_REQUEST", other, "req-B-000002", s, 2, http=400)


def test_i1_a_higher_seq_never_silently_returns_an_old_job(make, cube):
    jobs = make()
    s = sess(jobs)
    j = jobs.start(cube, "req-R-000001", s, 1)
    refused(jobs, "INVALID_REQUEST", cube, "req-R-000001", s, 2, http=400)
    assert st(jobs, j["job_id"])["request_id"] == "req-R-000001"


def test_i1_stale_and_cancel_are_decided_before_source_changed(make, cube, monkeypatch):
    for during, expected in (("newer", "STALE_START"), ("cancel", "CANCELLED_BEFORE_START"), ("expiry", "SESSION_EXPIRED")):
        now = [0.0]
        jobs = make(clock=lambda: now[0], session_ttl=100.0, ttl=10**9, max_terminal=100)
        s = sess(jobs)
        a = jobs.start(cube, "req-A-000001", s, 1)
        wait_state(jobs, a["job_id"], "succeeded")
        wait_for(lambda: not jobs.worker_alive())
        inside, release = threading.Event(), threading.Event()

        def hashing(path):                                              # the file HAS changed, yet the answer is decided first
            inside.set()
            assert release.wait(10)
            return "f" * 64
        monkeypatch.setattr(jobs, "_current_hash", hashing)
        out = {}

        def repeat():
            try:
                out["r"] = jobs.start(cube, "req-A-000001", s, 1)
            except sj.JobError as exc:
                out["e"] = exc
        t = threading.Thread(target=repeat, daemon=True)
        t.start()
        assert inside.wait(10)
        if during == "newer":
            jobs.start(cube, "req-N-000002", s, 2)
        elif during == "cancel":
            jobs.cancel_request(s, "req-A-000001", 1)
        else:
            now[0] += 500.0
            jobs._jobs.pop(a["job_id"])
            jobs._by_request.pop((s, "req-A-000001"))                  # nothing registered: the session may now expire
            jobs._housekeeping()
        release.set()
        t.join(10)
        assert out["e"].code == expected, (during, out)


def test_without_any_newer_start_a_changed_file_is_still_source_changed(make, cube):
    jobs = make()
    s = sess(jobs)
    a = jobs.start(cube, "req-A-000001", s, 1)
    wait_state(jobs, a["job_id"], "succeeded")
    with open(cube, "ab") as fh:
        fh.write(b"\0")
    refused(jobs, "SOURCE_CHANGED", cube, "req-A-000001", s, 1)


# ------------------------------------------------------------------ I2: cancellation is not forgotten

def test_i2_a_cancel_that_arrives_before_the_start_refuses_it_and_every_lower_seq(make, cube):
    jobs = make()
    s = sess(jobs)
    out = jobs.cancel_request(s, "req-A-000001", 3)                    # the client moved on from attempts 1..3
    assert out["job_id"] is None and out["state"] == "cancelled" and out["error"]["code"] == "CANCELLED"
    assert not list(sub_validator("job_status").iter_errors(out))
    for seq, rid_ in ((3, "req-A-000001"), (2, "req-late-0002"), (1, "req-late-0001")):
        refused(jobs, "CANCELLED_BEFORE_START", cube, rid_, s, seq, http=409)
    assert jobs.retained() == 0                                        # nothing was registered
    fresh = jobs.start(cube, "req-A-000004", s, 4)                     # a fresh request_id with a higher seq works
    assert wait_state(jobs, fresh["job_id"], "succeeded")["state"] == "succeeded"


def test_i2_a_cancelled_start_stays_refused_after_its_job_is_evicted_and_after_unrelated_activity(make, cube):
    now = [0.0]
    jobs = make(clock=lambda: now[0], ttl=1.0)
    s = sess(jobs)
    a = jobs.start(cube, "req-A-000001", s, 1)
    jobs.cancel_request(s, "req-A-000001", 1)
    wait_for(lambda: not jobs.worker_alive())
    now[0] += 100.0
    with pytest.raises(sj.JobError):
        st(jobs, a["job_id"])                                       # the cancelled job is long gone
    for i in range(200):                                               # a great deal of unrelated cancel traffic
        jobs.cancel_request(s, f"req-noise-{i:05d}", 1)
    refused(jobs, "CANCELLED_BEFORE_START", cube, "req-A-000001", s, 1)
    assert len(vars(jobs._sessions[s])) == 5                           # and the memory is still O(1)


def test_i2_cancelling_a_never_touches_b(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    s = sess(jobs)
    a = jobs.start(cube, "req-A-000001", s, 1)
    started.wait(10)
    b = jobs.start(cube, "req-B-000002", s, 2)                         # replaces A as today
    assert st(jobs, a["job_id"])["state"] == "cancelled"
    jobs.cancel_request(s, "req-A-000001", 1)                           # cancelling A...
    assert st(jobs, b["job_id"])["state"] in ("queued", "running")  # ...never touches B (exact request match)
    jobs.cancel_request(s, "req-C-nonexistent", 1)
    assert st(jobs, b["job_id"])["state"] in ("queued", "running")
    out = jobs.cancel_request(s, "req-B-000002", 2)
    assert out["job_id"] == b["job_id"] and out["state"] == "cancelled"
    gate.set()


def test_i2_cancel_by_job_id_is_unchanged(make, cube):
    jobs = make()
    s = sess(jobs)
    j = jobs.start(cube, "req-J-000001", s, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    assert cn(jobs, j["job_id"])["state"] == "succeeded"
    with pytest.raises(sj.JobError) as e:
        cn(jobs, "0" * 32)
    assert e.value.code == "EXPIRED"


# ------------------------------------------------------------------ I3: (session, request) scoping and ownership

def test_i3_the_same_request_id_in_two_sessions_gives_each_its_own_job_and_cancel(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    s, t = sess(jobs), sess(jobs)
    a = jobs.start(cube, "req-same-0001", s, 1)
    started.wait(10)
    b = jobs.start(cube, "req-same-0001", t, 1)                        # same request_id and path, another session
    assert a["job_id"] != b["job_id"] and b["replaced_job_id"] is None      # H1: s's job id is not revealed to t
    assert st(jobs, a["job_id"])["state"] == "cancelled"                     # (the newest start still replaces it, as before)
    assert jobs.start(cube, "req-same-0001", t, 1)["job_id"] == b["job_id"]      # idempotent inside its own scope
    out = jobs.cancel_request(s, "req-same-0001", 1)
    assert out["job_id"] == a["job_id"]
    assert st(jobs, b["job_id"])["state"] in ("queued", "running")  # t's job untouched: no leak across sessions
    assert jobs.cancel_request(t, "req-same-0001", 1)["job_id"] == b["job_id"]
    gate.set()


def test_i3_a_session_cannot_cancel_or_see_another_sessions_job_by_request(make, cube):
    jobs = make()
    s, t = sess(jobs), sess(jobs)
    j = jobs.start(cube, "req-own-00001", s, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    out = jobs.cancel_request(t, "req-own-00001", 1)
    assert out["job_id"] is None
    assert st(jobs, j["job_id"])["state"] == "succeeded"
    assert jobs.start(cube, "req-own-00001", s, 1)["job_id"] == j["job_id"]


def test_i3_the_legacy_namespace_is_separate_and_unchanged(make, cube):
    jobs = make()
    s = sess(jobs)
    legacy = jobs.start(cube, "req-ns-000001")
    ordered = jobs.start(cube, "req-ns-000001", s, 1)
    assert legacy["job_id"] != ordered["job_id"]
    assert jobs.start(cube, "req-ns-000001")["job_id"] == legacy["job_id"]


def test_i3_many_sessions_start_concurrently_and_independently(make, cube):
    jobs = make()
    ids = [sess(jobs) for _ in range(8)]
    barrier = threading.Barrier(len(ids))
    results, errors = {}, []

    def go(i, cid):
        barrier.wait(10)
        try:
            results[i] = jobs.start(cube, "req-same-0001", cid, 1)    # every session reuses seq 1 AND the request_id
        except sj.JobError as exc:
            errors.append(exc)
    threads = [threading.Thread(target=go, args=(i, c), daemon=True) for i, c in enumerate(ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors and len(results) == len(ids)
    assert len({r["job_id"] for r in results.values()}) == len(ids)


# ------------------------------------------------------------------ I4: expiry and capacity fail explicitly

def test_i4_an_expired_session_refuses_start_and_cancel_and_a_late_delayed_start(make, cube):
    now = [0.0]
    jobs = make(clock=lambda: now[0], session_ttl=100.0)
    s = sess(jobs)
    late = HeldStart(jobs, cube, "req-A-000001", s, 1)               # in flight when the session ends
    now[0] += 500.0
    jobs.open_session()                                                # any call prunes the idle-expired session
    assert s not in jobs._sessions
    late.finish()
    assert late.error is not None and (late.error.http, late.error.code) == (409, "SESSION_EXPIRED")
    assert s not in jobs._sessions and jobs.retained() == 0           # refused, never re-created, nothing registered
    refused(jobs, "SESSION_EXPIRED", cube, "req-B-000002", s, 2)
    with pytest.raises(sj.JobError) as e:
        jobs.cancel_request(s, "req-B-000002", 2)
    assert e.value.code == "SESSION_EXPIRED"
    assert s not in jobs._sessions


@pytest.mark.parametrize("how", ["refused_start", "cancel", "status"])
def test_i4_every_start_cancel_and_status_touches_the_session(make, cube, how):
    """Each call keeps alive a session that would otherwise be idle-expired (the job it owned is already gone)."""
    now = [0.0]
    jobs = make(clock=lambda: now[0], session_ttl=100.0, ttl=100.0)
    s = sess(jobs)
    j = jobs.start(cube, "req-A-000002", s, 2)
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    now[0] += 90.0
    if how == "status":
        st(jobs, j["job_id"])
    elif how == "cancel":
        jobs.cancel_request(s, "req-zzz-000001", 1)
    else:
        refused(jobs, "STALE_START", cube, "req-old-000001", s, 1)     # a refused start still touches the session
    now[0] += 90.0                                                       # 180 s since creation, 90 s since the touch
    jobs.open_session()                                                  # evicts the expired job (the session owned it until now)
    jobs.open_session()                                                  # now the session is judged on its idle time alone
    assert s in jobs._sessions


def test_i4_session_limit_is_explicit_when_nothing_is_prunable(make, cube):
    jobs = make(max_sessions=3)
    ids = [sess(jobs) for _ in range(3)]
    with pytest.raises(sj.JobError) as e:
        jobs.open_session()
    assert (e.value.http, e.value.code) == (503, "SESSION_LIMIT")
    assert not list(sub_validator("error_response").iter_errors(e.value.body()))
    assert set(jobs._sessions) == set(ids)                             # a live session is never evicted to make room


def test_i4_an_idle_expired_session_without_a_job_is_pruned_to_make_room(make):
    now = [0.0]
    jobs = make(clock=lambda: now[0], max_sessions=2, session_ttl=100.0)
    first, second = sess(jobs), sess(jobs)
    now[0] += 50.0
    jobs._sessions[second].last_touch = now[0]                          # the second one stays active
    now[0] += 60.0                                                      # the first is idle 110 s (> ttl), the second 60 s
    third = sess(jobs)
    assert first not in jobs._sessions and second in jobs._sessions and third in jobs._sessions


def test_i4_a_session_that_owns_a_registered_job_is_never_pruned(make, cube):
    now = [0.0]
    jobs = make(clock=lambda: now[0], max_sessions=2, session_ttl=100.0, ttl=10**9, max_terminal=100)
    s = sess(jobs)
    j = jobs.start(cube, "req-A-000001", s, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    other = sess(jobs)
    now[0] += 10**6                                                     # idle far beyond the ttl
    with pytest.raises(sj.JobError) as e:
        jobs.open_session()                                             # `other` is prunable, `s` is not -> room for one
        jobs.open_session()
    assert e.value.code == "SESSION_LIMIT"
    assert s in jobs._sessions and other not in jobs._sessions


def test_i4_an_engine_restart_drops_every_session_explicitly(make, cube):
    old = make()
    s = sess(old)
    restarted = make()                                                  # a new SceneJobs is a new engine process
    refused(restarted, "SESSION_EXPIRED", cube, "req-A-000001", s, 1, http=409)
    with pytest.raises(sj.JobError) as e:
        restarted.cancel_request(s, "req-A-000001", 1)
    assert e.value.code == "SESSION_EXPIRED"
    assert restarted.retained() == 0 and not restarted._sessions


def test_i4_an_unknown_session_id_is_not_created_by_a_start(make, cube):
    jobs = make()
    refused(jobs, "SESSION_EXPIRED", cube, "req-A-000001", "never-issued-session-id", 1)
    assert not jobs._sessions


# ------------------------------------------------------------------ the legacy path

def test_legacy_starts_without_the_fields_still_work(make, cube):
    jobs = make()
    a = jobs.start(cube, "req-L-000001")
    wait_state(jobs, a["job_id"], "succeeded")
    b = jobs.start(cube, "req-L-000002")
    wait_state(jobs, b["job_id"], "succeeded")
    s = sess(jobs)
    c = jobs.start(cube, "req-O-000003", s, 7)
    wait_state(jobs, c["job_id"], "succeeded")
    d = jobs.start(cube, "req-L-000004")
    assert wait_state(jobs, d["job_id"], "succeeded")["state"] == "succeeded"


# ------------------------------------------------------------------ validation

@pytest.mark.parametrize("extra", [
    {"client_id": None, "seq": None}, {"client_id": "x" * 24, "seq": None}, {"client_id": None, "seq": 1},
    {"client_id": "x" * 24 + "\n", "seq": 1}, {"seq": None}, {"client_id": None}, {"seq": 1}, {"client_id": "x" * 24},
    {"client_id": "x" * 24, "seq": 0}, {"client_id": "x" * 24, "seq": -1}, {"client_id": "x" * 24, "seq": True},
    {"client_id": "x" * 24, "seq": 1.0}, {"client_id": "x" * 24, "seq": "1"}, {"client_id": "x" * 24, "seq": 2 ** 53},
    {"client_id": "short", "seq": 1}, {"client_id": 12345678, "seq": 1},
])
def test_validation_holes_are_closed_on_start(make, cube, extra):
    jobs = make()
    status, body = sj.handle("/scene/start", dict({"path": cube, "request_id": "req-V-000001"}, **extra), jobs)
    assert (status, body["error"]) == (400, "INVALID_REQUEST"), (extra, status, body)
    assert jobs.retained() == 0 and not jobs._sessions


def test_validation_holes_are_closed_on_cancel_and_ids(make, cube):
    jobs = make()
    s = sess(jobs)
    bad = [
        {"client_id": s, "request_id": "req-V-000001"},                                   # seq missing
        {"client_id": s, "request_id": "req-V-000001\n", "seq": 1}, {"client_id": s + "\n", "request_id": "req-V-000001", "seq": 1},
        {"client_id": s, "request_id": "req-V-000001", "seq": None}, {"client_id": None, "request_id": "req-V-000001", "seq": 1},
        {"client_id": s, "request_id": "req-V-000001", "seq": True}, {"client_id": s, "request_id": "req-V-000001", "seq": 1.5},
        {"job_id": "0" * 32, "client_id": s, "request_id": "req-V-000001", "seq": 1},
        {"request_id": "req-V-000001", "seq": 1},
    ]
    for body in bad:
        status, resp = sj.handle("/scene/cancel", body, jobs)
        assert (status, resp["error"]) == (400, "INVALID_REQUEST"), (body, status, resp)
    status, resp = sj.handle("/scene/result", {"job_id": "0" * 32, "expected_revision": "a" * 64 + "\n"}, jobs)
    assert status == 400
    assert jobs._sessions[s].dead_through == 0                          # no malformed cancel changed any state


def test_seq_upper_bound_is_two_to_the_53_minus_1(make, cube):
    jobs = make()
    s = sess(jobs)
    status, _ = sj.handle("/scene/start", {"path": cube, "request_id": "req-S-000001", "client_id": s, "seq": 2 ** 53 - 1}, jobs)
    assert status == 200


# ------------------------------------------------------------------ the real HTTP route

def test_http_session_start_stale_cancel_and_expiry_shapes(server, tmp_path):  # noqa: F811
    port, token = server
    path = str(fx.plain_cube_3mf(tmp_path / "h.3mf"))
    code, opened = call(port, "/scene/session", {}, token)
    assert code == 200 and set(opened) == {"client_id", "ttl_s"} and not list(sub_validator("session").iter_errors(opened))
    cid = opened["client_id"]
    code, b = call(port, "/scene/start", {"path": path, "request_id": "req-B-http0002", "client_id": cid, "seq": 2}, token)
    assert code == 200 and not list(sub_validator("job_start").iter_errors(b))
    code, body = call(port, "/scene/start", {"path": path, "request_id": "req-A-http0001", "client_id": cid, "seq": 1}, token)
    assert (code, body["error"]) == (409, "STALE_START") and not list(sub_validator("error_response").iter_errors(body))
    code, status = call(port, "/scene/status", {"job_id": b["job_id"], "client_id": cid}, token)
    assert code == 200 and status["state"] != "cancelled"
    code, c = call(port, "/scene/cancel", {"client_id": cid, "request_id": "req-C-http0003", "seq": 3}, token)
    assert code == 200 and c["job_id"] is None and c["state"] == "cancelled" and not list(sub_validator("job_status").iter_errors(c))
    code, body = call(port, "/scene/start", {"path": path, "request_id": "req-C-http0003", "client_id": cid, "seq": 3}, token)
    assert (code, body["error"]) == (409, "CANCELLED_BEFORE_START")
    code, body = call(port, "/scene/start", {"path": path, "request_id": "req-D-http0004", "client_id": "never-issued-session-id", "seq": 1}, token)
    assert (code, body["error"]) == (409, "SESSION_EXPIRED")
    code, body = call(port, "/scene/cancel", {"client_id": "never-issued-session-id", "request_id": "req-D-http0004", "seq": 1}, token)
    assert (code, body["error"]) == (409, "SESSION_EXPIRED")
    code, legacy = call(port, "/scene/start", {"path": path, "request_id": "req-L-http0005"}, token)
    assert code == 200


def test_http_session_limit_is_503(server):  # noqa: F811
    port, token = server
    codes = [call(port, "/scene/session", {}, token)[0] for _ in range(L.MAX_SESSIONS + 1)]
    assert codes[:L.MAX_SESSIONS] == [200] * L.MAX_SESSIONS and codes[-1] == 503
    code, body = call(port, "/scene/session", {}, token)
    assert (code, body["error"]) == (503, "SESSION_LIMIT")


def test_http_routes_reject_non_object_bodies_and_need_the_token(server):  # noqa: F811
    port, token = server
    for route in sj.ROUTES:
        assert call(port, route, None, token)[0] == 400
        assert call(port, route, {}, None)[0] == 401


# ================================================================== round: job-id ownership, post-admission failures

def _unknown_body(jobs, call):
    with pytest.raises(sj.JobError) as e:
        call()
    return (e.value.http, e.value.body())


def test_h1_job_id_operations_are_session_owned_and_refused_exactly_like_unknown_ids(make, cube):
    jobs = make()
    a, b = sess(jobs), sess(jobs)
    j = jobs.start(cube, "req-own-00001", a, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    unknown = "0" * 32
    for call_for in (lambda jid, cid: jobs.status(jid, cid), lambda jid, cid: jobs.result(jid, None, cid),
                     lambda jid, cid: jobs.cancel(jid, cid)):
        baseline = _unknown_body(jobs, lambda: call_for(unknown, b))
        assert baseline[0] == 404 and baseline[1]["error"] == "EXPIRED"
        assert _unknown_body(jobs, lambda: call_for(j["job_id"], b)) == baseline          # another session
        assert _unknown_body(jobs, lambda: call_for(j["job_id"], None)) == baseline       # no credential at all
        assert _unknown_body(jobs, lambda: call_for(j["job_id"], "x" * 24)) == baseline   # a never-issued id
    assert jobs.status(j["job_id"], a)["state"] == "succeeded"                            # the owner still can
    assert jobs.result(j["job_id"], None, a)[0] == 200 and jobs.cancel(j["job_id"], a)["state"] == "succeeded"


def test_h1_a_foreign_cancel_by_job_id_does_not_cancel_anything(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    a, b = sess(jobs), sess(jobs)
    j = jobs.start(cube, "req-own-00001", a, 1)
    started.wait(10)
    with pytest.raises(sj.JobError):
        jobs.cancel(j["job_id"], b)
    assert jobs.status(j["job_id"], a)["state"] == "running"
    gate.set()


def test_h1_replaced_job_id_never_leaks_across_sessions(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, honor_cancel=True, started=started))
    a, b = sess(jobs), sess(jobs)
    ja = jobs.start(cube, "req-a-000001", a, 1)
    started.wait(10)
    jb = jobs.start(cube, "req-b-000001", b, 1)                       # another session replaces A's running job
    assert jb["replaced_job_id"] is None                              # ...and learns nothing about it
    assert jobs.status(ja["job_id"], a)["state"] == "cancelled"
    jb2 = jobs.start(cube, "req-b-000002", b, 2)                      # the same session replacing its own job
    assert jb2["replaced_job_id"] == jb["job_id"]
    legacy = jobs.start(cube, "req-l-000001")                         # a legacy caller replacing a session job
    assert legacy["replaced_job_id"] is None
    legacy2 = jobs.start(cube, "req-l-000002")                        # legacy replacing legacy: as before
    assert legacy2["replaced_job_id"] == legacy["job_id"]
    sj_after_legacy = jobs.start(cube, "req-b-000003", b, 3)          # a session replacing a legacy job
    assert sj_after_legacy["replaced_job_id"] is None
    gate.set()


def test_h1_legacy_jobs_keep_todays_behaviour_for_job_id_operations(make, cube):
    jobs = make()
    j = jobs.start(cube, "req-l-000001")
    wait_state(jobs, j["job_id"], "succeeded")
    assert jobs.status(j["job_id"])["state"] == "succeeded"
    assert jobs.status(j["job_id"], sess(jobs))["state"] == "succeeded"       # no owner: any caller, as today
    assert jobs.result(j["job_id"])[0] == 200 and jobs.cancel(j["job_id"])["state"] == "succeeded"


def test_h1_http_routes_carry_the_credential(server, tmp_path):  # noqa: F811
    port, token = server
    path = str(fx.plain_cube_3mf(tmp_path / "h1.3mf"))
    _, a = call(port, "/scene/session", {}, token)
    _, b = call(port, "/scene/session", {}, token)
    _, job = call(port, "/scene/start", {"path": path, "request_id": "req-h1-000001", "client_id": a["client_id"], "seq": 1}, token)
    for route in ("/scene/status", "/scene/result", "/scene/cancel"):
        missing = call(port, route, {"job_id": job["job_id"]}, token)
        foreign = call(port, route, {"job_id": job["job_id"], "client_id": b["client_id"]}, token)
        unknown = call(port, route, {"job_id": "0" * 32, "client_id": b["client_id"]}, token)
        assert missing == foreign == unknown and missing[0] == 404 and missing[1]["error"] == "EXPIRED"
        bad = call(port, route, {"job_id": job["job_id"], "client_id": None}, token)
        assert bad[0] == 400
    code, ok = call(port, "/scene/status", {"job_id": job["job_id"], "client_id": a["client_id"]}, token)
    assert code == 200 and ok["job_id"] == job["job_id"]
    code, both = call(port, "/scene/cancel", {"job_id": job["job_id"], "client_id": a["client_id"], "request_id": "req-h1-000001"}, token)
    assert code == 400


def test_h1_job_id_cancel_and_result_touch_the_owner_session(make, cube):
    for how in ("cancel_job", "result"):
        now = [0.0]
        jobs = make(clock=lambda: now[0], session_ttl=100.0, ttl=100.0)
        s = sess(jobs)
        j = jobs.start(cube, "req-A-000002", s, 2)
        wait_state(jobs, j["job_id"], "succeeded")
        wait_for(lambda: not jobs.worker_alive())
        now[0] += 90.0
        (jobs.cancel(j["job_id"], s) if how == "cancel_job" else jobs.result(j["job_id"], None, s))
        now[0] += 90.0
        jobs.open_session()
        jobs.open_session()
        assert s in jobs._sessions, how


def _wedge_then_recover(make, cube):
    """A cancelled running job whose worker ignores the cancel, past the grace period: the engine is wedged."""
    now = [0.0]
    gate, started = threading.Event(), threading.Event()
    jobs = make(clock=lambda: now[0], wedge_grace=10.0, builder=fake_builder(gate, honor_cancel=False, started=started))
    s = sess(jobs)
    late = HeldStart(jobs, cube, "req-late-0002", s, 2)               # attempt 2 is delayed in flight
    first = jobs.start(cube, "req-one-00001", s, 1)
    assert started.wait(10)
    jobs.cancel_request(s, "req-one-00001", 1)                         # seq 1 running AND cancelled...
    now[0] += 100.0
    assert jobs.wedged()                                               # ...and the worker is stuck past the grace
    return jobs, s, gate, late, first


def test_h2_a_wedged_rejection_still_advances_the_watermark(make, cube):
    jobs, s, gate, late, _ = _wedge_then_recover(make, cube)
    refused(jobs, "WORKER_WEDGED", cube, "req-three-0003", s, 3, http=503)
    gate.set()                                                         # the stuck call returns: the worker recovers
    wait_for(lambda: not jobs.worker_alive())
    late.finish()                                                      # the delayed seq 2 finally arrives
    assert late.error is not None and late.error.code == "STALE_START"
    assert jobs.retained() == 1                                        # only the seq-1 job: seq 2 registered nothing
    refused(jobs, "STALE_START", cube, "req-three-0003", s, 3)         # an exact retry of the refused attempt is stale
    ok = jobs.start(cube, "req-four-0004", s, 4)                       # the documented recovery: fresh request_id, higher seq
    assert ok["state"] in ("queued", "running")


def test_h2_unsupported_format_and_missing_file_also_advance_the_watermark(make, cube, tmp_path):
    jobs = make()
    s = sess(jobs)
    late = HeldStart(jobs, cube, "req-late-0002", s, 2)
    text = tmp_path / "notes.txt"
    text.write_text("x")
    refused(jobs, "UNSUPPORTED_FORMAT", str(text), "req-three-0003", s, 3, http=422)
    late.finish()
    assert late.error.code == "STALE_START"
    late2 = HeldStart(jobs, cube, "req-late-0004", s, 4)
    refused(jobs, "INVALID_REQUEST", str(tmp_path / "missing.3mf"), "req-five-0005", s, 5, http=400)
    late2.finish()
    assert late2.error.code == "STALE_START"
    refused(jobs, "STALE_START", str(text), "req-old-00001", s, 1)                 # staleness is reported first and moves nothing
    assert jobs._sessions[s].watermark == 5
    assert jobs.retained() == 0


# ------------------------------------------------------------------ Astra optionals

def test_a_delayed_cancel_for_an_old_attempt_cannot_cancel_a_newer_job_that_reused_the_request_id(make, cube):
    now = [0.0]
    gate, started = threading.Event(), threading.Event()
    calls = []

    def builder(path, revision, ctl):
        calls.append(1)
        if len(calls) == 1:
            return b"{}"
        started.set()
        while not gate.wait(0.005):
            ctl.check()
        return b"{}"
    jobs = make(clock=lambda: now[0], ttl=10.0, builder=builder)
    s = sess(jobs)
    old = jobs.start(cube, "req-R-000001", s, 1)
    wait_state(jobs, old["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    now[0] += 60.0
    with pytest.raises(sj.JobError):
        st(jobs, old["job_id"])                                         # the old job was evicted
    new = jobs.start(cube, "req-R-000001", s, 5)                        # the request id is reused at a higher seq
    assert started.wait(10) and st(jobs, new["job_id"])["state"] == "running"
    out = jobs.cancel_request(s, "req-R-000001", 1)                     # the delayed cancel for the OLD attempt
    assert out["job_id"] is None
    assert st(jobs, new["job_id"])["state"] == "running"                # the newer job is untouched
    assert jobs.cancel_request(s, "req-R-000001", 5)["job_id"] == new["job_id"]
    gate.set()


def test_an_expired_session_whose_last_job_was_just_evicted_does_not_cause_session_limit(make, cube):
    now = [0.0]
    jobs = make(clock=lambda: now[0], max_sessions=1, session_ttl=50.0, ttl=50.0)
    s = sess(jobs)
    j = jobs.start(cube, "req-A-000001", s, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    now[0] += 500.0                                                     # the job AND the session expire together
    fresh = jobs.open_session()                                         # one call: evict the job, then prune the session
    assert fresh["client_id"] != s and s not in jobs._sessions


# ================================================================== round: exact retries and exact-attempt cancels

def test_b1_a_failed_precheck_on_an_exact_retry_keeps_the_original_job_reference(make, cube, tmp_path):
    jobs = make()
    s = sess(jobs)
    b = jobs.start(cube, "req-B-000002", s, 2)
    wait_state(jobs, b["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    hidden = cube + ".away"
    os.replace(cube, hidden)                                          # the file vanishes: the retry's precheck fails
    refused(jobs, "INVALID_REQUEST", cube, "req-B-000002", s, 2, http=400)
    assert jobs._sessions[s].current[3] == b["job_id"]                # the retained job's reference was NOT cleared
    os.replace(hidden, cube)
    again = jobs.start(cube, "req-B-000002", s, 2)                    # a later exact retry still gets the job
    assert again["job_id"] == b["job_id"]


def test_b1_concurrent_exact_retries_one_hashing_one_failing_its_precheck(make, cube):
    jobs = make()
    s = sess(jobs)
    b = jobs.start(cube, "req-B-000002", s, 2)
    status = wait_state(jobs, b["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    inside, release = threading.Event(), threading.Event()
    real_hash = jobs._current_hash

    def slow(path):                                                    # retry R1 is mid-hash, outside the lock
        inside.set()
        assert release.wait(10)
        return status["revision"]
    jobs._current_hash = slow
    out = {}

    def retry():
        try:
            out["r"] = jobs.start(cube, "req-B-000002", s, 2)
        except sj.JobError as exc:
            out["e"] = exc
    t = threading.Thread(target=retry, daemon=True)
    t.start()
    assert inside.wait(10)
    hidden = cube + ".away"
    os.replace(cube, hidden)
    refused(jobs, "INVALID_REQUEST", cube, "req-B-000002", s, 2, http=400)    # R2 fails its precheck meanwhile
    os.replace(hidden, cube)
    release.set()
    t.join(10)
    jobs._current_hash = real_hash
    assert "e" not in out, out.get("e") and out["e"].code
    assert out["r"]["job_id"] == b["job_id"]                          # R1 still gets the job that still exists


def test_b2_a_cancel_at_a_higher_seq_does_not_cancel_the_older_job_of_the_same_request(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    s = sess(jobs)
    five = jobs.start(cube, "req-R-000001", s, 5)
    started.wait(10)
    out = jobs.cancel_request(s, "req-R-000001", 6)                   # a cancel for seq 6, not for this attempt
    assert out["job_id"] is None
    assert st(jobs, five["job_id"])["state"] == "running"             # the seq-5 job is untouched
    assert jobs._sessions[s].dead_through == 6                        # but seq 6 and everything below stays refused
    refused(jobs, "CANCELLED_BEFORE_START", cube, "req-R-000002", s, 6)
    gate.set()


def test_b2_only_the_exact_attempt_is_cancelled(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    s = sess(jobs)
    five = jobs.start(cube, "req-R-000001", s, 5)
    started.wait(10)
    assert jobs.cancel_request(s, "req-R-000001", 4)["job_id"] is None      # an older attempt's cancel: no match
    assert st(jobs, five["job_id"])["state"] == "running"
    assert jobs._sessions[s].dead_through == 4
    out = jobs.cancel_request(s, "req-R-000001", 5)                         # the exact attempt
    assert out["job_id"] == five["job_id"] and out["state"] == "cancelled"
    assert jobs._sessions[s].dead_through == 5
    gate.set()
