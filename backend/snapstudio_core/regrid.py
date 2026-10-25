"""Prepare-time layout correction: the plate grid and the prime tower.

A multi-plate project from another printer carries its build items on THAT printer's plate grid. Snapmaker
Orca rebuilds plate membership from geometry when it opens a file, so an item that is not inside the U1's
cell for its plate is listed under *Outside* and the plate will not slice. The same project carries a prime
(wipe) tower position written for the source bed, which can lie outside the U1 plate or on top of a model.

Both are corrected here, in BOTH prepare modes (where things sit is not a creator's setting), by
translating build items and moving a tower. Nothing else changes: not a mesh, not a paint attribute, not a
part transform, not a rotation or scale token.

The grid rule (Orca 2.4.0 ``PartPlate.cpp``; confirmed on 24 of 24 build items of the four multi-plate
benchmark projects, and by the creator's own Orca-made U1 file):

    stride_x = int(bed width)  * 1.2          stride_y = int(bed depth) * 1.2
    cols     = compute_colum_count(plates)    origin(i) = ((i % cols) * stride_x, -(i // cols) * stride_y)

An item's position is that origin plus its position in the bed's own frame. The rule is only used when it
can be cross-checked: every build item's whole bounding box must sit inside the cell the project's own plate
record names for it. If any item fails that check, or its plate cannot be established, nothing is moved and
the condition is reported as unresolved. Studio never guesses a grid.

The tower is NOT moved. Its footprint is not in the project: the depth of a prime tower is decided by
Snapmaker Orca when it plans the tool changes (purge volumes, ribs, brim, clearance). From the file Studio
knows the corner, the width and the brim, which is enough to PROVE a tower is outside the printable area (its
corner or its known width leaves it) or MAY sit on an object (its corner is inside an object's bounding box,
which an L-shaped or ring-shaped object can contain without being under it), and never enough to say it is
inside or clear. So each plate's tower is reported as ``outside_proven``, ``overlap_possible`` or ``unknown``,
with the known extents and, clearly marked as an estimate, a square of the tower's width and its clearances.
``wipe_tower_x/y`` are never changed, except that a project already authored on this very U1 plate keeps its
creator's tower position. Nothing here claims a tower is safe.
"""
from __future__ import annotations

import copy
import math
import re

from . import geometry, placement, plate_placement as pp

#: Orca's ``LOGICAL_PART_PLATE_GAP``: the stride is the plate size times (1 + gap).
PLATE_GAP = 1.0 / 5.0

#: The tower's depth is not stored in the project. ONLY the estimate shown next to a tower uses it
#: (a square of its width); no decision is taken from it.
TOWER_DEPTH_FROM_WIDTH = 1.0

_TOLERANCE = 1e-6


# --- Orca's plate grid ---------------------------------------------------------------------------

def column_count(plates: int) -> int:
    """``compute_colum_count`` from Orca's ``PartPlate.hpp``: the grid is as square as it can be."""
    value = math.sqrt(float(plates))
    rounded = round(value)
    return int(rounded + 1) if value > rounded else int(rounded)


def stride_of(polygon: list[tuple] | None):
    """``(stride_x, stride_y, (min_x, min_y, max_x, max_y))`` of a bed polygon, or None.

    Orca keeps the plate size as an integer (``m_plate_width``/``m_plate_depth``), so the size is
    truncated before the gap is applied."""
    if not polygon or len(polygon) < 3:
        return None
    left, front, right, back = placement.bounds_of(polygon)
    width, depth = int(right - left), int(back - front)
    if width <= 0 or depth <= 0:
        return None
    return width * (1.0 + PLATE_GAP), depth * (1.0 + PLATE_GAP), (left, front, right, back)


def origin(index: int, cols: int, stride: tuple) -> tuple[float, float]:
    """Where plate ``index`` (0-based) starts on the grid: columns go right, rows go to NEGATIVE Y."""
    return (index % cols) * stride[0], -(index // cols) * stride[1]


# --- the correction ------------------------------------------------------------------------------

def correct(tm, work: dict, source_cfg: dict, source_path: str) -> dict:
    """Re-grid the plates and place the prime tower, on ``tm`` (build items) and ``work`` (tower keys).

    Returns the report (``status``, per-plate cells and deltas, the formula check, the tower decisions,
    ``setting_changes`` for the keys it wrote and ``disclosure`` for people). Never raises: whatever it
    cannot establish is reported as unresolved and left as it was.
    """
    report: dict = {"status": "not_applicable", "plates": [], "formula_check": None, "tower": [],
                    "setting_changes": [], "disclosure": [], "unresolved": []}
    try:
        _correct(tm, work, source_cfg, source_path, report)
    except Exception as exc:  # noqa: BLE001 - a prepared copy must still be produced
        report["status"] = "unresolved"
        report["unresolved"].append(f"Studio could not check the plate layout ({type(exc).__name__})")
        report["items_moved"] = 0
    return report


def _correct(tm, work, source_cfg, source_path, report) -> None:
    items, geometry_unresolved = geometry.measure_items(source_path)
    by_index = {item["item_index"]: item for item in items}
    plates = pp._plates_from_model_settings(tm)
    numbers = sorted({p["ui_number"] for p in plates if p.get("ui_number") is not None})
    multi = len(numbers) > 1
    target_polygon = placement.polygon_of(work)
    target = stride_of(target_polygon)
    source = stride_of(placement.polygon_of(source_cfg))
    report["items_moved"] = 0
    if multi and not items and not geometry_unresolved:
        # the geometry could not be measured at all (for example a very large model): say so, not "unchanged"
        geometry_unresolved = [{"item_index": 0, "reason": "the model geometry could not be measured"}]

    # which plate (index) each item sits on, from the project's own records
    plate_index: dict[int, int] = {}
    cols = 1
    unresolved: list[str] = list(f"item {u['item_index']}: {u['reason']}" for u in geometry_unresolved)
    if multi:
        if numbers != list(range(1, len(numbers) + 1)):
            unresolved.append("the plate numbers are not 1..n, so the plate grid cannot be established")
        grouped, loose = pp._group_items_by_plate(items, plates)
        for number, members in grouped.items():
            for member in members:
                plate_index[member["item_index"]] = numbers.index(number)
        if loose:
            unresolved.append(f"{len(loose)} build item(s) are on no plate record, or on more than one")
        cols = column_count(len(numbers))
    else:
        for item in items:
            plate_index[item["item_index"]] = 0

    if source is None or target is None:
        unresolved.append("the source or the U1 printable area is not a rectangle Studio can read")

    # --- cross-check: the item's whole bounding box is inside the cell its own record names -------
    check = {"items": 0, "matched": 0, "mismatches": []}
    cells_ok = source is not None and not unresolved
    if multi and source is not None:
        left, front, right, back = source[2]
        for index, item in by_index.items():
            if index not in plate_index:
                continue
            check["items"] += 1
            ox, oy = origin(plate_index[index], cols, source)
            lo, hi = item["bounds"]["min"], item["bounds"]["max"]
            cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0
            if ox + left - _TOLERANCE <= lo[0] and hi[0] <= ox + right + _TOLERANCE \
                    and oy + front - _TOLERANCE <= lo[1] and hi[1] <= oy + back + _TOLERANCE:
                check["matched"] += 1
            else:
                check["mismatches"].append(
                    {"item_index": index, "plate": plate_index[index] + 1,
                     "centre": [round(cx, 2), round(cy, 2)],
                     "cell": [round(ox + left, 2), round(oy + front, 2), round(ox + right, 2),
                              round(oy + back, 2)]})
        report["formula_check"] = check
        if check["mismatches"]:
            unresolved.append(f"{len(check['mismatches'])} of {check['items']} build item(s) are not in "
                              "the plate cell their record names on the source grid (the whole object "
                              "must be inside it)")
            cells_ok = False

    offsets: dict[int, tuple[float, float]] = {}
    plate_report: dict[int, dict] = {}
    if multi:
        report["status"] = "unresolved" if unresolved else "same_grid"
        if not unresolved and source is not None and target is not None:
            same = abs(source[0] - target[0]) < _TOLERANCE and abs(source[1] - target[1]) < _TOLERANCE
            if not same:
                offsets, plate_report = _plan_regrid(by_index, plate_index, cols, source, target, work)
                report["status"] = "regridded" if any(
                    abs(dx) > _TOLERANCE or abs(dy) > _TOLERANCE for dx, dy in offsets.values()) else "same_grid"
        report["stride_source"] = [round(source[0], 4), round(source[1], 4)] if source else None
        report["stride_target"] = [round(target[0], 4), round(target[1], 4)] if target else None
        report["cols"] = cols
    else:
        report["status"] = "not_multi_plate"
    report["unresolved"].extend(unresolved)

    # --- apply the item translations (translation only, per build item) ---------------------------
    if offsets and report["status"] == "regridded":
        _apply_offsets(tm, offsets, report)
        if report["status"] == "unresolved":
            cells_ok = False  # the items are still on the source grid; the tower check must not assume the U1 grid
        report["plates"] = [plate_report[i] for i in sorted(plate_report)]
        for index in list(offsets):
            item = by_index.get(index)
            if item is not None:
                dx, dy = offsets[index]
                item["bounds"] = {
                    "min": (item["bounds"]["min"][0] + dx, item["bounds"]["min"][1] + dy, item["bounds"]["min"][2]),
                    "max": (item["bounds"]["max"][0] + dx, item["bounds"]["max"][1] + dy, item["bounds"]["max"][2])}

    # --- a project already authored on THIS U1 plate keeps the tower where its creator put it ----
    # The starter profile owns a tower position (a constant written for no particular model). A project
    # whose bed IS the U1's printable area was laid out in Orca for this very plate, tower included, so its
    # position is placement, not tuning, and is kept in every mode.
    src_polygon, dst_polygon = placement.polygon_of(source_cfg), placement.polygon_of(work)
    if src_polygon and dst_polygon and sorted(src_polygon) == sorted(dst_polygon):
        for key in ("wipe_tower_x", "wipe_tower_y"):
            if key in source_cfg and work.get(key) != source_cfg[key]:
                work[key] = copy.deepcopy(source_cfg[key])
                report.setdefault("tower_kept_from_source", []).append(key)

    # --- the prime tower, per plate, against the footprints as they now are ----------------------
    _assess_towers(work, by_index, plate_index, multi, cols, target if target else None, report,
                   plates_known=cells_ok or not multi)
    _disclose(report, multi)


def _plan_regrid(by_index, plate_index, cols, source, target, work):
    """Per item: the translation that puts its plate on the U1 grid, then the plate's own minimal fit."""
    plate_items: dict[int, list[int]] = {}
    for index in by_index:
        if index in plate_index:
            plate_items.setdefault(plate_index[index], []).append(index)
    u1 = pp.u1_bed_rect()
    offsets: dict[int, tuple[float, float]] = {}
    plates: dict[int, dict] = {}
    for idx, members in plate_items.items():
        sox, soy = origin(idx, cols, source)
        tox, toy = origin(idx, cols, target)
        dx, dy = tox - sox, toy - soy
        # the plate's content in the TARGET cell's own frame, to see whether it needs a nudge to fit
        boxes = [by_index[m]["bounds"] for m in members]
        cluster = {"min_x": min(b["min"][0] for b in boxes) + dx - tox,
                   "min_y": min(b["min"][1] for b in boxes) + dy - toy,
                   "max_x": max(b["max"][0] for b in boxes) + dx - tox,
                   "max_y": max(b["max"][1] for b in boxes) + dy - toy}
        fit = pp._centering_offset(cluster, u1)
        fits = pp._fits_after(cluster, u1, fit)
        for member in members:
            offsets[member] = (dx + fit["x"], dy + fit["y"])
        plates[idx] = {"plate": idx + 1, "items": len(members),
                       "cell_source": [round(sox, 3), round(soy, 3)],
                       "cell_target": [round(tox, 3), round(toy, 3)],
                       "delta": [round(dx, 3), round(dy, 3)],
                       "fit_shift": [fit["x"], fit["y"]], "fits_u1_plate": bool(fits)}
    return offsets, plates


def _apply_offsets(tm, offsets: dict, report: dict) -> None:
    raw = tm.read_part(pp.ROOT_MODEL)
    from . import units as _units

    scale = _units.mm_per_unit(raw)
    rewritten, moved = pp.rewrite_items_by_index(
        raw, {index: (dx / scale, dy / scale) for index, (dx, dy) in offsets.items()})
    before, after = geometry.build_items(raw), geometry.build_items(rewritten)
    same = len(before) == len(after) and all(
        {k: v for k, v in a["attributes"].items() if k != "transform"}
        == {k: v for k, v in b["attributes"].items() if k != "transform"}
        for a, b in zip(before, after))
    if not same or moved != len(offsets):
        # the writer and the reader disagree about the build items: write nothing
        report["status"] = "unresolved"
        report["unresolved"].append("Studio could not rewrite the build items safely, so it left them")
        offsets.clear()
        return
    tm.replace_part(pp.ROOT_MODEL, rewritten)
    report["items_moved"] = moved


# --- the prime tower (assessed, never moved) -----------------------------------------------------

def _entry(values, plate: int, fallback: float | None = None):
    """Orca's ``get_at``: the plate's own entry, else the first."""
    if isinstance(values, (str, int, float)):
        values = [values]
    if not isinstance(values, list) or not values:
        return fallback
    try:
        return float(values[plate] if plate < len(values) else values[0])
    except (TypeError, ValueError):
        return fallback


def tower_rect(x: float, y: float, width: float, brim: float) -> tuple[float, float, float, float]:
    """The ESTIMATED rectangle of a tower at corner (x, y): a square of its width, brim included."""
    depth = width * TOWER_DEPTH_FROM_WIDTH
    return (x - brim, y - brim, x + width + brim, y + depth + brim)


def _gap(rect, box) -> float:
    """Edge-to-edge distance between two rectangles (0 when they overlap)."""
    dx = max(box[0] - rect[2], rect[0] - box[2], 0.0)
    dy = max(box[1] - rect[3], rect[1] - box[3], 0.0)
    return math.hypot(dx, dy)


def _assess_towers(work, by_index, plate_index, multi, cols, target, report, *, plates_known: bool) -> None:
    """Per plate: what the file PROVES about the prime tower, and nothing it does not.

    ``outside_proven``: the corner, or the known width plus brim, leaves the U1 printable area.
    ``overlap_possible``: the corner lies inside the bounding box of an object on that plate (the box can
    include empty bed, so this is a possibility, not proof).
    ``unknown``: neither is proven; the full footprint depends on Orca's tool-change planning.
    """
    enabled = work.get("enable_prime_tower")
    if enabled is None or str(enabled).lower() in ("0", "false", "", "none"):
        return
    try:
        width = float(work.get("prime_tower_width"))
    except (TypeError, ValueError):
        width = 0.0
    bed = pp.u1_bed_rect()
    try:
        brim = max(0.0, float(work.get("prime_tower_brim_width") or 0))
    except (TypeError, ValueError):
        brim = 0.0
    n_plates = (len(set(plate_index.values())) or 1) if multi else 1
    xs, ys = work.get("wipe_tower_x"), work.get("wipe_tower_y")
    footprints: dict[int, list[tuple]] = {i: [] for i in range(n_plates)}
    for index, item in by_index.items():
        idx = plate_index.get(index)
        if idx is None:
            continue
        ox, oy = (origin(idx, cols, target) if (multi and target) else (0.0, 0.0))
        lo, hi = item["bounds"]["min"], item["bounds"]["max"]
        footprints.setdefault(idx, []).append((lo[0] - ox, lo[1] - oy, hi[0] - ox, hi[1] - oy))

    for i in range(n_plates):
        x, y = _entry(xs, i), _entry(ys, i)
        record = {"plate": i + 1, "position": [x, y], "width": width, "brim": brim,
                  "status": "unknown", "reason": None, "known_x_extent": None, "known_y_min": None,
                  "estimate": {"rect": None, "clearance_to_edges": None, "clearance_to_objects": None,
                              "note": "a square of the tower's width; Orca decides the real depth"}}
        report["tower"].append(record)
        if multi and not plates_known:
            record["reason"] = "the plate layout could not be established"
            continue
        if x is None or y is None or width <= 0:
            record["reason"] = "the project states no usable tower position or width"
            continue
        record["known_x_extent"] = [round(x - brim, 3), round(x + width + brim, 3)]
        record["known_y_min"] = round(y - brim, 3)
        est = tower_rect(x, y, width, brim)
        record["estimate"]["rect"] = [round(v, 3) for v in est]
        record["estimate"]["clearance_to_edges"] = {
            "left": round(est[0] - bed["min_x"], 3), "right": round(bed["max_x"] - est[2], 3),
            "front": round(est[1] - bed["min_y"], 3), "back": round(bed["max_y"] - est[3], 3)}
        boxes = footprints.get(i, [])
        record["estimate"]["clearance_to_objects"] = (
            round(min(_gap(est, box) for box in boxes), 3) if boxes else None)
        if (x - brim < bed["min_x"] - _TOLERANCE or x + width + brim > bed["max_x"] + _TOLERANCE
                or y - brim < bed["min_y"] - _TOLERANCE or y > bed["max_y"] + _TOLERANCE):
            record.update(status="outside_proven",
                          reason="its position and width already leave the U1 printable area")
        elif any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes):
            record.update(status="overlap_possible",
                          reason="its corner is inside the bounding box of an object on that plate")
        else:
            record["reason"] = ("the tower's depth is decided when Snapmaker Orca plans the tool changes, "
                                "so whether it is inside the plate and clear of the objects is not known")
    report["tower_note"] = ("Studio did not move any prime tower: its full footprint (depth, ribs, brim, "
                            "clearance) is only fixed when Snapmaker Orca plans the tool changes.")


def _disclose(report: dict, multi: bool) -> None:
    lines = report["disclosure"]
    if report.get("status") == "regridded":
        moved = [p for p in report["plates"] if abs(p["delta"][0]) > _TOLERANCE or abs(p["delta"][1]) > _TOLERANCE
                 or abs(p["fit_shift"][0]) > _TOLERANCE or abs(p["fit_shift"][1]) > _TOLERANCE]
        for p in moved:
            nudge = abs(p["fit_shift"][0]) > _TOLERANCE or abs(p["fit_shift"][1]) > _TOLERANCE
            tail = (f"; this includes a fit adjustment of X {p['fit_shift'][0]:+g} mm, Y {p['fit_shift'][1]:+g} mm "
                    "so the plate's objects sit inside the U1 plate") if nudge else ""
            lines.append(f"Repositioned plate {p['plate']} objects to the U1 plate layout "
                         f"(X {p['delta'][0] + p['fit_shift'][0]:+g} mm, Y {p['delta'][1] + p['fit_shift'][1]:+g} mm{tail}). "
                         "The objects keep their positions relative to each other; rotation and scale are unchanged.")
        for p in report["plates"]:
            if not p["fits_u1_plate"]:
                lines.append(f"Plate {p['plate']}'s objects are larger than the U1 plate, so they still "
                             "will not fit it; Snapmaker Orca will show them outside.")
    for t in report["tower"]:
        if t["status"] == "outside_proven":
            lines.append(f"Plate {t['plate']}'s prime tower is outside the U1 printable area ({t['reason']}); "
                         "Studio left it where it is because it cannot establish the tower's full footprint. "
                         "Move it in Snapmaker Orca's prime tower settings.")
        elif t["status"] == "overlap_possible":
            lines.append(f"Plate {t['plate']}'s prime tower may sit on an object ({t['reason']}, which can include "
                         "empty bed); Studio left it where it is because it cannot establish the tower's full "
                         "footprint.")
    for reason in report["unresolved"]:
        lines.append(f"Plate positions were left as the source had them: {reason}.")
