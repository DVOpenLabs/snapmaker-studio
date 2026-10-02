"""#53: a provider read is bounded by one overall wall-clock deadline, not only
by a per-socket-read timeout. A device that drips its status line, headers, a
redirect body, chunk framing or the body itself must not be able to hold a
request open for far longer than the configured timeout. Shared by every
provider (Spoolman, Bambuddy, SpoolEase) because they all read through `_fetch`.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

from snapstudio_core import material_providers as mp


class _DripServer:
    """Replies to the first request with `prefix` at once, then drips `payload`
    one byte every `interval` seconds (bounded by `total` bytes)."""

    def __init__(self, interval: float, prefix: bytes, payload: bytes = b"x",
                 total: int = 200):
        self.interval = interval
        self.prefix = prefix
        self.payload = payload
        self.total = total
        self.sent = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._srv.settimeout(0.2)
                conn, _ = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(2)
            conn.recv(4096)
            if self.prefix:
                conn.sendall(self.prefix)
            while self.sent < self.total and not self._stop.is_set():
                conn.sendall(self.payload)
                with self._lock:
                    self.sent += 1
                time.sleep(self.interval)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._srv.close()


_JSON_HEADERS = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Content-Length: 200\r\n\r\n")


@pytest.fixture
def serve():
    servers = []

    def make(interval, prefix=_JSON_HEADERS, payload=b"x", total=200):
        server = _DripServer(interval, prefix, payload, total)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def _assert_cut_off(url: str, *, timeout: float = 1.0, ceiling: float = 3.0):
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        mp._fetch(url, timeout=timeout)
    elapsed = time.monotonic() - started
    assert elapsed < ceiling, f"the read outlived its deadline: {elapsed:.1f}s"


def test_a_slow_drip_body_is_cut_off_at_the_overall_deadline(serve):
    # one byte every 0.4 s with a 1.0 s per-read timeout: no single read ever
    # times out, so before #53 this ran for the whole 200-byte body (~80 s).
    server = serve(0.4)
    _assert_cut_off(f"http://127.0.0.1:{server.port}/")
    assert server.sent < server.total


def test_a_dripped_status_line_is_cut_off_at_the_overall_deadline(serve):
    # no headers at all: the status line itself arrives one byte at a time.
    server = serve(0.4, prefix=b"", payload=b"H")
    _assert_cut_off(f"http://127.0.0.1:{server.port}/")


def test_a_dripped_chunk_size_line_is_cut_off_at_the_overall_deadline(serve):
    # chunked framing: the chunk-size line drips inside ONE stdlib read call.
    chunked = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
               b"Transfer-Encoding: chunked\r\n\r\n")
    server = serve(0.4, prefix=chunked, payload=b"1")
    _assert_cut_off(f"http://127.0.0.1:{server.port}/")


def test_a_dripped_redirect_body_is_cut_off_at_the_overall_deadline(serve):
    # urllib drains an intermediate redirect response for itself, before
    # `_fetch` ever sees a final response.
    redirect = (b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:1/\r\n"
                b"Content-Length: 200\r\n\r\n")
    server = serve(0.4, prefix=redirect)
    _assert_cut_off(f"http://127.0.0.1:{server.port}/")


@pytest.mark.parametrize("name", ["spoolman", "bambuddy", "spoolease"])
def test_a_slow_drip_is_reported_with_the_timeout_wording_for_every_provider(serve, name):
    server = serve(0.4)
    url = f"http://127.0.0.1:{server.port}"
    started = time.monotonic()
    if name == "spoolease":
        state = mp.spoolease(url, timeout=1.0, key="k")
    else:
        state = getattr(mp, name)(url, timeout=1.0)
    assert time.monotonic() - started < 4.0
    assert state["available"] is False
    assert "in time" in state["error"]


def test_the_size_cap_still_applies(serve):
    server = serve(0.0, total=500)
    with pytest.raises(mp._ProviderTransportError) as caught:
        mp._fetch(f"http://127.0.0.1:{server.port}/", timeout=3.0, limit=50)
    assert caught.value.code == "oversized"


def test_a_prompt_body_is_read_in_full(serve):
    headers = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
               b"Content-Length: 300\r\n\r\n")
    server = serve(0.0, prefix=headers, total=300)
    body = mp._fetch(f"http://127.0.0.1:{server.port}/", timeout=3.0)
    assert body == b"x" * 300
