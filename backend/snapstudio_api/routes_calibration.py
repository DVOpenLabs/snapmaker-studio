"""Palette calibration routes. All work is local parsing, comparison and persistence."""
from __future__ import annotations

import re

from snapstudio_core import paths
from snapstudio_core.calibration import palette as palette_reader
from snapstudio_core.calibration import service
from snapstudio_core.foundation.decode import Decoded

from . import ext_routes
from . import request_validation as rv

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _decoded_dict(decoded: Decoded) -> dict:
    return decoded.to_dict()


def _colors(data: dict) -> dict[str, str]:
    raw = data.get("physical_colors", {})
    if not isinstance(raw, dict) or len(raw) > 256:
        raise rv.ValidationError("Invalid 'physical_colors'")
    result = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, str) or not _COLOR.fullmatch(value):
            raise rv.ValidationError("Invalid 'physical_colors'")
        result[str(key)] = value.upper()
    return result


def _owned(data: dict) -> list[dict]:
    rows = data.get("owned_filaments", [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise rv.ValidationError("Invalid 'owned_filaments'")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise rv.ValidationError("Invalid 'owned_filaments'")
        color = row.get("color")
        label = row.get("label", "Owned filament")
        if not isinstance(color, str) or not _COLOR.fullmatch(color) or not isinstance(label, str) or len(label) > 80:
            raise rv.ValidationError("Invalid 'owned_filaments'")
        result.append({"color": color.upper(), "label": label})
    return result


@ext_routes.route("/calibration/evaluate")
def evaluate(data: dict) -> tuple[int, dict]:
    source = data.get("source")
    if source not in ("ditherforge_txt", "kromacut_json"):
        raise rv.ValidationError("Invalid 'source'")
    content = data.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 512_000:
        raise rv.ValidationError("Invalid 'content'")
    decoded = palette_reader.parse_palette(source, content)
    if decoded.value is None:
        return 200, {"status": "unknown", "decoded": _decoded_dict(decoded), "result": None}
    family = data.get("family")
    if family not in ("frontlit", "backlit"):
        raise rv.ValidationError("Invalid 'family'")
    basis = service.basis_document(family, rv.require_positive_float(data, "layer_height_mm"),
                                   rv.optional_positive_float(data, "nozzle_mm", 0.4),
                                   rv.optional_bounded_str(data, "material", 32) or "PLA")
    palette = decoded.value.to_dict()
    result = service.evaluate(palette, basis, _colors(data), _owned(data))
    saved = service.save_run(basis, palette, result, data_dir=paths.data_dir())
    return 200, {"status": "evaluated", "decoded": _decoded_dict(decoded), "result": saved}


@ext_routes.route("/calibration/history")
def get_history(data: dict) -> tuple[int, dict]:
    return 200, {"runs": service.history(data_dir=paths.data_dir())}
