"""Where the prime (wipe) tower sits, judged against the printable area.

Detection only. Studio does not move the tower. A project made for a printer with
a larger bed keeps that bed's tower position, and Snapmaker Orca can refuse to slice
a plate whose tower reaches past the U1's printable area ("a G-code path goes beyond
plate boundaries"). Whether it does is computed here from the project's own
settings, never asserted.

`wipe_tower_x` / `wipe_tower_y` are plate-local lists; a plate with no entry of its
own uses the first one. Only what is certain is claimed: the tower starts at (x, y)
and is at least `prime_tower_width` wide. Its depth is not known from the file, so
the y axis is judged on the start point only.
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
            f"X {first['x']:g}, Y {first['y']:g} and is at least {first['width']:g} mm wide, "
            f"while the area is X {bed['min_x']:g} to {bed['max_x']:g}, "
            f"Y {bed['min_y']:g} to {bed['max_y']:g} mm. Snapmaker Orca can refuse to slice "
            "that plate until the tower is moved.")
