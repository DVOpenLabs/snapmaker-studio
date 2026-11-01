"""Routes of the Passport track: build, import and verify a job passport.

    POST /passport/build    {entries:[{path, role, parents?}], recipes?, material_mappings?}
                              -> {passport, paths, diagnostics, losses}
    POST /passport/import   {passport, base_dir?, paths?}   -> {passport, parentage, verification, ...}
    POST /passport/verify   {passport, base_dir?, paths?}   -> {verification}

Files are only read (hashed). The routes make no network request and never touch a printer.
A chain built here is `declared` by the user; this version does not see a prepare or slice happen.
`paths` in a response maps artifact ids to the local files they were read from, for the caller's
own later verify call; the passport itself never contains a path.
"""
from __future__ import annotations

from snapstudio_core import localpath
from snapstudio_core.passport import build_passport, import_passport, verify_passport
from snapstudio_core.passport.model import MAX_ARTIFACTS, decode_passport

from . import ext_routes
from . import request_validation as rv

MAX_PATH_CHARS = 1024
MAX_PATHS = 2 * MAX_ARTIFACTS


def _entries(data: dict) -> list:
    raw = data.get("entries")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ARTIFACTS:
        raise rv.ValidationError("Invalid 'entries'")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise rv.ValidationError("Invalid 'entries'")
        out.append({"path": rv.require_bounded_str(item, "path", MAX_PATH_CHARS),
                    "role": rv.require_bounded_str(item, "role", 16),
                    "parents": item.get("parents"), "producer": item.get("producer")})
    return out


def _location_hints(data: dict) -> tuple:
    base_dir = rv.optional_bounded_str(data, "base_dir", MAX_PATH_CHARS)
    if base_dir is not None and not localpath.is_local_directory(base_dir):
        raise rv.ValidationError("Invalid 'base_dir'")
    raw = data.get("paths")
    if raw is None:
        return base_dir or None, {}
    if not isinstance(raw, dict) or len(raw) > MAX_PATHS or not all(
            isinstance(k, str) and 0 < len(k) <= 128 and isinstance(v, str) and 0 < len(v) <= MAX_PATH_CHARS
            for k, v in raw.items()):
        raise rv.ValidationError("Invalid 'paths'")
    return base_dir or None, dict(raw)


def _document(data: dict):
    doc = data.get("passport")
    if not isinstance(doc, dict):
        raise rv.ValidationError("Invalid 'passport'")
    return doc


@ext_routes.route("/passport/build")
def build(data: dict) -> tuple[int, dict]:
    result = build_passport(_entries(data), recipes=data.get("recipes"),
                            material_mappings=data.get("material_mappings"))
    body = result.to_dict()
    body["paths"] = result.paths
    return 200, body


@ext_routes.route("/passport/import")
def import_(data: dict) -> tuple[int, dict]:
    base_dir, paths = _location_hints(data)
    return 200, import_passport(_document(data), base_dir=base_dir, paths=paths)


@ext_routes.route("/passport/verify")
def verify(data: dict) -> tuple[int, dict]:
    base_dir, paths = _location_hints(data)
    decoded = decode_passport(_document(data))
    if decoded.value is None:
        return 200, {"verification": None, "diagnostics": [d.to_dict() for d in decoded.diagnostics]}
    return 200, {"verification": verify_passport(decoded.value, base_dir=base_dir, paths=paths),
                 "diagnostics": [d.to_dict() for d in decoded.diagnostics]}
