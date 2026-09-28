"""The local-only transport: filtering by what the resolver actually returns,
per-candidate connect deadline slicing, and the proxy/redirect/TLS guarantees
every provider (Spoolman, Bambuddy, SpoolEase) shares (plan-39 §3.1/§3.2 +
addendum §1).
"""
from __future__ import annotations

import socket
import time

import pytest

from snapstudio_core import material_providers as mp


def _answer(ip: str, port: int = 80):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0) if family == socket.AF_INET6
           else (ip, port))


# --- A-1/A-2: filter, not refuse, on a name with mixed answers ---------------

def test_a_name_resolving_only_to_a_public_address_is_refused(monkeypatch):
    monkeypatch.setattr(mp, "_resolve", lambda host, port, type=None: [_answer("8.8.8.8", port)])
    out = mp.read("spoolease", "http://spoolease.local", key="k")
    assert out["error_code"] == "invalid_address"
    assert "own network" in out["error"]


def test_mixed_answers_only_ever_dial_the_local_one(monkeypatch):
    """A2: a name resolving to both a global and a local address is read, and
    only the local candidate is ever connected to — proved by recording every
    address a socket was actually asked to `connect()` to, not merely by the
    read succeeding (which it would even if the global address were dialled
    first and merely failed over)."""
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    real_socket = socket.socket
    dialled: list[str] = []

    class RecordingSocket:
        def __init__(self, *a, **k):
            self._s = real_socket(*a, **k)

        def __getattr__(self, name):
            return getattr(self._s, name)

        def connect(self, address):
            dialled.append(address[0])
            return self._s.connect(address)

    monkeypatch.setattr(socket, "socket", RecordingSocket)
    try:
        monkeypatch.setattr(
            mp, "_resolve",
            lambda host, p, type=None: [_answer("93.184.216.34", port), _answer("127.0.0.1", port)])
        out = mp.spoolman("http://spoolman.local")
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is True
    assert dialled == ["127.0.0.1"], dialled


def _OkHandler():
    import http.server
    import json as _json

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = _json.dumps([]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return Handler


# --- validate_provider_url is unchanged (no %25 change; A-7) -----------------

@pytest.mark.parametrize("address", [
    "http://[::1]:7912", "http://[fe80::1%251]:7912", "http://[fe80::1]:7912",
])
def test_scoped_and_plain_ipv6_literals_pass_through_unchanged(address):
    assert mp.validate_provider_url(address).startswith(("http://", "https://"))


# --- connect-deadline slicing (addendum §1) -----------------------------------

_REAL_SOCKET = socket.socket


class _RecordingSocket:
    """A stand-in socket whose `connect()` either succeeds instantly or blocks
    until its own `settimeout()` value elapses, so a test can prove a
    black-holed candidate never consumes more than its own share."""

    instances: list["_RecordingSocket"] = []

    def __init__(self, family, kind, proto, *, behavior="ok", real_target=None):
        self.family, self.kind, self.proto = family, kind, proto
        self.behavior = behavior
        self.real_target = real_target
        self.timeout_seen = None
        self.closed = False
        self._real = None
        _RecordingSocket.instances.append(self)

    def settimeout(self, value):
        self.timeout_seen = value

    def connect(self, addr):
        if self.behavior == "blackhole":
            time.sleep(self.timeout_seen or 0)
            raise TimeoutError("timed out")
        if self.behavior == "refused":
            raise ConnectionRefusedError("refused")
        if self.behavior == "ok":
            self._real = _REAL_SOCKET(self.family, self.kind, self.proto)
            self._real.settimeout(self.timeout_seen)
            self._real.connect(self.real_target)

    def getpeername(self):
        return self._real.getpeername() if self._real else ("127.0.0.1", 0)

    def setsockopt(self, *a):
        pass

    def close(self):
        self.closed = True
        if self._real:
            self._real.close()

    def makefile(self, *a, **k):
        return self._real.makefile(*a, **k)

    def sendall(self, *a, **k):
        return self._real.sendall(*a, **k)

    def recv(self, *a, **k):
        return self._real.recv(*a, **k)

    def recv_into(self, *a, **k):
        return self._real.recv_into(*a, **k)


def _fake_socket_factory(behaviors: list[str], real_target):
    it = iter(behaviors)

    def factory(family=socket.AF_INET, kind=socket.SOCK_STREAM, proto=0, fileno=None):
        # `socketserver`'s own `accept()` calls `socket.socket(..., fileno=fd)`
        # on an already-open fd — that call must reach the real constructor
        # unchanged, or the fake HTTP server this test drives against stops
        # being able to accept the very connection being tested.
        if fileno is not None:
            return _REAL_SOCKET(family, kind, proto, fileno=fileno)
        behavior = next(it, "ok")
        return _RecordingSocket(family, kind, proto, behavior=behavior, real_target=real_target)

    return factory


def test_a_blackholed_first_candidate_cannot_starve_the_second(monkeypatch):
    """addendum §1 A-10a: two local candidates, the first black-holed — the
    second still gets a real share of the deadline and the read succeeds."""
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _RecordingSocket.instances.clear()
    try:
        monkeypatch.setattr(
            mp, "_resolve",
            lambda host, p, type=None: [_answer("10.0.0.9", port), _answer("127.0.0.1", port)])
        monkeypatch.setattr(
            socket, "socket",
            _fake_socket_factory(["blackhole", "ok"], ("127.0.0.1", port)))
        started = time.monotonic()
        out = mp.spoolman("http://spoolman.local", timeout=1.0)
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is True
    assert elapsed <= 1.5
    first, second = _RecordingSocket.instances[0], _RecordingSocket.instances[1]
    assert first.closed is True
    assert first.timeout_seen == pytest.approx(0.5, abs=0.1)


def test_three_blackholed_candidates_fail_within_the_deadline(monkeypatch):
    _RecordingSocket.instances.clear()
    monkeypatch.setattr(
        mp, "_resolve",
        lambda host, p, type=None: [_answer("10.0.0.1"), _answer("10.0.0.2"), _answer("10.0.0.3")])
    monkeypatch.setattr(
        socket, "socket",
        _fake_socket_factory(["blackhole", "blackhole", "blackhole"], ("127.0.0.1", 1)))
    started = time.monotonic()
    out = mp.spoolman("http://spoolman.local", timeout=0.6)
    elapsed = time.monotonic() - started
    assert out["available"] is False
    assert elapsed <= 1.1
    assert all(s.closed for s in _RecordingSocket.instances)


# --- proxy bypass --------------------------------------------------------------

def test_environment_proxy_is_ignored_for_a_provider_read(monkeypatch):
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    try:
        out = mp.spoolman(f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is True


# --- TCP_NODELAY / ENOPROTOOPT (L-3) ------------------------------------------

def test_enoprotoopt_on_setsockopt_is_ignored(monkeypatch):
    import errno
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _OkHandler())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    real_socket = socket.socket

    class NoNodelaySocket:
        def __init__(self, *a, **k):
            self._s = real_socket(*a, **k)

        def __getattr__(self, name):
            return getattr(self._s, name)

        def setsockopt(self, level, opt, value):
            if opt == socket.TCP_NODELAY:
                raise OSError(errno.ENOPROTOOPT, "no such option")
            return self._s.setsockopt(level, opt, value)

    monkeypatch.setattr(socket, "socket", NoNodelaySocket)
    try:
        out = mp.spoolman(f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()
        server.server_close()
    assert out["available"] is True


def test_a_genuine_setsockopt_failure_is_not_swallowed(monkeypatch):
    """A-14b: this must never dial a real LAN address — `_resolve` is stubbed
    to a genuine loopback listener so the connect actually succeeds and
    `setsockopt` is genuinely reached (recorded, so the test proves it ran
    rather than merely proving the read failed for some other reason)."""
    import errno

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    real_socket = socket.socket
    setsockopt_calls: list[tuple] = []

    class BadSocket:
        def __init__(self, *a, **k):
            self._s = real_socket(*a, **k)

        def __getattr__(self, name):
            return getattr(self._s, name)

        def setsockopt(self, level, opt, value):
            if opt == socket.TCP_NODELAY:
                setsockopt_calls.append((level, opt, value))
                raise OSError(errno.EINVAL, "bad value")
            return self._s.setsockopt(level, opt, value)

    monkeypatch.setattr(socket, "socket", BadSocket)
    monkeypatch.setattr(mp, "_resolve",
                        lambda host, p, type=None: [_answer("127.0.0.1", port)])
    try:
        out = mp.spoolman("http://spoolman.local:1", timeout=0.5)
    finally:
        server.close()
    assert out["available"] is False
    assert setsockopt_calls, "setsockopt was never reached — the failure was not genuine"


# --- A-12 (B-1): a name that does not resolve, for every provider ------------
#
# `_LocalOnlyHTTPConnection.connect()` must let the resolver's own OSError
# (`socket.gaierror`) propagate unwrapped, exactly as stdlib's own
# `HTTPConnection.connect` does — `urllib.request.AbstractHTTPHandler.do_open`
# then wraps it into a `URLError` exactly once. Wrapping it a second time
# inside `connect()` produced a `URLError` whose `.reason` was itself a
# `URLError` (since `URLError` is an `OSError` subclass and gets caught by
# do_open's own `except OSError`), which showed up as
# "<urlopen error ...>" for Spoolman/Bambuddy (which print `exc.reason`
# directly) and as the bare class name "URLError" for SpoolEase (which maps
# `exc.reason` through `_transport_reason`, expecting the raw resolver
# exception).

def _unresolvable(monkeypatch):
    def fake_resolve(host, port, type=None):
        raise socket.gaierror(11001, "getaddrinfo failed")
    monkeypatch.setattr(mp, "_resolve", fake_resolve)


def test_spoolman_unresolvable_name_matches_base_form(monkeypatch):
    _unresolvable(monkeypatch)
    out = mp.spoolman("http://nonexistent.invalid.lan:1234")
    assert out["available"] is False
    assert out["error"] == "Spoolman did not answer: [Errno 11001] getaddrinfo failed"
    assert "<urlopen error" not in out["error"]


def test_bambuddy_unresolvable_name_matches_base_form(monkeypatch):
    _unresolvable(monkeypatch)
    out = mp.bambuddy("http://nonexistent.invalid.lan:1234")
    assert out["available"] is False
    assert out["error"] == "Bambuddy did not answer: [Errno 11001] getaddrinfo failed"
    assert "<urlopen error" not in out["error"]


def test_spoolease_unresolvable_name_gives_name_not_found(monkeypatch):
    _unresolvable(monkeypatch)
    out = mp.spoolease("http://nonexistent.invalid.lan:1234", key="Fx7-tEsT")
    assert out["available"] is False
    assert out["error"] == "SpoolEase did not answer: name not found"
    assert out["error_code"] == "transport"
