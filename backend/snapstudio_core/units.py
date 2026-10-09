"""One place that knows what a 3MF `unit` means in millimetres.

A 3MF model part states its unit on the root `model` element; when the attribute is absent the format says
millimetre. Every number in that part (vertex coordinates AND the translation of any transform written in
it) is in that unit. Several Studio readers used to ignore the header, so a 12 inch part was reported as
12 mm. This table and the readers below are the single shared fix: nothing else may keep its own copy of
the factors, and the scene parser calls the SAME ``resolve_unit`` on the SAME root element.

Three outcomes are kept apart on purpose:

* **absent** attribute: the specification default, millimetre (``declared`` is False);
* **recognized** value: one of the six defined units;
* **unrecognized** value: NOT silently the same as absent. ``UnitInfo.recognized`` is False. Legacy
  dimension readers still fall back to millimetres (they always have), the scene reports a limitation
  (``UNSUPPORTED_UNIT``) and withholds fit findings.
"""
from __future__ import annotations

import io
from typing import NamedTuple

from lxml import etree

#: The six units the 3MF core specification defines, in millimetres per unit.
MM_PER_UNIT: dict[str, float] = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}
DEFAULT_UNIT = "millimeter"


class UnitInfo(NamedTuple):
    name: str                 # the declared value, or the default when absent
    factor: float             # millimetres per unit; 1.0 (the documented fallback) when not recognized
    recognized: bool          # False only for a declared value outside the six units
    declared: bool            # False when the attribute is absent (the default applies)


def resolve_unit(value: str | None) -> UnitInfo:
    """Interpret the root element's ``unit`` attribute value (None = absent)."""
    if value is None:
        return UnitInfo(DEFAULT_UNIT, MM_PER_UNIT[DEFAULT_UNIT], True, False)
    factor = MM_PER_UNIT.get(value)
    if factor is None:
        return UnitInfo(value, 1.0, False, True)
    return UnitInfo(value, factor, True, True)


def read_unit(raw: bytes | str) -> UnitInfo:
    """The unit declared by the REAL root element of a model part, read with the XML parser.

    Only the first start event is consumed, so comments, processing instructions, a DOCTYPE-free prolog
    and a long preamble are all irrelevant, and a ``<model unit=...>`` inside a comment is not seen. A part
    that cannot be parsed, or whose root is not ``model``, is NOT a legitimately absent attribute: it reads
    as ``recognized=False`` (millimetre factor for the legacy readers, with the flag set); entities are never
    resolved and the network is never touched.
    """
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    unreadable = UnitInfo(DEFAULT_UNIT, MM_PER_UNIT[DEFAULT_UNIT], False, False)
    try:
        for _event, elem in etree.iterparse(io.BytesIO(data), events=("start",), resolve_entities=False,
                                            load_dtd=False, no_network=True, huge_tree=False):
            if etree.QName(elem).localname != "model":
                return unreadable
            return resolve_unit(elem.get("unit"))
    except (etree.LxmlError, ValueError):
        pass
    return unreadable


def unit_of(raw: bytes | str) -> tuple[str | None, float | None]:
    """``(name, mm_per_unit)``; the factor is None for an unrecognized value."""
    info = read_unit(raw)
    return info.name, (info.factor if info.recognized else None)


def mm_per_unit(raw: bytes | str) -> float:
    """Millimetres per unit for a model part; an unrecognized unit reads as millimetres (see UnitInfo)."""
    return read_unit(raw).factor


def scale_translation(transform, factor: float):
    """A 3MF transform with its translation moved into millimetres (or back, with ``1/factor``).

    Accepts the 12-number list form (translation = entries 9..11) and the parsed row form
    ``((a,b,c),(d,e,f),(g,h,i),(tx,ty,tz))``. Only the translation carries a length; the 3x3 part is
    dimensionless. Factor 1.0 returns the input unchanged, so millimetre behaviour is exactly as before.
    """
    if transform is None or factor == 1.0:
        return transform
    if isinstance(transform[0], (tuple, list)):
        tx, ty, tz = transform[3]
        return (transform[0], transform[1], transform[2], (tx * factor, ty * factor, tz * factor))
    out = list(transform)
    out[9] *= factor
    out[10] *= factor
    out[11] *= factor
    return out
