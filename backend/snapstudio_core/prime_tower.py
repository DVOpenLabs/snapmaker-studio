"""Where the prime (wipe) tower sits, judged against the printable area.

Detection only. Studio never moves the tower. A project made for a printer with a
larger bed keeps that bed's tower position, and Snapmaker Orca can refuse to slice a
plate whose tower reaches past the U1's printable area ("a G-code path goes beyond
plate boundaries"). Whether it does is computed here from the project's own
settings, never asserted.

This module is the single place the tower is judged: ``regrid`` (Prepare) and the
placement check both call ``assess``, so they cannot disagree.

What the file proves, and nothing more
--------------------------------------
``wipe_tower_x`` / ``wipe_tower_y`` are plate-local lists; a plate with no entry of its
own uses the FIRST entry (Orca's ``get_at``), never the last. They are the tower's
start corner, which is part of its footprint. So:

* ``outside_proven``: the start corner itself lies outside the printable area.
* ``unknown``: everything else. The tower's depth comes from the tool changes and
  flush volumes of the sliced print; its wall type (rectangle, cone, rib), brim and
  ``wipe_tower_rotation_angle`` all change the footprint, and none of that is in the
  file. ``prime_tower_width`` is NOT used as an extent and no depth is ever inferred
  from it: the width is a nominal setting whose meaning differs by wall type.

A tower is never proven *inside*, never "clear" of objects, and its clearances are
never estimated. A rotated tower is not judged at all. Unresolved cases need review
in Snapmaker Orca.
"""
from __future__ import annotations

OUTSIDE = "outside_proven"
UNKNOWN = "unknown"


def _num(value, default=None):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _off(value) -> bool:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value).strip().lower() in ("0", "false")


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [] if value in (None, "") else [value]


def _entry(values, plate: int):
    """The plate's own entry, else the first one (Orca's ``get_at``)."""
    values = _as_list(values)
    if not values:
        return None
    return _num(values[plate] if plate < len(values) else values[0])


def enabled(cfg: dict) -> bool:
    """False only when the project switches the tower off. An absent key is not "off"."""
    return not _off((cfg or {}).get("enable_prime_tower"))


def _stated_on(cfg: dict) -> bool:
    """The project explicitly says the tower is on (a missing key proves nothing)."""
    value = (cfg or {}).get("enable_prime_tower")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None or str(value).strip().lower() in ("", "none", "nil"):
        return False
    return enabled(cfg)


def assess(cfg: dict, plate_count: int, bed: dict) -> list[dict]:
    """One record per plate: ``plate`` (1-based), ``x``, ``y``, ``status``, ``reason``.

    Empty when there is no enabled tower or the project states no position at all.
    """
    cfg = cfg or {}
    if not enabled(cfg):
        return []
    xs, ys = _as_list(cfg.get("wipe_tower_x")), _as_list(cfg.get("wipe_tower_y"))
    if not xs or not ys:
        return []
    rotated = (_num(cfg.get("wipe_tower_rotation_angle"), 0.0) or 0.0) != 0.0
    out = []
    for i in range(max(int(plate_count or 1), 1)):
        x, y = _entry(xs, i), _entry(ys, i)
        record = {"plate": i + 1, "x": x, "y": y, "status": UNKNOWN, "reason": None}
        if x is None or y is None:
            record["reason"] = "the project states no usable tower position for this plate"
        elif rotated:
            record["reason"] = "the tower is rotated, so its corners are not known from the file"
        elif not _stated_on(cfg):
            record["reason"] = "the project does not state that the prime tower is enabled"
        elif x < bed["min_x"] or x > bed["max_x"] or y < bed["min_y"] or y > bed["max_y"]:
            record.update(status=OUTSIDE,
                          reason="its start corner already lies outside the printable area")
        else:
            record["reason"] = ("how far the tower reaches is decided when Snapmaker Orca "
                                "plans the tool changes, so it is not known whether it fits")
        out.append(record)
    return out


def findings(cfg: dict, plate_count: int, bed: dict) -> list[dict]:
    """Towers (one per plate) proven to start outside `bed`."""
    return [r for r in assess(cfg, plate_count, bed) if r["status"] == OUTSIDE]


def message(found: list[dict], bed: dict, whose: str = "the U1's") -> str | None:
    if not found:
        return None
    plates = ", ".join(str(f["plate"]) for f in found)
    first = found[0]
    label = f"plate {plates}" if len(found) == 1 else f"plates {plates}"
    return (f"The prime tower ({label}) sits outside {whose} printable area: it starts at "
            f"X {first['x']:g}, Y {first['y']:g}, while the area is X {bed['min_x']:g} to "
            f"{bed['max_x']:g}, Y {bed['min_y']:g} to {bed['max_y']:g} mm. Snapmaker Orca can "
            "refuse to slice that plate until the tower is moved. Studio left it where it is; "
            "review it in Snapmaker Orca.")


UNVERIFIED_NOTE = (
    "Studio could not verify how far the prime tower reaches: its depth, wall type, brim "
    "and rotation are only known when Snapmaker Orca slices. Check the tower in Orca's preview."
)


def unverified_note(cfg: dict, found: list[dict]) -> str | None:
    """Informational: a tower exists in the settings and none was proven outside."""
    cfg = cfg or {}
    if found or not enabled(cfg):
        return None
    if not _as_list(cfg.get("wipe_tower_x")) or not _as_list(cfg.get("wipe_tower_y")):
        return None
    return UNVERIFIED_NOTE
