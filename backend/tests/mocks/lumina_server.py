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
