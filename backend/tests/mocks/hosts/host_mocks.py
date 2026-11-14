"""In-process 127.0.0.1 mock hosts for the host adapter tests.

Each mock is a `ThreadingHTTPServer` that COUNTS accepted connections and records every
request (method, path, header names/values lower-cased). They serve only the documented
read-only endpoints; anything else is 404. Synthetic payloads only.
"""
from __future__ import annotations

import http.server
import json
import threading
from typing import Callable

SECRET_KEY = "SYNTH-OCTOPRINT-KEY-0001"


class MockHost(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, routes: dict | None = None, *, require_key: str | None = None,
                 redirect_to: str | None = None):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes: dict = routes or {}      # path (no query) -> (status, json-able body)
        self.require_key = require_key
        self.redirect_to = redirect_to
        self.connections = 0
        self.requests: list = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02},
                                        daemon=True)

    def get_request(self):
        got = super().get_request()
        with self._lock:
            self.connections += 1
        return got

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def paths(self) -> list:
        return [r["path"] for r in self.requests]

    def start(self) -> "MockHost":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes = b"", extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        server: MockHost = self.server  # type: ignore[assignment]
        path = self.path.split("?", 1)[0]
        server.requests.append({"method": "GET", "path": path,
                                "headers": {k.lower(): v for k, v in self.headers.items()}})
        if server.redirect_to:
            return self._send(302, b"", {"Location": server.redirect_to})
        if server.require_key is not None and self.headers.get("X-Api-Key") != server.require_key:
            return self._send(403, b'{"error":"forbidden"}')
        hit = server.routes.get(path)
        if hit is None:
            return self._send(404, b'{"error":"not found"}')
        status, body = hit
        self._send(status, json.dumps(body).encode("utf-8"))

    def do_POST(self):  # noqa: N802 - mocks never accept writes; a POST is recorded and refused
        server: MockHost = self.server  # type: ignore[assignment]
        server.requests.append({"method": "POST", "path": self.path.split("?", 1)[0], "headers": {}})
        self._send(405, b"{}")

    do_PUT = do_DELETE = do_PATCH = do_POST


def make_moonraker(fixture_bundle: dict, *, octoprint_compat: bool = True) -> MockHost:
    """A Moonraker serving the replies held in a fixture bundle (wrapped replies, as on the wire)."""
    routes: dict = {}
    if fixture_bundle.get("server_info") is not None:
        routes["/server/info"] = (200, fixture_bundle["server_info"])
    for key, path in (("objects_list", "/printer/objects/list"),
                      ("print_task_config", "/printer/objects/query"),
                      ("system_info", "/machine/system_info")):
        if fixture_bundle.get(key) is not None:
            routes[path] = (200, fixture_bundle[key])
    if octoprint_compat:
        routes["/api/version"] = (200, {"api": "0.1", "server": "1.5.0", "text": "OctoPrint (Moonraker 0.9.3)"})
    return MockHost(routes).start()


def make_octoprint(*, require_key: str | None = SECRET_KEY) -> MockHost:
    return MockHost({"/api/version": (200, {"api": "0.1", "server": "1.9.3", "text": "OctoPrint 1.9.3"})},
                    require_key=require_key).start()
