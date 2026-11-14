"""In-process Lumina mock using only shapes present in the saved research."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from snapstudio_core.foundation.netguard import NetguardRefused, Response


class LuminaMock:
    def __init__(self, *, version: str = "2.0", mode: str = "normal") -> None:
        self.version = version
        self.mode = mode
        self.url = "http://127.0.0.1:8123"
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs) -> Response:
        path = urlsplit(url).path
        self.requests.append((method, path))
        if self.mode == "redirect" and path == "/openapi.json":
            raise NetguardRefused("redirect")
        if self.mode == "slow" and path == "/openapi.json":
            raise NetguardRefused("deadline")
        if self.mode == "large" and path == "/openapi.json":
            raise NetguardRefused("too_large")
        if path == "/openapi.json":
            payload = {"info": {"version": self.version}, "paths": {
                "/api/health": {}, "/api/convert/preview": {}, "/api/files/{file_id}": {}}}
            body = b"not-json" if self.mode == "malformed" else json.dumps(payload).encode()
            return Response(200, {"content-type": "application/json"}, body, None, len(body))
        if path == "/api/health":
            return Response(200, {"content-type": "application/json"}, b"{}", None, 2)
        if path == "/api/convert/preview" and method == "POST":
            payload = {"session_id": "session1", "status": "ok", "message": "Preview generated",
                       "preview_url": "/api/files/file1", "preview_glb_url": None,
                       "palette": [], "dimensions": {}, "contours": None}
            body = json.dumps(payload).encode()
            return Response(200, {"content-type": "application/json"}, body, None, len(body))
        if path == "/api/files/file1":
            raw = b"mock-3mf"
            return Response(200, {"content-type": "model/3mf"}, raw, None, len(raw))
        return Response(404, {"content-type": "application/json"}, b"{}", None, 2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


#: Synthetic artifact bytes. They are labelled bytes, not real 3MF/PNG/GLB documents.
HTTP_ARTIFACTS: dict[str, tuple[str, bytes]] = {
    "mfile": ("model/3mf", b"synthetic-mock-3mf-bytes"),
    "pngfile": ("image/png", b"\x89PNG\r\n\x1a\nsynthetic-mock-png-bytes"),
    "glbfile": ("model/gltf-binary", b"glTFsynthetic-mock-glb-bytes"),
}


class LuminaHttpMock:
    """A synthetic Lumina-shaped HTTP service on loopback, for route tests and screenshots.

    It is NOT Lumina. It answers only the shapes in the saved research, with fixed synthetic bytes.
    `preview_id` / `glb_id` pick which artifact the preview response points at.
    """

    def __init__(self, *, preview_id: str = "pngfile", glb_id: str | None = "glbfile",
                 version: str = "2.0", artifacts: dict | None = None, host: str = "127.0.0.1",
                 port: int = 0) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.artifacts = dict(artifacts if artifacts is not None else HTTP_ARTIFACTS)
        self.requests: list[tuple[str, str]] = []
        self.uploads: list[dict] = []
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                return None

            def _send(self, status: int, ctype: str, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                mock.requests.append(("GET", path))
                if path == "/openapi.json":
                    doc = {"info": {"version": version}, "paths": {
                        "/api/health": {}, "/api/convert/preview": {}, "/api/files/{file_id}": {}}}
                    return self._send(200, "application/json", json.dumps(doc).encode())
                if path == "/api/health":
                    return self._send(200, "application/json", b"{}")
                if path.startswith("/api/files/"):
                    item = mock.artifacts.get(path[len("/api/files/"):])
                    if item is not None:
                        return self._send(200, item[0], item[1])
                return self._send(404, "application/json", b"{}")

            def do_POST(self):
                path = urlsplit(self.path).path
                mock.requests.append(("POST", path))
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                if path != "/api/convert/preview":
                    return self._send(404, "application/json", b"{}")
                mock.uploads.append({"bytes": body, "type": self.headers.get("Content-Type", "")})
                payload = {"session_id": "session1", "status": "ok", "message": "Preview generated",
                           "preview_url": f"/api/files/{preview_id}",
                           "preview_glb_url": f"/api/files/{glb_id}" if glb_id else None,
                           "palette": [], "dimensions": {}, "contours": None}
                self._send(200, "application/json", json.dumps(payload).encode())

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.url = f"http://{host}:{self._server.server_port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        return None
