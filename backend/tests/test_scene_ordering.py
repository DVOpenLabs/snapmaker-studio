"""Start ordering at the engine boundary: an abandoned start can never replace or cancel a newer one.

No sleeps decide anything here: the abandoned start A is held at the pre-registration seam
(`SceneJobs._check_source`, which runs before the registry lock) with a threading.Event until the test has
registered the wanted start B, then released, so it reaches the registry AFTER B every time.
"""
import threading

import pytest

from snapstudio_api import scene_jobs as sj
from tests import scene_fixtures as fx
from tests.test_scene_api import call, server  # noqa: F401  (the loopback server fixture)
from tests.test_scene_contract import sub_validator
from tests.test_scene_jobs import fake_builder, wait_for, wait_state

CLIENT = "client-aaaaaaaa"
OTHER = "client-bbbbbbbb"
_n = iter(range(1, 10**6))


def rid() -> str:
    return f"req-ord-{next(_n):08d}"


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


# ------------------------------------------------------------------ the bug: A arrives after B

def test_an_abandoned_start_arriving_after_the_wanted_one_is_refused_and_changes_nothing(make, cube):
    jobs = make()
    a = HeldStart(jobs, cube, "req-A-000001", CLIENT, 1)              # sent first, abandoned, delayed in flight
    b = jobs.start(cube, "req-B-000002", CLIENT, 2)                   # the wanted start arrives first
    wait_state(jobs, b["job_id"], "succeeded")
    before = jobs.retained()
    a.finish()
    assert a.error is not None and (a.error.http, a.error.code) == (409, "STALE_START")
    assert not list(sub_validator("error_response").iter_errors(a.error.body()))
    assert jobs.status(b["job_id"])["state"] == "succeeded"           # B was never cancelled or replaced
    assert jobs.retained() == before                                   # and A registered nothing
    assert jobs.start(cube, "req-B-000002", CLIENT, 2)["job_id"] == b["job_id"]


def test_the_stale_start_cannot_replace_a_RUNNING_wanted_start(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    a = HeldStart(jobs, cube, "req-A-000001", CLIENT, 1)
    b = jobs.start(cube, "req-B-000002", CLIENT, 2)
    assert started.wait(10) and jobs.status(b["job_id"])["state"] == "running"
    a.finish()
    assert a.error.code == "STALE_START"
    assert jobs.status(b["job_id"])["state"] == "running"             # not cancelled by the late arrival
    gate.set()
    assert wait_state(jobs, b["job_id"], "succeeded")["state"] == "succeeded"


# ------------------------------------------------------------------ cancel by (client_id, request_id)

def test_a_cancel_that_arrives_before_the_start_tombstones_it(make, cube):
    jobs = make()
    out = jobs.cancel_request(CLIENT, "req-A-000001")                  # nothing registered yet
    assert out["job_id"] is None and out["state"] == "cancelled" and out["error"]["code"] == "CANCELLED"
    assert not list(sub_validator("job_status").iter_errors(out))
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, "req-A-000001", CLIENT, 1)
    assert (e.value.http, e.value.code) == (409, "CANCELLED_BEFORE_START")
    assert jobs.retained() == 0                                        # nothing was registered
    fresh = jobs.start(cube, "req-A-000002", CLIENT, 2)               # a fresh request_id with a higher seq works
    assert wait_state(jobs, fresh["job_id"], "succeeded")["state"] == "succeeded"


def test_cancelling_by_request_cancels_only_the_exact_job(make, cube):
    gate, started = threading.Event(), threading.Event()
    jobs = make(builder=fake_builder(gate, started=started))
    a = jobs.start(cube, "req-A-000001", CLIENT, 1)
    started.wait(10)
    b = jobs.start(cube, "req-B-000002", CLIENT, 2)                   # replaces A as today
    assert jobs.status(a["job_id"])["state"] == "cancelled"
    jobs.cancel_request(CLIENT, "req-A-000001")                        # cancelling A (again)...
    assert jobs.status(b["job_id"])["state"] in ("queued", "running")  # ...never touches B
    jobs.cancel_request(OTHER, "req-B-000002")                         # same request_id, DIFFERENT client: no match
    assert jobs.status(b["job_id"])["state"] in ("queued", "running")
    jobs.cancel_request(CLIENT, "req-C-nonexistent")                   # another request: no match
    assert jobs.status(b["job_id"])["state"] in ("queued", "running")
    out = jobs.cancel_request(CLIENT, "req-B-000002")                  # the exact pair
    assert out["job_id"] == b["job_id"] and out["state"] == "cancelled"
    gate.set()


def test_a_legacy_job_is_not_matched_by_a_client_cancel(make, cube):
    jobs = make()
    legacy = jobs.start(cube, "req-L-000001")
    wait_state(jobs, legacy["job_id"], "succeeded")
    out = jobs.cancel_request(CLIENT, "req-L-000001")
    assert out["job_id"] is None
    assert jobs.status(legacy["job_id"])["state"] == "succeeded"


def test_cancel_by_job_id_is_unchanged(make, cube):
    jobs = make()
    j = jobs.start(cube, "req-J-000001", CLIENT, 1)
    wait_state(jobs, j["job_id"], "succeeded")
    assert jobs.cancel(j["job_id"])["state"] == "succeeded"
    with pytest.raises(sj.JobError) as e:
        jobs.cancel("0" * 32)
    assert e.value.code == "EXPIRED"


# ------------------------------------------------------------------ idempotency, remount, restart, retry, legacy

def test_repeat_of_the_highest_seq_is_idempotent_and_a_different_request_is_refused(make, cube):
    jobs = make()
    b = jobs.start(cube, "req-B-000002", CLIENT, 2)
    again = jobs.start(cube, "req-B-000002", CLIENT, 2)
    assert again["job_id"] == b["job_id"] and again["replaced_job_id"] is None
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, "req-X-000003", CLIENT, 2)
    assert (e.value.http, e.value.code) == (400, "INVALID_REQUEST") and e.value.extra["reason"] == "seq reused for another request_id"
    assert jobs.status(b["job_id"])["state"] in ("queued", "running", "succeeded")


def test_remount_continues_the_seq_and_a_restarted_client_is_independent(make, cube):
    jobs = make()
    for seq in (1, 2, 3):
        j = jobs.start(cube, rid(), CLIENT, seq)
        wait_state(jobs, j["job_id"], "succeeded")
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, rid(), CLIENT, 2)                              # an old attempt from the same process
    assert e.value.code == "STALE_START"
    fresh_process = jobs.start(cube, rid(), OTHER, 1)                   # app restart: new random client_id, seq 1
    assert wait_state(jobs, fresh_process["job_id"], "succeeded")["state"] == "succeeded"
    assert jobs.start(cube, rid(), CLIENT, 4)["state"] in ("queued", "running", "succeeded")


def test_retry_with_a_fresh_request_id_and_a_higher_seq_after_a_stale_refusal(make, cube):
    jobs = make()
    jobs.start(cube, "req-B-000002", CLIENT, 5)
    with pytest.raises(sj.JobError):
        jobs.start(cube, "req-A-000001", CLIENT, 4)
    retry = jobs.start(cube, "req-A-000009", CLIENT, 6)
    assert wait_state(jobs, retry["job_id"], "succeeded")["state"] == "succeeded"


def test_legacy_starts_without_the_fields_still_work_and_mix_freely(make, cube):
    jobs = make()
    a = jobs.start(cube, "req-L-000001")
    wait_state(jobs, a["job_id"], "succeeded")
    b = jobs.start(cube, "req-L-000002")
    wait_state(jobs, b["job_id"], "succeeded")
    c = jobs.start(cube, "req-O-000003", CLIENT, 7)
    wait_state(jobs, c["job_id"], "succeeded")
    d = jobs.start(cube, "req-L-000004")                                # legacy after ordered: not judged
    assert wait_state(jobs, d["job_id"], "succeeded")["state"] == "succeeded"


def test_two_clients_are_independent_and_do_not_judge_each_other(make, cube):
    jobs = make()
    jobs.start(cube, "req-A-000001", CLIENT, 50)
    b = jobs.start(cube, "req-B-000001", OTHER, 1)                      # a low seq for another client is fine
    assert b["state"] in ("queued", "running", "succeeded")
    held = HeldStart(jobs, cube, "req-B-000002", OTHER, 2)              # concurrent, in flight
    stale = jobs.start(cube, "req-A-000002", CLIENT, 51)
    held.finish()
    assert held.error is None and held.result is not None
    assert stale["job_id"]


# ------------------------------------------------------------------ bounded maps

def test_the_client_map_is_an_lru_and_the_live_client_keeps_its_ordering(make, cube):
    jobs = make()
    live = "client-live0001"
    jobs.start(cube, rid(), live, 10)
    for i in range(sj.MAX_CLIENTS + 5):                                  # many other clients come and go
        jobs.start(cube, rid(), f"client-{i:08d}", 1)
        jobs.start(cube, rid(), live, 11 + i)                            # the live client keeps being used (touched)
    assert len(jobs._clients) <= sj.MAX_CLIENTS
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, rid(), live, 10)
    assert e.value.code == "STALE_START"                                 # ordering for the live client survived eviction
    assert "client-00000000" not in jobs._clients                        # an idle one was evicted (oldest first)


def test_tombstones_are_a_bounded_fifo(make, cube):
    jobs = make()
    for i in range(sj.MAX_TOMBSTONES + 1):
        jobs.cancel_request(CLIENT, f"req-T-{i:08d}")
    assert len(jobs._tombstones) == sj.MAX_TOMBSTONES
    assert (CLIENT, "req-T-00000000") not in jobs._tombstones            # first in, first out
    assert (CLIENT, f"req-T-{sj.MAX_TOMBSTONES:08d}") in jobs._tombstones
    with pytest.raises(sj.JobError) as e:
        jobs.start(cube, f"req-T-{sj.MAX_TOMBSTONES:08d}", CLIENT, 1)
    assert e.value.code == "CANCELLED_BEFORE_START"


# ------------------------------------------------------------------ the real HTTP route and body validation

def test_http_stale_start_and_the_cancel_by_request_shape(server, tmp_path):  # noqa: F811
    port, token = server
    path = str(fx.plain_cube_3mf(tmp_path / "h.3mf"))
    code, b = call(port, "/scene/start", {"path": path, "request_id": "req-B-http0002", "client_id": CLIENT, "seq": 2}, token)
    assert code == 200 and not list(sub_validator("job_start").iter_errors(b))
    code, body = call(port, "/scene/start", {"path": path, "request_id": "req-A-http0001", "client_id": CLIENT, "seq": 1}, token)
    assert (code, body["error"]) == (409, "STALE_START")
    assert not list(sub_validator("error_response").iter_errors(body))
    code, status = call(port, "/scene/status", {"job_id": b["job_id"]}, token)
    assert code == 200 and status["state"] != "cancelled"               # B untouched
    code, c = call(port, "/scene/cancel", {"client_id": CLIENT, "request_id": "req-C-http0003"}, token)
    assert code == 200 and c["job_id"] is None and c["state"] == "cancelled"
    assert not list(sub_validator("job_status").iter_errors(c))
    code, body = call(port, "/scene/start", {"path": path, "request_id": "req-C-http0003", "client_id": CLIENT, "seq": 3}, token)
    assert (code, body["error"]) == (409, "CANCELLED_BEFORE_START")
    code, hit = call(port, "/scene/cancel", {"client_id": CLIENT, "request_id": "req-B-http0002"}, token)
    assert code == 200 and hit["job_id"] == b["job_id"]
    code, legacy = call(port, "/scene/start", {"path": path, "request_id": "req-L-http0004"}, token)
    assert code == 200


@pytest.mark.parametrize("extra", [
    {"client_id": CLIENT, "seq": 0}, {"client_id": CLIENT, "seq": -3}, {"client_id": CLIENT, "seq": "1"},
    {"client_id": CLIENT, "seq": True}, {"client_id": CLIENT, "seq": 1.5}, {"client_id": CLIENT, "seq": 2 ** 60},
    {"client_id": "short", "seq": 1}, {"client_id": "has space in it", "seq": 1}, {"client_id": "x" * 65, "seq": 1},
    {"client_id": 12345678, "seq": 1}, {"client_id": CLIENT}, {"seq": 1},
])
def test_http_start_rejects_malformed_ordering_fields(server, tmp_path, extra):  # noqa: F811
    port, token = server
    path = str(fx.plain_cube_3mf(tmp_path / "v.3mf"))
    code, body = call(port, "/scene/start", dict({"path": path, "request_id": "req-V-http0001"}, **extra), token)
    assert (code, body["error"]) == (400, "INVALID_REQUEST"), (extra, code, body)


@pytest.mark.parametrize("body", [
    {"client_id": "short", "request_id": "req-C-http0001"}, {"client_id": CLIENT},
    {"client_id": CLIENT, "request_id": "bad id"}, {"job_id": "0" * 32, "client_id": CLIENT, "request_id": "req-C-http0001"},
])
def test_http_cancel_rejects_malformed_bodies(server, body):  # noqa: F811
    port, token = server
    code, resp = call(port, "/scene/cancel", body, token)
    assert (code, resp["error"]) == (400, "INVALID_REQUEST"), (body, code, resp)


@pytest.mark.parametrize("body", [[1], "x", None, 7])
def test_http_non_object_bodies_are_still_400(server, body):  # noqa: F811
    port, token = server
    for route in sj.ROUTES:
        assert call(port, route, body, token)[0] == 400


def test_a_repeat_of_an_old_start_that_is_still_hashing_is_refused_if_a_newer_one_arrived(make, cube, monkeypatch):
    jobs = make()
    a = jobs.start(cube, "req-A-000001", CLIENT, 1)
    status = wait_state(jobs, a["job_id"], "succeeded")
    wait_for(lambda: not jobs.worker_alive())
    inside, release = threading.Event(), threading.Event()

    def slow_hash(path):                                   # the idempotent repeat hashes OUTSIDE the lock
        inside.set()
        assert release.wait(10)
        return status["revision"]
    monkeypatch.setattr(jobs, "_current_hash", slow_hash)
    out = {}

    def repeat():
        try:
            out["r"] = jobs.start(cube, "req-A-000001", CLIENT, 1)
        except sj.JobError as exc:
            out["e"] = exc
    t = threading.Thread(target=repeat, daemon=True)
    t.start()
    assert inside.wait(10)
    b = jobs.start(cube, "req-B-000002", CLIENT, 2)        # the wanted start gets in while A's repeat hashes
    release.set()
    t.join(10)
    assert "r" not in out and out["e"].code == "STALE_START"
    assert jobs.status(b["job_id"])["state"] in ("queued", "running", "succeeded")
