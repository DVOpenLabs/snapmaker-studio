"""Bed-Fit / Out-of-Bounds Doctor — the #1 cryptic slicer failure, explained.

When a model is too big or badly placed, Snapmaker Orca refuses to slice with a
bare "out of bounds" and no reason — the single most common U1 friction in the
community, usually answered with "ask Facebook". This catches it BEFORE Orca, from
the model's geometry vs the printer's bed, and says exactly what's wrong and how to fix
it: the precise scale-to-fit percentage, a rotate suggestion when the diagonal
fits, a height/split warning, and — in multi-material mode — whether there's room
left for the prime/wipe tower.

Two different questions are answered here and the text always says which one:

    by size       can this object, as modelled, fit the bed at all (per object)
    by placement  do the placed instances sit on the plate (per instance, per plate)

A size says nothing about a position, and a combined extent across several separated
objects or plates is neither: it is never used to say "too big" or to suggest scaling.

Read-only and offline-capable: it uses the connected printer's REAL bed when
known, else the printable volume recorded in the profile of the machine the file
is being prepared for. Honest: it explains only what the geometry proves, returns
unavailable when there are no dimensions, and says which bed it measured against
so a profile figure never reads as a measurement.
"""
from __future__ import annotations

SCHEMA_VERSION = "bedfit/1"

#: The root model part: an object in any other part is named with it.
ROOT_PART = "3D/3dmodel.model"

#: What every size consumer says when per-object sizes are missing.
UNMEASURED_TEXT = "By size, Studio could not measure each object, so it cannot say whether they fit."

# A typical multi-material prime/wipe tower footprint side (mm) — the clearance the
# model must leave on the plate or Orca pushes the tower out of bounds.
PRIME_TOWER_MM = 55.0

# Fraction of the bed above which a footprint is "almost the whole plate" — skirt /
# brim / tower can then spill over the edge even though the part itself fits.
EDGE_FRAC = 0.95


def _f(level: str, text: str) -> dict:
    return {"level": level, "text": text}


def assess(dims, bed=None, bed_known: bool = False, object_count: int = 1,
           multi_material: bool = False, profile: dict | None = None,
           subject: str | None = None, placed: dict | None = None) -> dict:
    """Diagnose whether a model fits the bed and explain any "out of bounds".

    dims: ONE object's size {x, y, z} in mm, as modelled (``geometry.object_sizes``).
        Every statement made from it starts "By size" and claims no position.
    subject: what ``dims`` is the size of, e.g. "object 3" (default "this model").
    placed: a ``plate_placement.assess`` result. When given, where the instances sit
        is reported separately as "By placement", and an instance off the plate makes
        the overall result a risk even though each object is small enough by size.
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
    who = subject or "this model"

    def bump(level: str) -> None:
        nonlocal worst
        order = {"ok": 0, "warn": 1, "risk": 2}
        if order[level] > order[worst]:
            worst = level

    over_x, over_y, over_z = x > bx, y > by, z > bz

    # Too tall — the machine cannot reach the height.
    if over_z:
        bump("risk")
        findings.append(_f("risk", f"By size, {who} is taller than {source} can print: {z:.0f} mm vs the "
                                   f"{bz:.0f} mm max height — Orca reports this as out of bounds. "
                                   f"Scale to {bz / z * 100:.0f}% or split it into shorter parts."))
        fixes.append(f"Scale to {bz / z * 100:.0f}% to fit the height, or split into parts.")

    # Too big in X/Y — the actual "out of bounds" most people hit.
    if over_x or over_y:
        bump("risk")
        # Only divide by dimensions that are positive — a degenerate model can have
        # a zero-width/zero-depth axis (flat plane) which would ZeroDivision here.
        _factors = ([bx / x] if x > 0 else []) + ([by / y] if y > 0 else [])
        scale_pct = (min(_factors) if _factors else 0.0) * 100.0
        findings.append(_f("risk", f"By size, {who} is too big for the bed: {x:.0f}×{y:.0f} mm on a "
                                   f"{bx:.0f}×{by:.0f} mm bed — this is the “out of bounds” error "
                                   f"Orca shows without saying which way. Scale to {scale_pct:.0f}% to fit."))
        fixes.append(f"Scale to {scale_pct:.0f}% so it fits the {bx:.0f}×{by:.0f} mm bed.")
        diag = (x + y) / (2 ** 0.5)
        if (over_x ^ over_y) and diag <= min(bx, by):
            fixes.append(f"Or it may fit rotated ~45° on the plate — the diagonal ({diag:.0f} mm) "
                         f"is within the bed; try Arrange in Orca to confirm.")

    # Almost the whole plate — fits, but brim/skirt/tower can spill over.
    elif x > bx * EDGE_FRAC or y > by * EDGE_FRAC:
        bump("warn")
        findings.append(_f("warn", f"By size, {who} fills almost the whole bed ({x:.0f}×{y:.0f} of "
                                   f"{bx:.0f}×{by:.0f} mm) — a skirt, brim, or prime tower can spill "
                                   f"past the edge and trigger out of bounds."))
        fixes.append("Center the model, drop the brim/skirt, or scale down slightly.")

    # Multi-material: is there room for the prime/wipe tower?
    if multi_material and not (over_x or over_y):
        mx, my = bx - x, by - y
        if mx < PRIME_TOWER_MM or my < PRIME_TOWER_MM:
            bump("warn")
            findings.append(_f("warn", f"By size, {who} leaves little room for the multi-material "
                                       f"prime/wipe tower (~{PRIME_TOWER_MM:.0f} mm, depending on your "
                                       f"Snapmaker Orca tower settings): the bed is only {mx:.0f}×{my:.0f} mm "
                                       f"bigger than it, so the tower may not fit beside it. "
                                       f"This is about size; where the tower lands depends on the arrangement."))
            fixes.append("Shrink the model a little, or reduce/disable the prime tower in Snapmaker Orca.")

    # Multiple parts share the plate — the arrangement must fit, not just one part.
    if object_count and object_count > 1:
        findings.append(_f("ok", f"The project has {object_count} objects. Whatever sits on one plate "
                                 f"must fit that plate together; if Snapmaker Orca still says out of "
                                 f"bounds, one object is off its plate and Arrange can re-pack them."))

    # Where the instances sit is a different fact from how big each object is.
    placed_level = _placed_findings(placed, findings, fixes)
    if placed_level:
        bump(placed_level)

    if worst == "ok" and not any(f["level"] != "ok" for f in findings):
        findings.insert(0, _f("ok", f"By size, {who} fits {source}'s {bx:.0f}×{by:.0f}×{bz:.0f} mm bed "
                                     f"with room to spare ({x:.0f}×{y:.0f}×{z:.0f} mm)."))

    size_level = "risk" if (over_x or over_y or over_z) else (
        "warn" if (x > bx * EDGE_FRAC or y > by * EDGE_FRAC) else "ok")
    checked_placement = bool(placed and placed.get("available"))
    if size_level == "risk":
        overall_text = f"By size, {who} won't fit as-is — this is the out-of-bounds error, with the fix below."
    elif placed_level == "risk":
        overall_text = (f"By size, {who} is small enough for {source}'s bed, but the placement is a "
                        "problem — see the placement finding below.")
    elif size_level == "warn":
        overall_text = "By size, it fits, but the edges are tight — see below before slicing."
    elif worst == "warn":
        overall_text = "By size, it fits, but there is a point to check — see below before slicing."
    elif checked_placement:
        overall_text = f"By size, {who} fits {source}'s bed, and the placement check found nothing off the plate."
    else:
        overall_text = (f"By size, {who} fits {source}'s bed. Where it sits on the plate was not "
                        "checked here.")

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "bed_known": bool(bed_known),
        "bed_source": source,
        "bed_mm_source": "live" if bed_known else "profile",
        "measured_against": printer_profiles.summarise(None if bed_known else profile),
        "bed_mm": {"x": bx, "y": by, "z": bz},
        "dims_mm": {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)},
        "basis": "size_and_placement" if checked_placement else "size",
        "subject": subject,
        "placement_checked": checked_placement,
        "overall_level": worst,
        "overall_text": overall_text,
        "findings": findings,
        "fixes": fixes,
    }


def _placed_findings(placed: dict | None, findings: list, fixes: list) -> str | None:
    """Add the "By placement" statements; returns the level they raised, or None."""
    if not placed or not placed.get("available"):
        return None
    plate_count = placed.get("plate_count") or 1
    if plate_count > 1:
        # Plates share one grid with unrecorded spacing: each plate is judged on whether its own
        # contents fit, never on a combined extent across plates.
        oversized = placed.get("oversized_plates") or []
        if oversized:
            for plate in oversized:
                findings.append(_f("risk", f"By placement, plate {plate['plate']}: {plate['reason']}. "
                                           "Scale it down or split it."))
            fixes.append("Scale the oversized plate down or split it, then use Arrange in Snapmaker Orca.")
            return "risk"
        if placed.get("not_judged"):
            findings.append(_f("warn", f"By placement: {placed.get('summary')}"))
            return "warn"
        findings.append(_f("ok", f"By placement, each of the {plate_count} plates fits on its own. "
                                 "Positions across plates are not checked; use Arrange in Snapmaker Orca."))
        return None
    if not placed.get("off_plate"):
        if placed.get("not_judged"):
            findings.append(_f("warn", f"By placement: {placed.get('summary')}"))
            return "warn"
        findings.append(_f("ok", "By placement, every placed instance sits inside the plate."))
        return None
    findings.append(_f("risk", f"By placement: {placed.get('summary')}"))
    fixes.append("Move the arrangement onto the plate (Studio can save a corrected copy), "
                 "or use Arrange in Snapmaker Orca." if placed.get("fixable") else
                 "Use Arrange in Snapmaker Orca to bring every instance onto the plate.")
    return "risk"


_ORDER = {"ok": 0, "warn": 1, "risk": 2}


def assess_objects(objects: list[dict] | None, placed: dict | None = None, unmeasured: int = 0,
                   **kw) -> dict:
    """Size every object on its own, report the worst, and add the placement separately.

    ``objects`` is ``intelligence.project_info()["object_sizes_mm"]``. The combined extents of
    several objects are never used: a project of small, separated objects is not one big
    object, and "scale to 40%" would shrink all of them for nothing. When no object could be
    measured the answer is UNKNOWN, not a fall-back to the overall extents. Every object is
    checked (there is no cap); ``unmeasured`` says how many build items had no measurable
    object, which keeps the result from claiming that everything fits.
    """
    objects = [o for o in (objects or []) if o.get("dimensions_mm")]
    if not objects:
        return {"schema_version": SCHEMA_VERSION, "available": False, "basis": "size",
                "reason": UNMEASURED_TEXT}
    many = len(objects) > 1

    def label_of(entry):
        if not many or entry.get("object_id") is None:
            return None
        where = entry.get("part")
        return f"object {entry['object_id']}" + (f" in {where}" if where and where != ROOT_PART else "")

    # Size first, object by object and WITHOUT the placement, so a level here is purely about size.
    sized = []
    for entry in objects:
        res = assess(entry["dimensions_mm"], subject=label_of(entry), **kw)
        if not res.get("available"):
            return res
        sized.append((entry, res))
    worst_entry, _ = max(
        sized, key=lambda pair: (_ORDER[pair[1]["overall_level"]],
                                 pair[0]["dimensions_mm"]["x"] * pair[0]["dimensions_mm"]["y"]))
    # Then the one result that is reported, with the placement added once.
    out = assess(worst_entry["dimensions_mm"], placed=placed, subject=label_of(worst_entry), **kw)
    out["objects_checked"] = len(sized)
    out["objects_unmeasured"] = unmeasured
    out["objects_by_size"] = [{"object_id": e.get("object_id"), "level": r["overall_level"],
                               "dims_mm": r["dims_mm"]} for e, r in sized]
    if unmeasured:
        out["findings"].append(_f("warn", f"By size, {unmeasured} build item"
                                          f"{'s' if unmeasured != 1 else ''} could not be measured, so "
                                          "Studio cannot say whether everything fits."))
        if out["overall_level"] != "risk":
            out["overall_level"] = "warn"
            out["overall_text"] = ("By size, it fits as far as Studio could measure, but "
                                   f"{unmeasured} build item{'s' if unmeasured != 1 else ''} could not be "
                                   "measured — see below before slicing.")
    return out
