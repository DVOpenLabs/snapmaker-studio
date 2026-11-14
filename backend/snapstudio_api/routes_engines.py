"""Routes of the Engines track: an optional, user-configured local Lumina-compatible service.

    POST /engines/lumina/formats   {}                                                  -> {formats, ...}
    POST /engines/lumina/status    {service_url}                                       -> {status, ...}
    POST /engines/lumina/generate  {service_url, image_path, lut_name, format, out_dir?} -> {generated, ...}

Studio does not slice and does not control anything here. The service is whatever local address the user
typed; it is reached only through `foundation.netguard` (loopback / LAN, no redirects, bounded). The
generated artifact is written as a NEW file in a Studio-owned folder (or a local folder the user chose),
never over or next to the input image. No response carries a filesystem path or a service response body.
Progress and cancel are `unknown`: the saved Lumina research publishes neither, so none is invented.

Evidence: mock-service-tested. No real Lumina installation has been exercised.
"""
from __future__ import annotations

import os
import re

from snapstudio_core import paths
from snapstudio_core.engines import local_input
from snapstudio_core.engines.lumina import MAX_INPUT_BYTES, LuminaClient, LuminaError
from snapstudio_core.foundation.netguard import NetguardRefused

from . import ext_routes
from . import request_validation as rv

EVIDENCE = "mock-service-tested"
GENERATED_BY = "a user-configured local Lumina-compatible service (not verified)"
ADVISORY = ("Studio did not watch this file being made. It came from a service you configured, which "
            "Studio has not verified. Inspect it before you use it; Studio does not slice or print it.")
DEFAULT_OUT_FOLDER = "lumina-output"
MAX_PATH_CHARS = 4096
MAX_URL_CHARS = 512

#: The explicit list. A format is never inferred; anything else is refused.
SUPPORTED_FORMATS: tuple[dict, ...] = (
    {"kind": "3mf", "meaning": "A 3MF model file returned by the service.", "evidence": EVIDENCE},
    {"kind": "png", "meaning": "A PNG preview image returned by the service.", "evidence": EVIDENCE},
    {"kind": "glb", "meaning": "A binary glTF (GLB) preview model returned by the service.", "evidence": EVIDENCE},
)
FORMAT_KINDS = tuple(f["kind"] for f in SUPPORTED_FORMATS)

_FILE_URL = re.compile(r"\A/api/files/([A-Za-z0-9_-]{1,128})\Z")
_EXT = re.compile(r"\A\.[A-Za-z0-9]{1,8}\Z")

#: Plain explanations per adapter error code. Never a service body, URL or path.
LUMINA_MESSAGES = {
    "invalid_service_url": "Enter only the service address, for example http://192.168.1.20:8000, with no path.",
    "discovery_failed": "The service did not answer its description request. Check the address and that it is running.",
    "malformed_discovery": "The service described itself in a shape Studio does not recognise.",
    "malformed_json": "The service answered with something Studio could not read.",
    "unknown_version": "The service did not say which API version it speaks, so Studio will not use it.",
    "unsupported_version": "The service speaks an API version Studio has not been tested with.",
    "health_failed": "The service did not pass its identity check, so Studio did not send anything to it.",
    "malformed_health": "The service identity check answered in a shape Studio does not recognise.",
    "route_unavailable": "The service does not offer a route Studio needs.",
    "identity_not_confirmed": "The service identity was not confirmed, so Studio did not send anything to it.",
    "preview_failed": "The service refused or failed the request.",
    "malformed_preview": "The service answered in a shape Studio does not recognise.",
    "unknown_preview_locator": "The service pointed at a file location Studio does not recognise.",
    "artifact_unavailable": "The service did not provide the file it announced.",
    "invalid_file_id": "The service named a file in a form Studio will not fetch.",
    "invalid_input": "The image is empty or larger than Studio will send.",
    "invalid_lut": "Enter a LUT name of up to 256 characters.",
    "progress_unknown": "Progress is unknown: the service does not publish a progress route Studio can rely on.",
    "cancel_unknown": "Cancel is unknown: the service does not publish a cancel route Studio can rely on.",
}
_GENERIC_ENGINE = "The service could not be used."


def _refusal(code: str, message: str) -> tuple[int, dict]:
    return 422, {"error": "refusal", "code": code, "message": message}


def _lumina_refusal(exc: LuminaError) -> tuple[int, dict]:
    return _refusal(exc.code, LUMINA_MESSAGES.get(exc.code, _GENERIC_ENGINE))


def _netguard_refusal(exc: NetguardRefused) -> tuple[int, dict]:
    return _refusal(f"network_{exc.code}", str(exc))


def _service_url(data: dict) -> str:
    return rv.require_bounded_str(data, "service_url", MAX_URL_CHARS).strip()


def _format_list_text() -> str:
    return ", ".join(FORMAT_KINDS)


@ext_routes.route("/engines/lumina/formats")
def formats(data: dict) -> tuple[int, dict]:
    return 200, {
        "formats": [dict(f) for f in SUPPORTED_FORMATS],
        "evidence": EVIDENCE,
        "progress": "unknown",
        "cancel": "unknown",
        "note": ("Formats are listed explicitly and chosen by you; Studio never infers one. "
                 "Evidence is a synthetic loopback mock: no real Lumina installation was exercised."),
    }


@ext_routes.route("/engines/lumina/status")
def status(data: dict) -> tuple[int, dict]:
    url = _service_url(data)
    client = None
    try:
        client = LuminaClient(url)
        discovery = client.discover()
        client.health_check()
        return 200, {
            "status": "ok",
            "api_version": discovery.api_version,
            "can_generate": {"/api/convert/preview", "/api/files/{file_id}"} <= set(discovery.paths),
            "progress": "unknown",
            "cancel": "unknown",
            "evidence": EVIDENCE,
            "note": ("That answer is not proof of what the service is or "
                     "that it will produce a good result."),
        }
    except NetguardRefused as exc:
        if exc.code in ("syntax", "off_network", "public_address", "unresolvable"):
            return _netguard_refusal(exc)
        return 200, {"status": "unknown", "code": f"network_{exc.code}", "message": str(exc),
                     "progress": "unknown", "cancel": "unknown", "evidence": EVIDENCE}
    except LuminaError as exc:
        if exc.code == "invalid_service_url":
            return _lumina_refusal(exc)
        return 200, {"status": "unknown", "code": exc.code,
                     "message": LUMINA_MESSAGES.get(exc.code, _GENERIC_ENGINE),
                     "progress": "unknown", "cancel": "unknown", "evidence": EVIDENCE}
    finally:
        if client is not None:
            client.close()


def _image_path(data: dict) -> str:
    raw = rv.require_bounded_str(data, "image_path", MAX_PATH_CHARS)
    if "\x00" in raw:
        raise rv.ValidationError("Invalid 'image_path'")
    if local_input.is_network_or_device_path(raw) or local_input.reaches_network(raw):
        raise rv.ValidationError("That image path is a network or device location. Choose a file on this computer.")
    if not os.path.exists(raw):
        raise rv.ValidationError("That image file was not found.")
    if not local_input.is_local_regular_file(raw, max_bytes=MAX_INPUT_BYTES):
        raise rv.ValidationError("That is not a regular image file Studio can send "
                                 f"(it must be a file of at most {MAX_INPUT_BYTES // (1024 * 1024)} MB).")
    return raw


def _out_dir(data: dict, image_path: str) -> tuple[str, str]:
    """(directory, location label). The folder must be Studio's own or an existing local one."""
    raw = data.get("out_dir")
    if raw is None or raw == "":
        target = os.path.join(paths.data_dir(), DEFAULT_OUT_FOLDER)
        os.makedirs(target, exist_ok=True)
        label = "Studio's lumina-output folder"
    else:
        if not isinstance(raw, str) or len(raw) > MAX_PATH_CHARS or "\x00" in raw:
            raise rv.ValidationError("Invalid 'out_dir'")
        if not local_input.is_local_directory(raw):
            raise rv.ValidationError("That output folder is not an existing local folder Studio can write to.")
        target = raw
        label = "the folder you chose"
    try:
        if os.path.samefile(target, os.path.dirname(os.path.abspath(image_path))):
            raise rv.ValidationError("Choose an output folder other than the image's own folder, so the "
                                     "original is never written next to.")
    except OSError:
        raise rv.ValidationError("That output folder is not an existing local folder Studio can write to.") from None
    return target, label


def _write_new(directory: str, kind: str, sha256: str, data: bytes) -> str:
    """Create a new file, never replacing one. Returns the file name only."""
    for n in range(1, 1000):
        name = f"lumina-{sha256[:12]}.{kind}" if n == 1 else f"lumina-{sha256[:12]}-{n}.{kind}"
        try:
            fd = os.open(os.path.join(directory, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return name
    raise rv.ValidationError("The output folder already holds too many files with this name.")


def _read_input(path: str) -> bytes:
    with open(path, "rb") as handle:
        blob = handle.read(MAX_INPUT_BYTES + 1)
    if not blob or len(blob) > MAX_INPUT_BYTES:
        raise rv.ValidationError("The image is empty or larger than Studio will send.")
    return blob


@ext_routes.route("/engines/lumina/generate")
def generate(data: dict) -> tuple[int, dict]:
    url = _service_url(data)
    fmt = data.get("format")
    if not isinstance(fmt, str) or fmt not in FORMAT_KINDS:
        raise rv.ValidationError(f"Choose one of the supported formats: {_format_list_text()}. "
                                 "Studio does not guess a format.")
    lut = rv.require_bounded_str(data, "lut_name", 256)
    image_path = _image_path(data)
    out_dir, location = _out_dir(data, image_path)
    image = _read_input(image_path)
    suffix = os.path.splitext(image_path)[1]
    upload_name = "input" + (suffix if _EXT.match(suffix) else "")

    client = None
    try:
        client = LuminaClient(url)
        client.discover()
        client.health_check()
        preview = client.preview(image, upload_name, lut_name=lut)
        locators = [preview.get("preview_url"), preview.get("preview_glb_url")]
        seen: list[str] = []
        artifact = None
        for locator in locators:
            match = _FILE_URL.match(locator) if isinstance(locator, str) else None
            if match is None:
                continue
            candidate = client.fetch_artifact(match.group(1))
            seen.append(candidate.kind)
            if candidate.kind == fmt:
                artifact = candidate
                break
        if artifact is None:
            produced = ", ".join(sorted(set(seen))) if seen else "no file"
            return _refusal("format_not_produced",
                            f"You asked for {fmt}, but the service returned {produced}. Nothing was saved. "
                            f"Choose a format the service produced, from: {_format_list_text()}.")
        name = _write_new(out_dir, artifact.kind, artifact.sha256, artifact.data)
        return 200, {
            "generated": True,
            "file_name": name,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "kind": artifact.kind,
            "generated_by": GENERATED_BY,
            "location_label": location,
            "advisory": ADVISORY,
            "progress": "unknown",
            "cancel": "unknown",
            "evidence": EVIDENCE,
        }
    except NetguardRefused as exc:
        return _netguard_refusal(exc)
    except LuminaError as exc:
        return _lumina_refusal(exc)
    finally:
        if client is not None:
            client.close()
