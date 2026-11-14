"""Palette decoding for DitherForge TXT and Kromacut palette JSON v2."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from snapstudio_core.foundation.decode import Decoded, Diagnostic, ERROR, decode_document, diag, parse_json

_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")
_DITHER = re.compile(r"^\s*#?([0-9a-fA-F]{6})(?:\s+(.*?))?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PaletteEntry:
    label: str
    color: str
    td: float
    td_provenance: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"label": self.label, "color": self.color, "td": self.td,
                "td_provenance": self.td_provenance, "enabled": self.enabled}


@dataclass
class Palette:
    source: str
    entries: list[PaletteEntry]

    def to_dict(self) -> dict:
        return {"schema_version": "calibration_palette/1", "source": self.source,
                "entries": [entry.to_dict() for entry in self.entries]}


def _color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _COLOR.fullmatch(value.strip())
    return f"#{match.group(1).upper()}" if match else None


def parse_ditherforge(text: str) -> Decoded[Palette]:
    """Parse documented DitherForge rows; unmeasured TD is explicitly derived."""
    if not isinstance(text, str):
        return Decoded(None, None, [diag("wrong_type", "text", ERROR)], False)
    entries: list[PaletteEntry] = []
    diagnostics: list[Diagnostic] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("//") or stripped.startswith("# "):
            continue
        match = _DITHER.match(stripped)
        if not match:
            diagnostics.append(diag("invalid_palette_line", f"line:{number}", ERROR))
            continue
        color, remainder = match.groups()
        remainder = remainder or ""
        assignments = list(re.finditer(r"\btd\s*=\s*(\S*)", remainder, re.IGNORECASE))
        values = [item.group(1) for item in assignments]
        label = re.sub(r"\btd\s*=\s*\S*", "", remainder, flags=re.IGNORECASE).strip()
        leading_td = re.match(r"^td(?:\s+([0-9.eE+-]+))?(?:\s+|$)(.*)$", label, re.IGNORECASE)
        numeric = re.match(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+|$)(.*)$", label)
        if leading_td:
            if leading_td.group(1) is not None:
                values.append(leading_td.group(1))
            label = leading_td.group(2)
        elif numeric:
            values.append(numeric.group(1))
            label = numeric.group(2)
        try:
            numbers = [float(value) for value in values]
        except ValueError:
            numbers = [float("nan")]
        if len(assignments) > 1 or any(not (0 < value < float("inf")) for value in numbers) or len(set(numbers)) > 1:
            diagnostics.append(diag("invalid_or_conflicting_td", f"line:{number}", ERROR))
            continue
        td = numbers[0] if numbers else 1.0
        td_text = values[0] if values else None
        entries.append(PaletteEntry((label or f"Color {len(entries) + 1}").strip(),
                                    f"#{color.upper()}", td,
                                    "provided" if td_text is not None else "derived"))
    if not entries and not diagnostics:
        diagnostics.append(diag("empty_palette", "", ERROR))
    value = Palette("ditherforge_txt", entries) if not any(d.severity == ERROR for d in diagnostics) else None
    return Decoded("calibration_palette/1", value, diagnostics, value is not None,
                   raw=None if value else text)


def _build_kromacut(reader) -> Palette:
    # Kromacut v2 exports parallel arrays in a .kpal JSON object. Keep every
    # original index, including disabled colours, so readings cannot shift rows.
    if "colors" in reader.raw:
        colors = reader.raw["colors"]
        names = reader.raw.get("colorNames", [])
        disabled = reader.raw.get("disabledColors", [])
        if not isinstance(colors, list) or not colors or len(colors) > 256:
            reader.error("invalid_colors", "colors")
            return Palette("kromacut_json_v2", [])
        if not isinstance(names, list) or len(names) > len(colors) or any(not isinstance(n, str) or len(n) > 256 for n in names):
            reader.error("invalid_color_names", "colorNames")
            return Palette("kromacut_json_v2", [])
        if not isinstance(disabled, list) or any(type(i) is not int or not 0 <= i < len(colors) for i in disabled):
            reader.error("invalid_disabled_colors", "disabledColors")
            return Palette("kromacut_json_v2", [])
        entries = []
        for index, raw_color in enumerate(colors):
            color = _color(raw_color)
            if color is None:
                reader.error("invalid_color", f"colors[{index}]")
                continue
            label = names[index].strip() if index < len(names) else ""
            entries.append(PaletteEntry(label or f"Color {index + 1}", color, 1.0, "derived", index not in disabled))
        return Palette("kromacut_json_v2", entries)
    # Retain the earlier Studio row representation for saved fixtures.
    rows = reader.items("palette", required=True)
    if not rows:
        reader.error("empty_palette", "palette")
    entries: list[PaletteEntry] = []
    for index, row in enumerate(rows):
        item = reader.child(row, f"palette[{index}]")
        color = _color(item.raw.get("color", item.raw.get("hex")))
        if color is None:
            item.error("invalid_color", "color")
            continue
        label = item.string("label", required=False, default=None) or f"Color {index + 1}"
        td_value = item.raw.get("td")
        if td_value is None:
            td = 1.0
            provenance = "derived"
        elif isinstance(td_value, bool) or not isinstance(td_value, (int, float)) or not (0 < td_value < float("inf")):
            item.error("invalid_td", "td")
            continue
        else:
            td = float(td_value)
            provenance = "provided"
        entries.append(PaletteEntry(label, color, td, provenance))
    return Palette("kromacut_json_v2", entries)


def parse_kromacut(raw: Any) -> Decoded[Palette]:
    """Decode version 2 only; preserve unsupported input without evaluating it."""
    parsed = parse_json(raw) if isinstance(raw, (str, bytes, bytearray)) else None
    if parsed is not None:
        if parsed.value is None:
            return Decoded(None, None, parsed.diagnostics, False, raw=parsed.raw)
        raw = parsed.value
    if not isinstance(raw, dict):
        return Decoded(None, None, [diag("not_an_object", "", ERROR)], False, raw=raw)
    version = raw.get("version", raw.get("schema_version"))
    if version not in (2, "2", "kromacut_palette/2"):
        return Decoded(str(version) if version is not None else None, None,
                       [diag("unknown_schema_version" if version is not None else "missing_schema_version",
                             "version", ERROR)], False, raw=raw)
    normalized = {**raw, "schema_version": "kromacut_palette/2"}
    if "palette" not in normalized and isinstance(normalized.get("entries"), list):
        normalized["palette"] = normalized["entries"]
    return decode_document(normalized, "kromacut_palette/2", _build_kromacut)


def parse_palette(source: str, content: str) -> Decoded[Palette]:
    if source == "ditherforge_txt":
        return parse_ditherforge(content)
    if source == "kromacut_json":
        return parse_kromacut(content)
    return Decoded(None, None, [diag("unknown_palette_source", "source", ERROR)], False)
