"""Bed-Fit / Out-of-Bounds Doctor — the #1 cryptic slicer failure, explained.

When a model is too big or badly placed, Snapmaker Orca refuses to slice with a
bare "out of bounds" and no reason — the single most common U1 friction in the
community, usually answered with "ask Facebook". This catches it BEFORE Orca, from
the model's geometry vs the printer's bed, and says exactly what's wrong and how to fix
it: the precise scale-to-fit percentage, a rotate suggestion when the diagonal
fits, a height/split warning, and — in multi-material mode — whether there's room
left for the prime/wipe tower.

Read-only and offline-capable: it uses the connected printer's REAL bed when
known, else the printable volume recorded in the profile of the machine the file
is being prepared for. Honest: it explains only what the geometry proves, returns
unavailable when there are no dimensions, and says which bed it measured against
so a profile figure never reads as a measurement.
"""
from __future__ import annotations

SCHEMA_VERSION = "bedfit/1"

# A typical multi-material prime/wipe tower footprint side (mm) — the clearance the
# model must leave on the plate or Orca pushes the tower out of bounds.
PRIME_TOWER_MM = 55.0

# Fraction of the bed above which a footprint is "almost the whole plate" — skirt /
# brim / tower can then spill over the edge even though the part itself fits.
EDGE_FRAC = 0.95


def _f(level: str, text: str, id: str | None = None, action: str | None = None) -> dict:
    out = {"level": level, "text": text}
    if id:
        out["id"] = id         # the stable condition id (snapstudio_core.conditions)
    if action:
        out["action"] = action  # the step that belongs to THIS finding
    return out


def assess(dims, bed=None, bed_known: bool = False, object_count: int = 1,
           multi_material: bool = False, profile: dict | None = None) -> dict:
    """Diagnose whether a model fits the bed and explain any "out of bounds".

    dims: object bounding box {x, y, z} in mm (from geometry).
    bed:  the printer's real bed {x, y, z}; falls back to the profile's volume.
    bed_known: True when `bed` came from a connected printer.
    object_count: parts on the plate (the whole arrangement must fit).
    multi_material: reserve prime/wipe-tower clearance when True.
    profile: the printer profile to fall back on. Defaults to the machine Studio
        prepares copies for.
    """
    from . import printer_profiles

    profile = profile or printer_profiles.prepare_target()
    if not dims or any(dims.get(k) is None for k in ("x", "y", "z")):
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": "no model dimensions available to check against the bed"}

    x, y, z = float(dims["x"]), float(dims["y"]), float(dims["z"])
    fallback = profile.get("build_volume_mm") or {"x": 0.0, "y": 0.0, "z": 0.0}
    b = bed if (bed and all(bed.get(k) for k in ("x", "y", "z"))) else fallback
    if not all(b.get(k) for k in ("x", "y", "z")):
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": ("no bed size to check against — no printer answered and the "
                           f"{printer_profiles.display_name(profile)} profile records no "
                           "build volume")}
    bx, by, bz = float(b["x"]), float(b["y"]), float(b["z"])
    name = printer_profiles.display_name(profile)
    source = "your connected printer" if bed_known else f"the {name}"

    findings: list[dict] = []
    fixes: list[str] = []
    worst = "ok"

    def bump(level: str) -> None:
        nonlocal worst
        order = {"ok": 0, "warn": 1, "risk": 2}
        if order[level] > order[worst]:
            worst = level

    over_x, over_y, over_z = x > bx, y > by, z > bz

    # Too tall — the machine cannot reach the height.
    if over_z:
        bump("risk")
        findings.append(_f("risk", f"Taller than {source} can print: {z:.0f} mm vs the "
                                   f"{bz:.0f} mm max height — Orca reports this as out of bounds. "
                                   f"Scale to {bz / z * 100:.0f}% or split it into shorter parts.",
                               id="bed-height", action=f"Scale to {bz / z * 100:.0f}% to fit the height, or split into parts."))
        fixes.append(f"Scale to {bz / z * 100:.0f}% to fit the height, or split into parts.")

    # Too big in X/Y — the actual "out of bounds" most people hit.
    if over_x or over_y:
        bump("risk")
        # Only divide by dimensions that are positive — a degenerate model can have
        # a zero-width/zero-depth axis (flat plane) which would ZeroDivision here.
        _factors = ([bx / x] if x > 0 else []) + ([by / y] if y > 0 else [])
        scale_pct = (min(_factors) if _factors else 0.0) * 100.0
        findings.append(_f("risk", f"Too big for the bed: {x:.0f}×{y:.0f} mm on a "
                                   f"{bx:.0f}×{by:.0f} mm bed — this is the “out of bounds” error "
                                   f"Orca shows without saying which way. Scale to {scale_pct:.0f}% to fit.",
                               id="bed-footprint", action=f"Scale to {scale_pct:.0f}% so it fits the {bx:.0f}×{by:.0f} mm bed."))
        fixes.append(f"Scale to {scale_pct:.0f}% so it fits the {bx:.0f}×{by:.0f} mm bed.")
        diag = (x + y) / (2 ** 0.5)
        if (over_x ^ over_y) and diag <= min(bx, by):
            fixes.append(f"Or it may fit rotated ~45° on the plate — the diagonal ({diag:.0f} mm) "
                         f"is within the bed; try Arrange in Orca to confirm.")

    # Almost the whole plate — fits, but brim/skirt/tower can spill over.
    elif x > bx * EDGE_FRAC or y > by * EDGE_FRAC:
        bump("warn")
        findings.append(_f("warn", f"Fills almost the whole bed ({x:.0f}×{y:.0f} of "
                                   f"{bx:.0f}×{by:.0f} mm) — a skirt, brim, or prime tower can spill "
                                   f"past the edge and trigger out of bounds.",
                               id="bed-near-full", action="Center the model, drop the brim/skirt, or scale down slightly."))
        fixes.append("Center the model, drop the brim/skirt, or scale down slightly.")

    # Multi-material: is there room for the prime/wipe tower?
    if multi_material and not (over_x or over_y):
        mx, my = bx - x, by - y
        if mx < PRIME_TOWER_MM or my < PRIME_TOWER_MM:
            bump("warn")
            findings.append(_f("warn", f"Little room for the multi-material prime/wipe tower "
                                       f"(~{PRIME_TOWER_MM:.0f} mm, depending on your Orca tower settings): "
                                       f"only {mx:.0f}×{my:.0f} mm is free beside the model, so Orca may push "
                                       f"the tower off the bed (out of bounds).",
                                   id="bed-prime-tower-room", action="Shrink the model a little, or reduce/disable the prime tower in Orca."))
            fixes.append("Shrink the model a little, or reduce/disable the prime tower in Orca.")

    # Multiple parts share the plate — the arrangement must fit, not just one part.
    if object_count and object_count > 1:
        findings.append(_f("ok", f"{object_count} objects share the plate — the whole "
                                 f"arrangement must fit. If Orca still says out of bounds, one object "
                                 f"is off the plate; use Arrange to re-pack them."))

    if worst == "ok" and not any(f["level"] != "ok" for f in findings):
        findings.insert(0, _f("ok", f"Fits {source}'s {bx:.0f}×{by:.0f}×{bz:.0f} mm bed "
                                     f"with room to spare ({x:.0f}×{y:.0f}×{z:.0f} mm)."))

    overall_text = {
        "ok": f"This model fits {source}'s bed.",
        "warn": "It fits, but the edges are tight — see below before slicing.",
        "risk": "It won't fit as-is — this is the out-of-bounds error, with the fix below.",
    }[worst]

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "bed_known": bool(bed_known),
        "bed_source": source,
        "bed_mm_source": "live" if bed_known else "profile",
        "measured_against": printer_profiles.summarise(None if bed_known else profile),
        "bed_mm": {"x": bx, "y": by, "z": bz},
        "dims_mm": {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)},
        "overall_level": worst,
        "overall_text": overall_text,
        "findings": findings,
        "fixes": fixes,
    }
