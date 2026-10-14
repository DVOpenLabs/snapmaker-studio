"""Where the prime (wipe) tower sits, judged against the printable area.

Detection only. Studio does not move the tower. A project made for a printer with
a larger bed keeps that bed's tower position, and Snapmaker Orca can refuse to slice
a plate whose tower reaches past the U1's printable area ("a G-code path goes beyond
plate boundaries"). Whether it does is computed here from the project's own
settings, never asserted.

`wipe_tower_x` / `wipe_tower_y` are plate-local lists; a plate with no entry of its
own uses the first one. Only what is certain is claimed: the tower starts at (x, y)
and is at least `prime_tower_width` wide.

Why only "at least": in Snapmaker Orca 2.4.0 (Print.cpp, `wipe_tower_data().depth`) the
tower's depth comes from the tool changes and flush volumes of the sliced print, and
its brim, cone base and `wipe_tower_rotation_angle` add to the footprint. None of
that is in the file. So Studio can prove a tower is *outside* (its start point or
minimum width already is), but it can never prove one is *inside*; a tower that is
not reported is "not verified", not "fine". A rotated tower is not judged at all.
"""
from __future__ import annotations


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


def findings(cfg: dict, plate_count: int, bed: dict) -> list[dict]:
    """Towers (one per plate) that start or extend outside `bed`."""
    cfg = cfg or {}
    if _off(cfg.get("enable_prime_tower")):
        return []
    if (_num(cfg.get("wipe_tower_rotation_angle"), 0.0) or 0.0) != 0.0:
        return []   # the footprint is rotated; its corners are not known from the file
    xs, ys = cfg.get("wipe_tower_x"), cfg.get("wipe_tower_y")
    xs = xs if isinstance(xs, list) else ([xs] if xs is not None else [])
    ys = ys if isinstance(ys, list) else ([ys] if ys is not None else [])
    if not xs or not ys:
        return []
    width = _num(cfg.get("prime_tower_width"), 0.0) or 0.0
    out = []
    for i in range(max(int(plate_count or 1), len(xs), len(ys))):
        x = _num(xs[min(i, len(xs) - 1)])
        y = _num(ys[min(i, len(ys) - 1)])
        if x is None or y is None:
            continue
        if (x < bed["min_x"] or x + width > bed["max_x"]
                or y < bed["min_y"] or y > bed["max_y"]):
            out.append({"plate": i + 1, "x": x, "y": y, "width": width})
    return out


def message(found: list[dict], bed: dict, whose: str = "the U1's") -> str | None:
    if not found:
        return None
    plates = ", ".join(str(f["plate"]) for f in found)
    first = found[0]
    label = f"plate {plates}" if len(found) == 1 else f"plates {plates}"
    return (f"The prime tower ({label}) sits outside {whose} printable area: it starts at "
            f"X {first['x']:g}, Y {first['y']:g} and is at least {first['width']:g} mm wide "
            f"(its depth is only known when Orca slices), "
            f"while the area is X {bed['min_x']:g} to {bed['max_x']:g}, "
            f"Y {bed['min_y']:g} to {bed['max_y']:g} mm. Snapmaker Orca can refuse to slice "
            "that plate until the tower is moved.")


UNVERIFIED_NOTE = (
    "Studio could not verify how far the prime tower reaches: its depth, brim and rotation "
    "are only known when Snapmaker Orca slices. Check the tower in Orca's preview."
)


def unverified_note(cfg: dict, found: list[dict]) -> str | None:
    """Informational: a tower exists in the settings and none was proven outside."""
    cfg = cfg or {}
    if found or _off(cfg.get("enable_prime_tower")):
        return None
    if cfg.get("wipe_tower_x") in (None, [], "") or cfg.get("wipe_tower_y") in (None, [], ""):
        return None
    return UNVERIFIED_NOTE
