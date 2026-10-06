"""The list of spools a person picks from, in one deterministic order.

A provider answers with whatever order it keeps spools in. A person with a hundred
spools needs the list sorted the same way every time and each spool described well
enough to tell two similar ones apart: who made it, what it is, what colour (in words,
not only a swatch), and which spool it is in the provider.

Read-only. Nothing here talks to a provider; it only shapes what one already returned.
"""
from __future__ import annotations

import colorsys
import re

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")


def color_name(value: str | None) -> str | None:
    """A plain-English name for a hex colour, or None when it cannot be read.

    Same bands as the app's own colour naming, so a colour is called the same thing in
    the Plate Remap page and in the spool list.
    """
    m = _HEX.match((value or "").strip())
    if not m:
        return None
    raw = m.group(1)
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h *= 360
    if l >= 0.92 and s < 0.1:
        return "white"
    if l <= 0.12:
        return "black"
    if s < 0.12:
        return "light gray" if l > 0.6 else "gray"
    if h < 15 or h >= 345:
        return "red"
    if h < 45:
        return "orange"
    if h < 65:
        return "gold/yellow"
    if h < 160:
        return "green"
    if h < 200:
        return "light blue" if l > 0.6 else "teal"
    if h < 255:
        return "blue"
    if h < 290:
        return "purple"
    return "pink"


def _text(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _id_key(value) -> tuple:
    """Ids that are numbers sort as numbers (124 before 1000); anything else as text."""
    s = str(value)
    return (0, int(s), "") if s.isdigit() else (1, 0, s.casefold())


def _text_key(value: str | None) -> tuple:
    # A spool that does not say sorts after one that does, never before.
    return (value is None, (value or "").casefold())


def sort_key(choice: dict) -> tuple:
    """vendor, then material family, then subtype, then colour, then the provider's id."""
    return (
        _text_key(choice.get("vendor")),
        _text_key(choice.get("material")),
        _text_key(choice.get("subtype")),
        _text_key(choice.get("color_name")),
        _text_key(choice.get("color")),
        _id_key(choice.get("id")),
    )


def _label(vendor, material, subtype, name, spool_id) -> str:
    material_text = " ".join(x for x in (material, subtype) if x)
    parts = [x for x in (vendor, name or material_text) if x]
    return " ".join(parts) or f"spool {spool_id}"


def build(spools: list[dict], source: str) -> list[dict]:
    """The pickable form of a provider's spools: identity fields, sorted."""
    out = []
    for s in spools:
        vendor = _text(s.get("vendor"))
        material = _text(s.get("material"))
        subtype = _text(s.get("subtype"))
        name = _text(s.get("name"))
        colour = _text(s.get("color"))
        provided = _text(s.get("color_name"))
        out.append({
            "id": s.get("id"),
            "label": _label(vendor, material, subtype, name, s.get("id")),
            "vendor": vendor,
            "material": material,
            "subtype": subtype,
            "color": colour,
            # What the provider calls the colour when it says; otherwise what the colour looks like.
            "color_name": provided or color_name(colour),
            "slicer_filament": _text(s.get("slicer_filament")),
            "source": source,
            "remaining_g": s.get("remaining_g"),
            "remaining_quality": s.get("remaining_quality"),
            "archived": bool(s.get("archived")),
        })
    out.sort(key=sort_key)
    return out
