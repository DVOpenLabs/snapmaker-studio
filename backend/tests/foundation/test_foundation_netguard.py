"""netguard: the only network transport. Local stdlib servers count connections and requests."""
from __future__ import annotations

import ast
import http.server
import logging
import os
import pathlib
import socketserver
import threading
import time

import pytest

from snapstudio_core import material_providers as legacy
from snapstudio_core.foundation import netguard
from snapstudio_core.foundation.netguard import NetguardRefused, local_request, require_local_url

SECRET = "SECRET-KEY-123456"


# ------------------------------------------------------------------ servers

class _CountingHTTP(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, behaviour):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.behaviour = behaviour
        self.connections = 0
        self.requests: list[dict] = []
        self._lock = threading.Lock()

    def get_request(self):
        got = super().get_request()
        with self._lock:
            self.connections += 1
        return got

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence
        pass

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        self.server.requests.append({"method": self.command, "path": self.path,
                                     "headers": {k.lower(): v for k, v in self.headers.items()}, "body": data})
        self.server.behaviour(self)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _go


def _ok(body=b"ok", extra=None):
    def behave(h):
        h.send_response(200)
        h.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(body)
    return behave


@pytest.fixture
def serve():
    started: list[_CountingHTTP] = []

    def make(behaviour=None):
        server = _CountingHTTP(behaviour or _ok())
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        started.append(server)
        return server

    yield make
    for server in started:
        server.shutdown()
        server.server_close()


class _RawServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture
def raw_serve():
    started = []

    def make(script):
        class H(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.recv(65536)
                    script(self.request)
                except OSError:
                    pass
        server = _RawServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        started.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield make
    for server in started:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _clean_registry():
    netguard.clear_write_origins()
    yield
    netguard.clear_write_origins()


# ------------------------------------------------------------------ happy path and addresses

def test_local_get_works_and_returns_body(serve):
    server = serve(_ok(b"hello"))
    r = local_request("GET", server.origin + "/server/info?x=1")
    assert (r.status, r.body, r.bytes_read) == (200, b"hello", 5)
    assert server.requests[0]["path"] == "/server/info?x=1"


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "[2606:4700::1111]", "169.254.1.1",
                                     "[fe80::1]", "[2002:808:808::1]", "[2001:0:4136:e378::1]",
                                     "[::ffff:8.8.8.8]", "0.0.0.0", "[64:ff9b::808:808]"])
def test_public_and_special_addresses_refused_without_dialling(monkeypatch, address):
    monkeypatch.setattr(netguard, "_dial", lambda *a, **k: pytest.fail("dialled"))
    with pytest.raises(NetguardRefused):
        local_request("GET", f"http://{address}:9/")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "192.168.1.5", "172.16.0.1", "100.64.0.9",
                                     "[::1]", "[fd00::1]", "[::ffff:192.168.1.5]"])
def test_local_addresses_pass_the_syntax_policy(address):
    assert require_local_url(f"http://{address}:7125").startswith("http://")


def test_name_resolving_to_public_refused_at_connect_time(monkeypatch):
    dialled = []
    monkeypatch.setattr(netguard, "_dial", lambda *a, **k: dialled.append(a))
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", "http://printer.local:7125/x", resolver=lambda h: ["93.184.216.34"])
    assert e.value.code == "off_network" and dialled == []


def test_mixed_answer_dials_only_local_candidates(serve, monkeypatch):
    server = serve()
    real = netguard._dial
    seen = []
    monkeypatch.setattr(netguard, "_dial", lambda a, p, t: (seen.append(a), real(a, p, t))[1])
    port = server.server_address[1]
    r = local_request("GET", f"http://nas.example.net:{port}/", resolver=lambda h: ["8.8.8.8", "127.0.0.1"])
    assert r.status == 200 and seen == ["127.0.0.1"]


def test_dns_rebinding_is_resolved_once_and_dials_the_vetted_address(serve):
    server = serve()
    answers = iter([["127.0.0.1"], ["8.8.8.8"]])
    calls = []

    def resolver(host):
        calls.append(host)
        return next(answers)

    port = server.server_address[1]
    assert local_request("GET", f"http://rebind.lan:{port}/", resolver=resolver).status == 200
    assert calls == ["rebind.lan"] and server.connections == 1


# ------------------------------------------------------------------ resolver bounds

def test_stalled_resolver_returns_within_deadline():
    release = threading.Event()
    pool = netguard.ResolverPool(4)
    start = time.monotonic()
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", "http://stuck.example.net:80/", timeout=0.4,
                      resolver=lambda h: (release.wait(10), ["127.0.0.1"])[1], resolver_pool=pool)
    release.set()
    assert e.value.code == "deadline" and time.monotonic() - start < 2.0


def test_require_local_url_with_stalled_resolver_returns_within_deadline():
    release = threading.Event()
    start = time.monotonic()
    with pytest.raises(NetguardRefused) as e:
        require_local_url("http://stuck.example.net", timeout=0.3,
                          resolver=lambda h: (release.wait(10), [])[1], resolver_pool=netguard.ResolverPool(4))
    release.set()
    assert e.value.code == "deadline" and time.monotonic() - start < 2.0


def test_saturated_resolver_pool_fails_fast_without_queueing():
    release = threading.Event()
    pool = netguard.ResolverPool(2)
    blocked = lambda h: (release.wait(10), ["127.0.0.1"])[1]
    for _ in range(2):
        with pytest.raises(NetguardRefused):
            require_local_url("http://a.example.net", timeout=0.05, resolver=blocked, resolver_pool=pool)
    start = time.monotonic()
    with pytest.raises(NetguardRefused) as e:
        require_local_url("http://b.example.net", timeout=5, resolver=blocked, resolver_pool=pool)
    release.set()
    assert e.value.code == "unavailable" and time.monotonic() - start < 0.5


def test_default_pool_is_four_threads():
    assert netguard.RESOLVER_THREADS == 4


def test_resolver_exception_is_not_surfaced():
    def boom(host):
        raise OSError(f"secret detail for {host}")
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", "http://x.example.net/", resolver=boom)
    assert "secret detail" not in str(e.value) and e.value.__cause__ is None


# ------------------------------------------------------------------ redirects and credentials

@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_cross_origin_redirect_refused_second_server_untouched(serve, status):
    second = serve()

    def redirect(h):
        h.send_response(status)
        h.send_header("Location", second.origin + "/steal")
        h.send_header("Content-Length", "0")
        h.end_headers()

    first = serve(redirect)
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", first.origin + "/a", headers={"X-Api-Key": SECRET}, origin=first.origin)
    assert e.value.code == "redirect"
    assert second.connections == 0 and second.requests == []
    assert SECRET not in str(e.value) and SECRET not in repr(e.value)


def test_same_host_redirect_also_refused(serve):
    holder = {}

    def redirect(h):
        h.send_response(302)
        h.send_header("Location", holder["s"].origin + "/b")
        h.send_header("Content-Length", "0")
        h.end_headers()

    holder["s"] = server = serve(redirect)
    with pytest.raises(NetguardRefused):
        local_request("GET", server.origin + "/a")
    assert len(server.requests) == 1


def test_credential_sent_only_to_configured_origin(serve):
    server = serve()
    local_request("GET", server.origin + "/x", headers={"X-Api-Key": SECRET, "Accept": "a"}, origin=server.origin)
    assert server.requests[-1]["headers"].get("x-api-key") == SECRET
    # default port canonicalised: http://127.0.0.1:80 == http://127.0.0.1
    assert netguard._split("http://h").canonical == netguard._split("http://h:80").canonical
    assert netguard._split("https://h").canonical == netguard._split("https://h:443").canonical
    # different port, or no configured origin: dropped, other headers kept
    other = f"http://127.0.0.1:{server.server_address[1] + 1}"
    local_request("GET", server.origin + "/x", headers={"X-Api-Key": SECRET, "Accept": "a"}, origin=other)
    local_request("GET", server.origin + "/x", headers={"Authorization": "Bearer " + SECRET})
    assert "x-api-key" not in server.requests[-2]["headers"] and server.requests[-2]["headers"]["accept"] == "a"
    assert "authorization" not in server.requests[-1]["headers"]


def test_caller_marked_secret_header_follows_the_same_rule(serve):
    server = serve()
    other = f"http://127.0.0.1:{server.server_address[1] + 1}"
    local_request("GET", server.origin + "/", headers={"X-Custom-Token": SECRET}, origin=other,
                  secret_headers=["x-custom-token"])
    assert "x-custom-token" not in server.requests[-1]["headers"]
    local_request("GET", server.origin + "/", headers={"X-Custom-Token": SECRET}, origin=server.origin,
                  secret_headers=["x-custom-token"])
    assert server.requests[-1]["headers"]["x-custom-token"] == SECRET


def test_concurrent_requests_with_different_credentials_never_cross(serve):
    server = serve()
    errors = []

    def one(i):
        try:
            local_request("GET", server.origin + f"/r{i}", headers={"X-Api-Key": f"key-{i}"}, origin=server.origin)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(server.requests) == 12
    assert all(r["headers"]["x-api-key"] == "key-" + r["path"][2:] for r in server.requests)


def test_echoed_credentials_are_redacted_in_response_and_logs(serve, caplog):
    server = serve(lambda h: _ok(("you sent " + h.headers["X-Api-Key"]).encode(),
                                 {"X-Echo": h.headers["X-Api-Key"]})(h))
    caplog.set_level(logging.DEBUG)
    r = local_request("GET", server.origin + "/", headers={"X-Api-Key": SECRET}, origin=server.origin)
    assert SECRET.encode() not in r.body and SECRET not in repr(r) and SECRET not in str(r.headers)
    assert SECRET not in caplog.text


def test_errors_never_contain_header_values_or_urls(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", "http://127.0.0.1:1/path?token=" + SECRET, headers={"X-Api-Key": SECRET},
                      origin="http://127.0.0.1:1", timeout=0.5)
    assert SECRET not in str(e.value) and SECRET not in repr(e.value) and "127.0.0.1" not in str(e.value)
    assert SECRET not in caplog.text and e.value.__cause__ is None


@pytest.mark.parametrize("name,value", [("Host", "evil"), ("X-A", "a\r\nX-B: b"), ("Content-Length", "1"),
                                        ("Bad Name", "v"), ("Connection", "upgrade")])
def test_dangerous_headers_refused(serve, name, value):
    server = serve()
    with pytest.raises(NetguardRefused):
        local_request("GET", server.origin + "/", headers={name: value})
    assert server.connections == 0


# ------------------------------------------------------------------ proxies and TLS

def test_proxy_environment_is_ignored(serve, monkeypatch):
    proxy = serve()
    target = serve()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(var, proxy.origin)
    monkeypatch.setenv("NO_PROXY", "")
    assert local_request("GET", target.origin + "/").status == 200
    assert proxy.connections == 0 and len(target.requests) == 1


def test_tls_context_verifies_certificates_and_hostname():
    import ssl
    ctx = netguard._tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_https_to_a_plain_server_fails_closed(serve):
    server = serve()
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", server.origin.replace("http://", "https://") + "/", timeout=2)
    assert e.value.code in ("tls", "network")


# ------------------------------------------------------------------ deadline and caps

def test_slow_headers_hit_the_deadline(raw_serve):
    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\n")
        for _ in range(60):
            sock.sendall(b"X-Slow: a\r\n"[:3])
            time.sleep(0.1)
    url = raw_serve(script)
    start = time.monotonic()
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", url + "/", timeout=0.6)
    assert e.value.code == "deadline" and time.monotonic() - start < 3


def test_slow_body_hits_the_deadline(raw_serve):
    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        for _ in range(60):
            sock.sendall(b"x")
            time.sleep(0.1)
    url = raw_serve(script)
    start = time.monotonic()
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", url + "/", timeout=0.6)
    assert e.value.code == "deadline" and time.monotonic() - start < 3


def test_response_body_cap(serve):
    server = serve(_ok(b"a" * 5000))
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", server.origin + "/", max_bytes=1000)
    assert e.value.code == "too_large"
    assert local_request("GET", server.origin + "/", max_bytes=5000).bytes_read == 5000


def test_chunked_body_without_length_is_capped(raw_serve):
    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        for _ in range(50):
            sock.sendall(b"64\r\n" + b"x" * 100 + b"\r\n")
        sock.sendall(b"0\r\n\r\n")
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", raw_serve(script) + "/", max_bytes=1000)
    assert e.value.code == "too_large"


def test_response_header_cap(serve):
    server = serve(_ok(b"x", {"X-Big": "a" * 5000}))
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", server.origin + "/", max_bytes=1024)
    assert e.value.code == "too_large"


def test_request_body_cap_sends_nothing(serve):
    server = serve()
    with pytest.raises(NetguardRefused) as e:
        local_request("POST", server.origin + "/x", body=b"a" * 2000, max_bytes=1000, write_ok=True)
    assert e.value.code == "too_large" and server.connections == 0


def test_stream_to_writes_capped_temp_file_and_cleans_up(serve, tmp_path):
    server = serve(_ok(b"b" * 3000))
    r = local_request("GET", server.origin + "/f", stream_to=tmp_path, max_bytes=4000)
    assert r.body is None and r.bytes_read == 3000
    assert pathlib.Path(r.path).parent == tmp_path and pathlib.Path(r.path).read_bytes() == b"b" * 3000
    os.unlink(r.path)
    with pytest.raises(NetguardRefused):
        local_request("GET", server.origin + "/f", stream_to=tmp_path, max_bytes=1000)
    assert list(tmp_path.iterdir()) == []


def test_stream_to_partial_file_removed_on_deadline(raw_serve, tmp_path):
    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n" + b"x" * 50)
        time.sleep(3)
    with pytest.raises(NetguardRefused):
        local_request("GET", raw_serve(script) + "/", stream_to=tmp_path, timeout=0.5)
    assert list(tmp_path.iterdir()) == []


def test_stream_to_requires_an_existing_directory(serve, tmp_path):
    server = serve()
    with pytest.raises(NetguardRefused):
        local_request("GET", server.origin + "/", stream_to=tmp_path / "missing")
    assert server.connections == 0


def test_head_has_no_body(serve):
    server = serve(_ok(b"abc"))
    r = local_request("HEAD", server.origin + "/")
    assert r.status == 200 and r.body is None


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True, "3", 10_000])
def test_timeout_validated(bad):
    with pytest.raises(NetguardRefused) as e:
        local_request("GET", "http://127.0.0.1:9/", timeout=bad)
    assert e.value.code == "bad_args"


# ------------------------------------------------------------------ method and path policy

_DENIED = [
    "/printer/print/start", "/printer/print", "/printer/gcode/script", "/printer/emergency_stop",
    "/printer/firmware_restart", "/printer/restart", "/machine", "/machine/reboot", "/machine/shutdown",
    "/machine/system_info/x", "/server/files/upload", "/api/printer", "/api/printer/tool", "/api/job",
    "/api/job/x",
    # normalisation traps
    "/PRINTER/Print", "/printer//print", "//printer/print", "/printer/./print", "/x/../printer/print",
    "/../printer/print", "/%70rinter/print", "/printer/%70rint", "/printer/print/", "/%2e%2e/printer/print",
    "/x/%2e%2e/printer/print", "/x/%2E%2E/machine/reboot", "/printer;x=1/print", "/printer/print;jsessionid=1",
    "/api/printer;x/anything", "/api/./printer", "/x/..;/printer/print", "/x%2f..%2fprinter/print",
    "/printer/%252e%252e/print", "/printer\\print", "/api/%2e/printer",
]


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("path", _DENIED)
def test_denylist_matrix_applies_before_any_connection(serve, path, method):
    server = serve()
    with pytest.raises(NetguardRefused) as e:
        local_request(method, server.origin + path)
    assert e.value.code == "path" and server.connections == 0


@pytest.mark.parametrize("path", ["/printer/print", "/printer/gcode/script", "/machine/reboot",
                                  "/server/files/upload", "/api/printer", "/api/job"])
def test_denylist_applies_to_confirmed_write_origins_too(serve, path):
    server = serve()
    netguard.confirm_write_origin(server.origin)
    for method in ("POST", "PUT", "DELETE"):
        with pytest.raises(NetguardRefused) as e:
            local_request(method, server.origin + path, write_ok=True, body=b"{}")
        assert e.value.code == "path"
    assert server.connections == 0


def test_machine_system_info_is_allowed_for_get_only(serve):
    server = serve()
    assert local_request("GET", server.origin + "/machine/system_info").status == 200
    assert local_request("GET", server.origin + "/MACHINE/system_info?x=1").status == 200
    with pytest.raises(NetguardRefused):
        local_request("HEAD", server.origin + "/machine/system_info")
    netguard.confirm_write_origin(server.origin)
    with pytest.raises(NetguardRefused):
        local_request("POST", server.origin + "/machine/system_info", write_ok=True, body=b"")


@pytest.mark.parametrize("path", ["/printer/objects/query", "/printer/print_status", "/printerx/print",
                                  "/api/printers", "/api/health", "/api/lut/list", "/api/convert/start",
                                  "/api/files/other", "/server/info", "/a?next=/printer/print"])
def test_unrelated_paths_are_not_caught_by_prefix_rules(serve, path):
    server = serve()
    assert local_request("GET", server.origin + path).status == 200


@pytest.mark.parametrize("path", ["/api/files/local", "/api/files/local/x.gcode", "/api/files/sdcard",
                                  "/server/jsonrpc", "/server/job_queue/job", "/API/Files/Local"])
def test_extra_paths_allow_get_only(serve, path):
    server = serve()
    assert local_request("GET", server.origin + path).status == 200
    netguard.confirm_write_origin(server.origin)
    for method in ("HEAD", "POST", "PUT", "DELETE", "PATCH"):
        before = server.connections
        with pytest.raises(NetguardRefused) as e:
            local_request(method, server.origin + path, write_ok=True, body=None if method == "HEAD" else b"{}")
        assert e.value.code == "path" and server.connections == before


def test_lumina_style_client_against_moonraker_mock_sends_zero_non_get(serve):
    server = serve()
    netguard.confirm_write_origin(server.origin)
    attempts = ["/api/files/local", "/api/files/sdcard", "/server/jsonrpc", "/server/job_queue/job",
                "/printer/print/start", "/api/job", "/api/printer/command"]
    for path in attempts:
        with pytest.raises(NetguardRefused):
            local_request("POST", server.origin + path, write_ok=True, body=b"{}")
    assert [r for r in server.requests if r["method"] != "GET"] == []


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_non_get_needs_write_flag(serve, method):
    server = serve()
    with pytest.raises(NetguardRefused) as e:
        local_request(method, server.origin + "/api/convert/start", body=b"{}")
    assert e.value.code in ("method", "bad_args") and server.connections == 0


@pytest.mark.parametrize("method", ["CONNECT", "TRACE", "OPTIONS", "", "GET /x HTTP/1.0\r\n"])
def test_unknown_methods_refused(serve, method):
    server = serve()
    with pytest.raises(NetguardRefused):
        local_request(method, server.origin + "/", write_ok=True)
    assert server.connections == 0


def test_write_flag_without_confirmed_origin_refused(serve):
    server = serve()
    with pytest.raises(NetguardRefused) as e:
        local_request("POST", server.origin + "/api/convert/start", write_ok=True, body=b"{}")
    assert e.value.code == "write_origin" and server.connections == 0


def test_confirmed_origin_allows_write_and_is_per_origin(serve):
    one, two = serve(), serve()
    netguard.confirm_write_origin(one.origin)
    r = local_request("POST", one.origin + "/api/convert/start", write_ok=True, body=b"{}")
    assert r.status == 200 and one.requests[-1]["body"] == b"{}"
    with pytest.raises(NetguardRefused):
        local_request("POST", two.origin + "/api/convert/start", write_ok=True, body=b"{}")
    netguard.revoke_write_origin(one.origin)
    with pytest.raises(NetguardRefused):
        local_request("POST", one.origin + "/api/convert/start", write_ok=True, body=b"{}")


def test_get_with_body_refused(serve):
    server = serve()
    with pytest.raises(NetguardRefused):
        local_request("GET", server.origin + "/", body=b"x")


def test_path_is_sent_normalised(serve):
    server = serve()
    local_request("GET", server.origin + "/a//b/./c/../d;p=1?q=1&r=2#frag")
    assert server.requests[-1]["path"] == "/a/b/d?q=1&r=2"


# ------------------------------------------------------------------ syntax and parity

_PARITY_INPUTS = [
    "http://127.0.0.1:7912", "192.168.1.9:7912", "https://10.0.0.5", "http://8.8.8.8", "http://[::1]:7125",
    "http://[fe80::1]", "http://169.254.10.1:80", "http://100.64.1.1", "http://[2002::1]", "http://[2001::1]",
    "http://[::ffff:8.8.8.8]", "http://[::ffff:192.168.1.5]", "ftp://127.0.0.1", "file:///etc/passwd",
    "http://user:pw@127.0.0.1", "http://127.0.0.1:abc", "http://127.0.0.1:70000", "", "   ",
    "http://" + "1" * 300, "http://[fd00::1]:8080", "HTTP://127.0.0.1:7125", "http://127.0.0.1:0",
]


# Deliberate differences: netguard is stricter. Link-local is never local here, and port 0 is refused
# (the legacy check silently drops it).
_STRICTER = {"http://[fe80::1]", "http://169.254.10.1:80", "http://127.0.0.1:0"}


@pytest.mark.parametrize("value", _PARITY_INPUTS)
def test_require_local_url_matches_legacy_for_ip_literals(value):
    try:
        expected = legacy.validate_provider_url(value)
    except legacy.InvalidProviderAddress:
        expected = None
    try:
        got = require_local_url(value)
    except NetguardRefused:
        got = None
    if value in _STRICTER:
        assert got is None and expected is not None, value
    else:
        assert got == expected, value


def test_require_local_url_allows_a_path_where_legacy_does_not():
    assert require_local_url("http://127.0.0.1:7125/server/info?a=1") == "http://127.0.0.1:7125/server/info?a=1"
    with pytest.raises(legacy.InvalidProviderAddress):
        legacy.validate_provider_url("http://127.0.0.1:7125/server/info")


@pytest.mark.parametrize("name,expected", [("printer.local", True), ("spoolman", True), ("localhost", True),
                                           ("nas.home.arpa", True), ("example.com", False)])
def test_typed_name_policy(name, expected):
    answers = {"example.com": ["93.184.216.34"]}
    resolver = lambda h: answers.get(h, [])
    if expected:
        assert require_local_url(f"http://{name}", resolver=resolver)
    else:
        with pytest.raises(NetguardRefused):
            require_local_url(f"http://{name}", resolver=resolver)


def test_private_fqdn_is_local_when_it_resolves_locally():
    assert require_local_url("http://spool.example.net:7912", resolver=lambda h: ["192.168.1.9"])


def test_require_local_url_never_calls_the_legacy_resolver(monkeypatch):
    monkeypatch.setattr(legacy, "_resolve", lambda *a, **k: pytest.fail("legacy resolver used"))
    require_local_url("http://spool.example.net", resolver=lambda h: ["192.168.1.9"])


# ------------------------------------------------------------------ guards

def test_only_netguard_imports_transport_modules():
    root = pathlib.Path(netguard.__file__).parent
    banned = {"socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "urllib.error"}
    offenders = []
    for path in root.glob("*.py"):
        if path.name == "netguard.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            offenders += [f"{path.name}:{n}" for n in names if n in banned or n.split(".")[0] in {"urllib3", "requests"}]
    assert offenders == []
    assert netguard.socket is not None and netguard.ssl is not None


# ------------------------------------------------------------------ streamed redaction (R1)

def test_streamed_body_echoing_credentials_is_redacted(serve, tmp_path):
    server = serve(lambda h: _ok(("auth=" + h.headers["Authorization"] + " key=" + h.headers["X-Api-Key"]
                                  + " tail").encode())(h))
    r = local_request("GET", server.origin + "/", headers={"Authorization": "Bearer " + SECRET, "X-Api-Key": SECRET},
                      origin=server.origin, stream_to=tmp_path)
    data = pathlib.Path(r.path).read_bytes()
    assert SECRET.encode() not in data and b"[redacted]" in data and data.endswith(b" tail")


@pytest.mark.parametrize("stream", [False, True])
def test_authorization_scheme_token_alone_is_redacted(serve, tmp_path, stream):
    server = serve(lambda h: _ok(h.headers["Authorization"].split()[1].encode())(h))
    kwargs = {"stream_to": tmp_path} if stream else {}
    r = local_request("GET", server.origin + "/", headers={"Authorization": "Bearer " + SECRET},
                      origin=server.origin, **kwargs)
    data = pathlib.Path(r.path).read_bytes() if stream else r.body
    assert SECRET.encode() not in data and data == b"[redacted]"


@pytest.mark.parametrize("chunk", [1, 3, 7, 11])
def test_streamed_secret_split_across_read_boundaries_is_redacted(raw_serve, tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(netguard, "_READ_CHUNK", chunk)
    body = b"xx" + SECRET.encode() + b"yy" + SECRET.encode()

    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body))
        for i in range(0, len(body), 2):
            sock.sendall(body[i:i + 2])
            time.sleep(0.01)
    origin = raw_serve(script)
    r = local_request("GET", origin + "/", headers={"X-Api-Key": SECRET}, origin=origin, stream_to=tmp_path)
    assert pathlib.Path(r.path).read_bytes() == b"xx[redacted]yy[redacted]"


def test_streamed_secret_split_at_the_very_end_is_still_redacted(raw_serve, tmp_path, monkeypatch):
    monkeypatch.setattr(netguard, "_READ_CHUNK", 4)
    body = b"head" + SECRET.encode()

    def script(sock):
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body))
        sock.sendall(body)
    origin = raw_serve(script)
    r = local_request("GET", origin + "/", headers={"X-Api-Key": SECRET}, origin=origin, stream_to=tmp_path)
    assert pathlib.Path(r.path).read_bytes() == b"head[redacted]"


def test_credential_echoed_in_status_reason_is_redacted(raw_serve):
    def script(sock):
        sock.sendall(("HTTP/1.1 200 bad " + SECRET + "\r\nContent-Length: 0\r\n\r\n").encode())
    origin = raw_serve(script)
    r = local_request("GET", origin + "/", headers={"X-Api-Key": SECRET}, origin=origin)
    assert SECRET not in r.reason and "[redacted]" in r.reason and SECRET not in repr(r)


def test_body_redactor_unit_cases():
    red = netguard._BodyRedactor(["abc", "abcdef"])
    out = red.feed(b"zzab") + red.feed(b"cdefzz") + red.finish()
    assert out == b"zz[redacted]zz"
    assert netguard._BodyRedactor([]).feed(b"abc") == b"abc"
