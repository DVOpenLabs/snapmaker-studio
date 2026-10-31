"""Bounded client for the documented Lumina Layers local API (API 2.0)."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from snapstudio_core.foundation.netguard import (
    NetguardRefused,
    Response,
    confirm_write_origin,
    local_request,
    require_local_url,
    revoke_write_origin,
)

SUPPORTED_API_VERSION = "2.0"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
_FILE_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
_REQUEST: Callable[..., Response] = local_request


class LuminaError(Exception):
    """A safe, bounded error without response bodies or configured URLs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Discovery:
    api_version: str
    paths: frozenset[str]
    evidence: str = "mock-service-tested"


@dataclass(frozen=True)
class Artifact:
    sha256: str
    size_bytes: int
    kind: str
    data: bytes


class LuminaClient:
    """Talk to a user-supplied local Lumina service through foundation netguard."""

    def __init__(self, service_url: str, *, timeout: float = 15.0,
                 request: Callable[..., Response] | None = None) -> None:
        require_local_url(service_url)
        parts = urlsplit(service_url if "://" in service_url else "http://" + service_url)
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise LuminaError("invalid_service_url")
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.timeout = timeout
        self._request = request or _REQUEST
        self._discovery: Discovery | None = None
        self._write_enabled = False

    def discover(self) -> Discovery:
        """Read the captured FastAPI OpenAPI document and require its known API version."""
        response = self._request("GET", self.origin + "/openapi.json", timeout=self.timeout,
                                 max_bytes=MAX_JSON_BYTES)
        data = self._json(response, "discovery")
        info = data.get("info")
        paths = data.get("paths")
        if not isinstance(info, dict) or not isinstance(paths, dict):
            raise LuminaError("malformed_discovery")
        version = info.get("version")
        if not isinstance(version, str) or not version:
            raise LuminaError("unknown_version")
        if version != SUPPORTED_API_VERSION:
            raise LuminaError("unsupported_version")
        self._discovery = Discovery(version, frozenset(p for p in paths if isinstance(p, str)))
        return self._discovery

    def health_check(self) -> Mapping[str, Any]:
        """Confirm the documented identity route before enabling API writes.

        The health response schema is absent from the saved research. It is retained opaquely
        and never interpreted as proof of a version or capability.
        """
        if self._discovery is None:
            self.discover()
        self._require_discovery("/api/health")
        response = self._request("GET", self.origin + "/api/health", timeout=self.timeout,
                                 max_bytes=MAX_JSON_BYTES)
        payload = self._json(response, "health")
        if not isinstance(payload, dict):
            raise LuminaError("malformed_health")
        confirm_write_origin(self.origin)
        self._write_enabled = True
        return payload

    def preview(self, image: bytes, filename: str, *, lut_name: str,
                fields: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        """Submit the documented multipart preview form; no parameters are inferred."""
        self._require_discovery("/api/convert/preview")
        if not self._write_enabled:
            raise LuminaError("identity_not_confirmed")
        if not isinstance(image, bytes) or not image or len(image) > MAX_INPUT_BYTES:
            raise LuminaError("invalid_input")
        if not isinstance(filename, str) or not filename or any(c in filename for c in "\r\n\x00\"\\"):
            raise LuminaError("invalid_filename")
        if not isinstance(lut_name, str) or not lut_name or len(lut_name) > 256:
            raise LuminaError("invalid_lut")
        form = {"lut_name": lut_name}
        for key, value in (fields or {}).items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,64}", key) or key in {"image", "lut_name"}:
                raise LuminaError("invalid_form")
            if not isinstance(value, str) or len(value) > 1024:
                raise LuminaError("invalid_form")
            form[key] = value
        boundary = "sslumina" + uuid.uuid4().hex
        body = bytearray()
        for key, value in form.items():
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{filename}\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode())
        body.extend(image)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        response = self._request("POST", self.origin + "/api/convert/preview",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                 body=bytes(body), timeout=self.timeout, max_bytes=MAX_JSON_BYTES,
                                 max_request_bytes=MAX_INPUT_BYTES + 128 * 1024,
                                 write_ok=True, origin=self.origin)
        data = self._json(response, "preview")
        session_id = data.get("session_id")
        status = data.get("status")
        preview_url = data.get("preview_url")
        if not isinstance(session_id, str) or not isinstance(status, str) or not isinstance(preview_url, str):
            raise LuminaError("malformed_preview")
        if not preview_url.startswith("/api/files/"):
            raise LuminaError("unknown_preview_locator")
        return data

    def fetch_artifact(self, file_id: str) -> Artifact:
        """Fetch a documented registered file and derive identity from returned bytes."""
        self._require_discovery("/api/files/{file_id}")
        if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
            raise LuminaError("invalid_file_id")
        response = self._request("GET", self.origin + f"/api/files/{file_id}",
                                 timeout=self.timeout, max_bytes=MAX_ARTIFACT_BYTES)
        if response.status < 200 or response.status >= 300 or response.body is None:
            raise LuminaError("artifact_unavailable")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        kind = {"model/3mf": "3mf", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml": "3mf",
                "model/gltf-binary": "glb", "image/png": "png"}.get(content_type, "unknown")
        raw = response.body
        return Artifact(hashlib.sha256(raw).hexdigest(), len(raw), kind, raw)

    def progress(self, *_: Any, **__: Any) -> None:
        """Progress is unknown: the saved Lumina research publishes no progress route or shape."""
        self._require_discovery()
        raise LuminaError("progress_unknown")

    def cancel(self, *_: Any, **__: Any) -> None:
        """Cancellation is unknown: the saved Lumina research publishes no cancel route or shape."""
        self._require_discovery()
        raise LuminaError("cancel_unknown")

    def close(self) -> None:
        if self._write_enabled:
            revoke_write_origin(self.origin)
            self._write_enabled = False

    def _require_discovery(self, path: str | None = None) -> None:
        if self._discovery is None:
            self.discover()
        if path and path not in self._discovery.paths:
            raise LuminaError("route_unavailable")

    @staticmethod
    def _json(response: Response, operation: str) -> dict[str, Any]:
        if response.status < 200 or response.status >= 300 or response.body is None:
            raise LuminaError(f"{operation}_failed")
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LuminaError("malformed_json") from None
        if not isinstance(data, dict):
            raise LuminaError("malformed_json")
        return data
