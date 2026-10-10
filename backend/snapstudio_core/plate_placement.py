"""Plate placement — is each object actually *on* the U1's bed, and can that be fixed?

A project authored for another printer carries its objects at that printer's
coordinates. A 40 mm part sitting at X=300 on a 350 mm bed is small enough for the
U1 by every size check, and still lands completely off a 270 mm plate. Size checks
never catch it, because nothing is too big — it is in the wrong place.

Snapmaker Orca's answer to this is a bare "out of bounds", and the community's
answer is "hit Arrange and hope". This module gives the specific answer instead:
which object is off the plate, by how much and on which edge, whether one
translation would bring the whole arrangement back on, and — when it would —
writes a new copy with exactly that translation applied.

Discipline, in order of importance:

* **The original is never modified.** A fix writes a new file.
* **Only the placement changes.** The rewrite touches the translation component of
  build-item transforms and nothing else: no meshes, no painted colour, no
  settings, no other archive entry. Rotation and scale are carried through
  untouched, so the creator's arrangement survives.
* **It refuses rather than guesses.** If one translation cannot bring everything
  on-plate, it says so and stops. Multi-plate projects are never repositioned at
  all: the spacing between plates is not recorded in the file, so any move would
  be a guess. They are still *checked* — each plate is judged on whether its own
  contents fit a U1 plate, which does not depend on the grid — and the answer is
  "open this in Orca and use Arrange".
"""
from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

from . import units as _units
from .container import ThreeMF

SCHEMA_VERSION = "placement/1"

ROOT_MODEL = "3D/3dmodel.model"

# Objects are not placed at the extreme edge in practice: skirt, brim and the
# prime tower all need room. A hair of margin keeps a "just touching the edge"
# result from reading as safe.
EDGE_MARGIN_MM = 0.5

_ITEM_TAG_RE = re.compile(r"<item\b[^>]*/?>")
_TRANSFORM_ATTR_RE = re.compile(r'(\btransform\s*=\s*")([^"]*)(")')


def _u1_printable_area() -> list[str]:
    template = json.loads(
        (files("snapstudio_core.data") / "templates" / "u1_base_project_settings.json")
        .read_text("utf-8"))
    return template.get("printable_area") or []


def parse_printable_area(area) -> dict | None:
    """Turn a slicer's printable_area polygon into an axis-aligned rectangle.

    The value is a list of ``"XxY"`` corner strings. Only rectangular beds are
    handled; anything else returns None so the caller reports "unknown" instead
    of pretending a delta bed is a box.
    """
    if not isinstance(area, (list, tuple)) or len(area) < 3:
        return None
    xs, ys = [], []
    for corner in area:
        parts = str(corner).lower().split("x")
        if len(parts) != 2:
            return None
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            return None
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}


def _prepare_target_name() -> str:
    from . import printer_profiles

    return printer_profiles.display_name(printer_profiles.prepare_target())


def u1_bed_rect() -> dict:
    """The U1's printable rectangle, from Studio's own U1 profile template."""
    rect = parse_printable_area(_u1_printable_area())
    # The template is shipped with the package and is rectangular; the fallback
    # exists only so a corrupted install degrades to the published volume.
    return rect or {"min_x": 0.0, "min_y": 0.0, "max_x": 270.0, "max_y": 270.0}


def _source_bed(tm: ThreeMF) -> dict | None:
    part = "Metadata/project_settings.config"
    if not tm.has_part(part):
        return None
    try:
        cfg = json.loads(tm.read_part(part).decode("utf-8", "ignore"))
    except Exception:
        return None
    return parse_printable_area(cfg.get("printable_area"))


def _overhang(bounds: dict, bed: dict) -> dict:
    """How far an item pokes past each edge, in mm. Zero means inside."""
    lo, hi = bounds["min"], bounds["max"]
    return {
        "left": round(max(0.0, (bed["min_x"] + EDGE_MARGIN_MM) - lo[0]), 2),
        "right": round(max(0.0, hi[0] - (bed["max_x"] - EDGE_MARGIN_MM)), 2),
        "front": round(max(0.0, (bed["min_y"] + EDGE_MARGIN_MM) - lo[1]), 2),
        "back": round(max(0.0, hi[1] - (bed["max_y"] - EDGE_MARGIN_MM)), 2),
    }


def _instance_list(rows: list[dict]) -> str:
    """'object 1, instance 1 of 2; object 3' — which placed items a sentence is about."""
    named = []
    for row in rows:
        text = f"object {row['object_id']}"
        if row.get("instance_count", 1) > 1:
            text += f", instance {row['instance_index'] + 1} of {row['instance_count']}"
        named.append(text)
    return "; ".join(named)


def _edges_text(over: dict) -> str:
    named = [name for name, mm in over.items() if mm > 0]
    return ", ".join(named)


def _cluster_bounds(items: list[dict]) -> dict:
    xs_lo = min(i["bounds"]["min"][0] for i in items)
    ys_lo = min(i["bounds"]["min"][1] for i in items)
    xs_hi = max(i["bounds"]["max"][0] for i in items)
    ys_hi = max(i["bounds"]["max"][1] for i in items)
    return {"min_x": xs_lo, "min_y": ys_lo, "max_x": xs_hi, "max_y": ys_hi}


def _centering_offset(cluster: dict, bed: dict) -> dict:
    """The smallest translation that brings the whole arrangement onto the bed.

    Not the centre of the plate. Somebody who arranged a print 0.5 mm off the edge
    asked for it to be where it is; moving it half a metre to the middle answers a
    question they did not ask. The smallest move that works changes as little as
    possible about what they chose, and it is deterministic: for each axis there is
    one interval of translations that fits, and this is the point in it nearest to
    not moving at all.
    """
    low_x = bed["min_x"] + EDGE_MARGIN_MM - cluster["min_x"]
    high_x = bed["max_x"] - EDGE_MARGIN_MM - cluster["max_x"]
    low_y = bed["min_y"] + EDGE_MARGIN_MM - cluster["min_y"]
    high_y = bed["max_y"] - EDGE_MARGIN_MM - cluster["max_y"]
    return {"x": round(_nearest_to_zero(low_x, high_x), 3),
            "y": round(_nearest_to_zero(low_y, high_y), 3)}


def _nearest_to_zero(low: float, high: float) -> float:
    """The number in [low, high] closest to zero; 0 when the interval is empty."""
    if low > high:
        return 0.0
    if low > 0.0:
        return low
    if high < 0.0:
        return high
    return 0.0


def _fits_after(cluster: dict, bed: dict, offset: dict) -> bool:
    return (cluster["min_x"] + offset["x"] >= bed["min_x"] + EDGE_MARGIN_MM - 1e-6
            and cluster["max_x"] + offset["x"] <= bed["max_x"] - EDGE_MARGIN_MM + 1e-6
            and cluster["min_y"] + offset["y"] >= bed["min_y"] + EDGE_MARGIN_MM - 1e-6
            and cluster["max_y"] + offset["y"] <= bed["max_y"] - EDGE_MARGIN_MM + 1e-6)


def _printable_only(path: str, items: list[dict]) -> list[dict]:
    """Bounds measured from the parts that print, where the project says which.

    A modifier, a negative volume or a support blocker is an instruction to the
    slicer rather than something that lands on the bed, and one of them sitting far
    off the plate does not stop the print. Measured against Snapmaker Orca 2.3.5
    with a control: a modifier cube 400 mm off the plate sliced without complaint,
    and the same cube written as a normal part stopped the slice. Counting it would
    warn about a problem the printer does not have — and offer to move an
    arrangement that is already fine.
    """
    from . import placement

    try:
        read = placement.read_objects(path)
    except Exception:
        return items
    # Keyed by build item, not by object id: one object can be used by several items, each
    # at its own place, and a table keyed by object id gives all of them the last one's.
    footprints = {entry["item_index"]: entry["footprint"]
                  for entry in read.get("objects") or ()
                  if entry.get("footprint")}
    if not footprints:
        return items

    out = []
    for item in items:
        box = footprints.get(item.get("item_index"))
        if box is None:
            out.append(item)
            continue
        low, high = item["bounds"]["min"], item["bounds"]["max"]
        entry = dict(item)
        entry["bounds"] = {"min": (box["min_x"], box["min_y"], low[2]),
                           "max": (box["max_x"], box["max_y"], high[2])}
        entry["dimensions"] = dict(item["dimensions"],
                                   x=round(box["width"], 3), y=round(box["depth"], 3))
        out.append(entry)
    return out


def _unavailable(reason: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "available": False, "reason": reason,
            "items": [], "off_plate": [], "fixable": False}


# --- multi-plate projects ----------------------------------------------------
#
# A slicer lays several build plates out on one coordinate grid, and the stride
# between them is not recorded in the file.
#
# Studio used to derive that stride from where each plate's objects happened to
# sit. An independent review reproduced the consequence: for two plates whose
# parts were off-centre, a true 370 mm stride was measured as 690 mm and the
# second plate was placed 745 mm along X — entirely off the bed — while the
# result reported success. The measurement was of the parts, not of the grid, and
# with only two plates the "does this stride explain every plate" check is a
# tautology.
#
# Rather than patch a number Studio cannot actually observe, the repositioning is
# withdrawn for multi-plate projects. What remains is the part that is sound: each
# plate is judged on whether its own contents *fit* a U1 plate, which does not
# depend on the grid at all. A plate's absolute coordinates on a multi-plate grid
# are an artefact of the authoring slicer, not a fault in the project — so an
# object at X=900 on plate 3 is not "off the plate", and Studio no longer says it
# is.
#
# Moving them is Snapmaker Orca's Arrange, and Studio says so.

MULTI_PLATE_REFUSAL = (
    "Studio does not reposition multi-plate projects. The spacing between plates "
    "is not recorded in the file, so any move would be a guess — open the project "
    "in Snapmaker Orca and use Arrange."
)


_MODEL_INSTANCE_RE = re.compile(r"<model_instance>(.*?)</model_instance>", re.S)
_METADATA_RE = re.compile(r'key="([^"]*)"\s+value="([^"]*)"')


def _plates_from_model_settings(tm: ThreeMF) -> list[dict]:
    """UI plate number -> the objects on it, from the project's own records.

    `object_ids` is every object named; `members` is the same list as
    ``(object id, instance id or None)`` so a repeated object can be placed per instance.
    """
    part = "Metadata/model_settings.config"
    if not tm.has_part(part):
        return []
    try:
        from .plate_remap import _parse_plates

        text = tm.read_part(part).decode("utf-8", "ignore")
        plates = _parse_plates(text)
        bodies = re.findall(r"<plate>(.*?)</plate>", text, re.S)
        # `_parse_plates` sorts by plate number; pair each body with its plate by number.
        by_number: dict = {}
        for body in bodies:
            number = re.search(r'key="plater_id"\s+value="(\d+)"', body)
            members = []
            for instance in _MODEL_INSTANCE_RE.findall(body):
                meta = dict(_METADATA_RE.findall(instance))
                if meta.get("object_id") is not None:
                    members.append((meta["object_id"], meta.get("instance_id")))
            by_number.setdefault(int(number.group(1)) if number else None, []).extend(members)
        for plate in plates:
            plate["members"] = by_number.get(plate["ui_number"], [])
        return plates
    except Exception:
        return []


def _group_items_by_plate(items: list[dict], plates: list[dict]):
    """Split build items across plates. Returns (grouped, unresolved).

    Judged per instance: the n-th build item that uses an object is matched to the plate
    record that names that instance. A record that names an object without saying which
    instance can only place it when the object is used once. An item that no record (or
    more than one plate) claims is 'unresolved': Studio cannot say which plate it is on,
    and therefore cannot judge it.
    """
    totals: dict[str, int] = {}
    for item in items:
        totals[str(item["object_id"])] = totals.get(str(item["object_id"]), 0) + 1
    parts_of: dict[str, set] = {}
    for item in items:
        parts_of.setdefault(str(item["object_id"]), set()).add(item.get("part"))
    seen: dict[str, int] = {}
    grouped: dict[int, list[dict]] = {}
    unresolved: list[dict] = []
    for item in items:
        oid = str(item["object_id"])
        ordinal = seen.get(oid, 0)
        seen[oid] = ordinal + 1
        owners: set = set()
        # plate records name a BARE object id: when build items in different parts share it, a
        # record cannot prove which one it means
        ambiguous = len(parts_of[oid]) > 1
        for plate in plates:
            members = plate.get("members")
            if members is None:      # a plate described by object ids alone
                members = [(str(o), None) for o in plate.get("object_ids") or []]
            for member_oid, instance in members:
                if str(member_oid) != oid:
                    continue
                if instance is None:
                    if totals[oid] == 1:
                        owners.add(plate["ui_number"])
                    else:
                        ambiguous = True
                elif str(instance).isdigit() and int(instance) == ordinal:
                    owners.add(plate["ui_number"])
        if ambiguous or len(owners) != 1 or None in owners:
            unresolved.append(item)
        else:
            grouped.setdefault(next(iter(owners)), []).append(item)
    return grouped, unresolved


def _plate_fit(grouped: dict[int, list[dict]], bed: dict,
               whose: str = "the plate") -> list[dict]:
    """Does each plate's own content fit the plate? Position-independent."""
    usable_x = bed["max_x"] - bed["min_x"] - 2 * EDGE_MARGIN_MM
    usable_y = bed["max_y"] - bed["min_y"] - 2 * EDGE_MARGIN_MM
    out = []
    for number in sorted(grouped):
        cluster = _cluster_bounds(grouped[number])
        width = cluster["max_x"] - cluster["min_x"]
        depth = cluster["max_y"] - cluster["min_y"]
        fits = width <= usable_x and depth <= usable_y
        out.append({
            "plate": number,
            "fits": fits,
            "width": round(width, 2),
            "depth": round(depth, 2),
            "object_ids": [i["object_id"] for i in grouped[number]],
            "item_indexes": [i.get("item_index") for i in grouped[number]],
            "reason": None if fits else (
                f"the objects on this plate span {width:.0f} × {depth:.0f} mm, which is "
                f"larger than {whose} {usable_x:.0f} × {usable_y:.0f} mm plate"),
        })
    return out


def assess(path: str, bed: dict | None = None, bed_name: str | None = None) -> dict:
    """Where every object sits relative to the bed. Read-only, never raises.

    `bed` is the printer's real printable rectangle when one has been read from a
    connected machine; without it the check falls back to the plate of the printer
    Studio prepares copies for. `bed_name` is what to call that plate in the
    sentences below — because a summary that says "the U1's printable area" while
    measuring against a rectangle a different printer reported is describing the
    wrong machine.
    """
    from . import geometry, project_traits

    target = bed or u1_bed_rect()
    whose = bed_name or ("this printer's" if bed else f"the {_prepare_target_name()}'s")

    try:
        tm = ThreeMF.open(path)
    except Exception:
        return _unavailable("Studio could not open this file as a 3MF project.")

    traits = project_traits.extract(path)
    plate_count = (traits.get("plate_count") or {}).get("value") or 1

    measured, geometry_unresolved = geometry.measure_items(path)
    items = _printable_only(path, measured)
    if not items:
        return _unavailable(
            "Studio could not read where the objects sit in this project, so it "
            "cannot check their placement. Open it in Snapmaker Orca to see the plate.")

    source_bed = _source_bed(tm)

    multi_plate = bool(plate_count and plate_count > 1)
    # Instances Studio cannot judge are listed, counted and never treated as harmless: a build item
    # whose object is not where the file says it is, or that no plate record places.
    unresolved: list[dict] = [dict(entry, reason="Studio could not find this item's object: "
                                   + entry["reason"]) for entry in geometry_unresolved]
    grouped: dict[int, list[dict]] = {}
    plate_fit: list[dict] = []
    if multi_plate:
        plates = _plates_from_model_settings(tm)
        grouped, unresolved_items = _group_items_by_plate(items, plates)
        unresolved += [{"object_id": i["object_id"], "item_index": i.get("item_index"),
                        "reason": "no plate record places this instance"}
                       for i in unresolved_items]
        plate_fit = _plate_fit(grouped, target, whose)
    not_judged = len(unresolved)

    # instance numbers count uses of the SAME object: an id is only unique within its part
    totals: dict[tuple, int] = {}
    for item in items:
        who = (item.get("part"), str(item["object_id"]))
        totals[who] = totals.get(who, 0) + 1
    seen: dict[tuple, int] = {}
    reported = []
    for item in items:
        lo, hi = item["bounds"]["min"], item["bounds"]["max"]
        oid = (item.get("part"), str(item["object_id"]))
        instance_index = seen.get(oid, 0)
        seen[oid] = instance_index + 1
        if multi_plate:
            # A plate's absolute coordinates on a multi-plate grid are an artefact
            # of the authoring slicer, not a fault. Judge the plate's *size*.
            over = {"left": 0.0, "right": 0.0, "front": 0.0, "back": 0.0}
            off = False
        else:
            over = _overhang(item["bounds"], target)
            off = any(mm > 0 for mm in over.values())
        reported.append({
            "object_id": item["object_id"],
            "item_index": item.get("item_index"),
            "instance_index": instance_index,
            "instance_count": totals[oid],
            "bounds_mm": {"min": [round(v, 4) for v in lo], "max": [round(v, 4) for v in hi]},
            "dimensions": item["dimensions"],
            "position": {"x": round((lo[0] + hi[0]) / 2.0, 2),
                         "y": round((lo[1] + hi[1]) / 2.0, 2)},
            "off_plate": off,
            "overhang_mm": over,
            "edges": _edges_text(over) or None,
        })

    oversized_plates = [p for p in plate_fit if not p["fits"]]
    if multi_plate:
        oversized_items = {ix for p in oversized_plates for ix in p["item_indexes"]}
        for row in reported:
            if row["item_index"] in oversized_items:
                row["off_plate"] = True

    off_plate = [r for r in reported if r["off_plate"]]
    cluster = _cluster_bounds(items)
    offset = _centering_offset(cluster, target)
    span_x = cluster["max_x"] - cluster["min_x"]
    span_y = cluster["max_y"] - cluster["min_y"]
    bed_x = target["max_x"] - target["min_x"] - 2 * EDGE_MARGIN_MM
    bed_y = target["max_y"] - target["min_y"] - 2 * EDGE_MARGIN_MM
    too_wide = span_x > bed_x or span_y > bed_y
    would_fit = (not too_wide) and _fits_after(cluster, target, offset)

    # Studio never repositions a multi-plate project: the plate spacing is not in
    # the file, so any move would be a guess.
    # Nor is a move offered while some instance could not be judged: the move would carry it
    # somewhere nobody has checked.
    fixable = (not multi_plate) and bool(off_plate) and would_fit and not not_judged

    # A repeated object is one object at several places; the sentence counts the places, so the
    # instance that is off the plate is never averaged away by the one that is not.
    repeated = any(r["instance_count"] > 1 for r in reported)
    k = len(off_plate)
    if repeated:
        count_text = f"{k} of {len(reported)} placed instances ({_instance_list(off_plate)})"
    else:
        count_text = f"{k} object" + ("" if k == 1 else "s")
    fall = "falls" if k == 1 else "fall"
    unjudged = ""
    if not_judged:
        unjudged = (f" {not_judged} placed instance{'s' if not_judged != 1 else ''} could not be "
                    "judged, so Studio cannot say whether everything is on the plate.")

    if multi_plate and not off_plate:
        if plate_fit:
            summary = (f"None of the plates Studio could assign is too big for {whose} printable area."
                       if not_judged else
                       f"All {len(plate_fit)} plate{'s' if len(plate_fit) != 1 else ''} fit "
                       f"{whose} printable area.")
        else:
            summary = ""
        summary = (summary + unjudged + " Studio does not reposition multi-plate projects — open "
                   "the project in Snapmaker Orca to arrange the plates.").strip()
    elif multi_plate and oversized_plates:
        names = ", ".join(str(p["plate"]) for p in oversized_plates)
        summary = (f"Plate {names} does not fit {whose} printable area: "
                   f"{oversized_plates[0]['reason']}. Scale it down or split it."
                   + unjudged + " " + MULTI_PLATE_REFUSAL)
    elif multi_plate:
        summary = (MULTI_PLATE_REFUSAL + unjudged).strip()
    elif not off_plate:
        if not_judged:
            summary = f"Every placed instance Studio could measure sits inside {whose} printable area.{unjudged}"
        else:
            summary = (f"Every placed instance sits inside {whose} printable area."
                       if repeated else
                       f"Every object sits inside {whose} printable area."
                       if len(reported) > 1 else
                       f"The object sits inside {whose} printable area.")
    elif too_wide:
        summary = (f"{count_text} {fall} outside {whose} plate, and the "
                   "whole arrangement is wider than the plate — moving it cannot fix "
                   "this. Scale it down or split it across plates." + unjudged)
    elif would_fit and not not_judged:
        summary = (f"{count_text} {fall} outside {whose} plate, but the "
                   "whole arrangement fits — moving it as one piece brings everything "
                   "back on, keeping the creator's layout, rotation and scale.")
    else:
        summary = (f"{count_text} {fall} outside {whose} plate and one "
                   "move will not fix it. Open it in Snapmaker Orca and use Arrange." + unjudged)

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "bed": target,
        "source_bed": source_bed,
        "source_printer": (traits.get("target_printer") or {}).get("value"),
        "plate_count": plate_count,
        "item_count": len(reported),
        "items": reported,
        "off_plate": off_plate,
        "arrangement": {"width": round(span_x, 2), "depth": round(span_y, 2)},
        "suggested_offset": offset if (would_fit and not multi_plate) else None,
        "plate_fit": plate_fit,
        "oversized_plates": oversized_plates,
        "unresolved_objects": unresolved,
        "not_judged": not_judged,
        "fixable": fixable,
        "summary": summary,
    }


# --- the fix ---------------------------------------------------------------

def _shift_transform(value: str, dx: float, dy: float) -> str | None:
    """Add (dx, dy) to a 3MF transform's translation. None if not a 3x4 matrix.

    3MF stores the matrix row-major with the translation as the final row, so
    only entries 10 and 11 (1-indexed 12-value form) move. Everything else —
    rotation, scale, shear — is copied through unchanged.
    """
    parts = value.split()
    if len(parts) != 12:
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    nums[9] += dx
    nums[10] += dy
    return " ".join(f"{n:.6g}" for n in nums)


def _identity_shifted(dx: float, dy: float) -> str:
    return _shift_transform("1 0 0 0 1 0 0 0 1 0 0 0", dx, dy) or ""


_OBJECTID_RE = re.compile(r'\bobjectid\s*=\s*"([^"]*)"')


def _rewrite_items(raw: bytes, offset_for) -> tuple[bytes, int]:
    """Translate build items in the root model part.

    ``offset_for`` maps an item's object id to an ``(dx, dy)`` pair, or None to
    leave that item exactly where it is — which is how a skipped plate and an
    object Studio could not place stay untouched.

    Byte-surgical: only the transform attribute inside <item> tags is rewritten.
    Meshes, painted colour, settings and every other archive entry are unchanged.
    """
    text = raw.decode("utf-8", "strict")
    moved = 0

    def fix_item(match: re.Match) -> str:
        nonlocal moved
        tag = match.group(0)
        oid_match = _OBJECTID_RE.search(tag)
        offset = offset_for(oid_match.group(1) if oid_match else None)
        if offset is None:
            return tag
        dx, dy = offset
        attr = _TRANSFORM_ATTR_RE.search(tag)
        if attr is None:
            # An item with no transform is at the identity; give it the shift so
            # it moves with the rest of the plate instead of staying behind.
            moved += 1
            insert = f' transform="{_identity_shifted(dx, dy)}"'
            return tag[:-2] + insert + "/>" if tag.endswith("/>") else tag[:-1] + insert + ">"
        shifted = _shift_transform(attr.group(2), dx, dy)
        if shifted is None:
            return tag
        moved += 1
        return tag[:attr.start()] + attr.group(1) + shifted + attr.group(3) + tag[attr.end():]

    out = _ITEM_TAG_RE.sub(fix_item, text)
    return out.encode("utf-8"), moved


def _uniform_offset(dx: float, dy: float):
    return lambda _oid: (dx, dy)


def _unique_output(src: Path, out_dir: Path | None) -> Path:
    target = out_dir if out_dir else src.parent
    out = target / f"{src.stem}_placed_U1.3mf"
    n = 2
    while out.resolve() == src.resolve() or out.exists():
        out = target / f"{src.stem}_placed_U1_{n}.3mf"
        n += 1
    return out


#: The numbers a build item carries are written to six significant digits, so two items moved by the
#: same amount can differ by a few thousandths of a millimetre. Anything within this is "the same".
MOVE_TOLERANCE_MM = 0.01


def _without_transform(attributes: dict) -> dict:
    return {key: value for key, value in attributes.items() if key != "transform"}


def verify_only_placement_moved(source: str, moved: str) -> dict:
    """Prove the copy differs from the original in where the objects sit, and in
    nothing else.

    A move that quietly re-serialised a mesh, dropped a painted facet or rewrote a
    setting would still pass a placement check, because a placement check only
    looks at placement.
    """
    import zipfile

    from . import geometry, multipart, painted_color, placement

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        return bool(ok)

    with zipfile.ZipFile(source) as before, zipfile.ZipFile(moved) as after:
        names_before, names_after = set(before.namelist()), set(after.namelist())
        check("the file list is unchanged", names_before == names_after,
              f"+{sorted(names_after - names_before)} "
              f"-{sorted(names_before - names_after)}")
        differing = [name for name in sorted(names_before & names_after)
                     if before.read(name) != after.read(name)]
        check("only the root model differs", differing == [ROOT_MODEL],
              f"differing: {differing}")
        root_before = before.read(ROOT_MODEL).decode("utf-8", "ignore")
        root_after = after.read(ROOT_MODEL).decode("utf-8", "ignore")

    strip = lambda text: _ITEM_TAG_RE.sub("", text)  # noqa: E731
    check("the root model's geometry and components are unchanged",
          strip(root_before) == strip(root_after))

    # Per build item, in order: an object used by two items is two items to compare. Everything
    # about an item except where it sits (its object, its p:path, its printable flag, anything
    # else it carries) must be unchanged, and its turn and scale with it.
    items_before = geometry.build_items(root_before)
    items_after = geometry.build_items(root_after)
    same = len(items_before) == len(items_after) and all(
        _without_transform(one["attributes"]) == _without_transform(two["attributes"])
        for one, two in zip(items_before, items_after))
    check("every build item is still there, unchanged apart from where it sits", same,
          f"{len(items_before)} item(s) before, {len(items_after)} after")

    root_scale = _units.mm_per_unit(root_before)
    deltas = []
    same_basis = len(items_before) == len(items_after)
    for before_item, after_item in zip(items_before, items_after):
        # an item with no transform is at the identity
        one = (placement.parse_transform(before_item["transform"])
               if before_item["transform"] else placement.IDENTITY)
        two = (placement.parse_transform(after_item["transform"])
               if after_item["transform"] else placement.IDENTITY)
        if one is None or two is None:
            same_basis = False
            break
        if one[0] != two[0] or one[1] != two[1] or one[2] != two[2]:
            same_basis = False        # a rotation or a scale crept in
            break
        deltas.append(tuple((two[3][axis] - one[3][axis]) * root_scale for axis in range(3)))
    check("nothing was rotated or rescaled", same_basis)
    # What "moved" means: every item's translation changed by the SAME non-zero amount in X and Y
    # (to within what the written numbers can carry) and not at all in Z. A copy that moved one
    # instance, or none, is not a moved copy.
    uniform = bool(deltas) and all(
        all(abs(d[axis] - deltas[0][axis]) <= MOVE_TOLERANCE_MM for axis in range(3)) for d in deltas)
    moved_xy = bool(deltas) and (abs(deltas[0][0]) > MOVE_TOLERANCE_MM or abs(deltas[0][1]) > MOVE_TOLERANCE_MM)
    check("every object moved by the same amount, in X and Y only",
          uniform and moved_xy and abs(deltas[0][2]) <= MOVE_TOLERANCE_MM,
          str([tuple(round(v, 4) for v in d) for d in deltas]))

    structure = multipart.validate_archive(ThreeMF.open(moved))
    check("the moved copy still describes itself consistently",
          structure.get("ok", False), "; ".join(structure.get("problems") or ()))

    one_paint = painted_color.read_container(ThreeMF.open(source))
    two_paint = painted_color.read_container(ThreeMF.open(moved))
    check("the painting is unchanged",
          one_paint.get("painted_triangle_count") == two_paint.get("painted_triangle_count")
          and one_paint.get("slots_referenced") == two_paint.get("slots_referenced"))

    return {"passed": all(entry["pass"] for entry in checks), "checks": checks,
            "delta_mm": ({"x": round(deltas[0][0], 4), "y": round(deltas[0][1], 4)}
                         if deltas and uniform else None)}


def prepare_placed_copy(path: str, out_dir: str | None = None,
                        bed: dict | None = None) -> dict:
    """Write a new copy with the whole arrangement moved onto the U1 plate.

    Returns a result describing what moved and what the check said afterwards.
    Refuses — without writing anything — when the assessment says a single move
    cannot fix the project.
    """
    before = assess(path, bed=bed)
    if not before.get("available"):
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": before.get("reason"), "before": before}
    if not before.get("off_plate"):
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": "Nothing to move — every object is already on the plate.",
                "before": before}
    if not before.get("fixable"):
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": before["summary"], "before": before}

    src = Path(path)
    try:
        tm = ThreeMF.open(src)
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": "Studio could not open this file as a 3MF project.",
                "before": before}
    if not tm.has_part(ROOT_MODEL):
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": "This project has no 3D model part Studio can reposition.",
                "before": before}

    offset = before["suggested_offset"]
    # The geometry above is measured in millimetres, but a build item's translation is written in the
    # ROOT model's own unit. Convert the offset back before it is added, or an inch project would be
    # shifted by 25.4 times too little (and the move would silently not land).
    root_scale = _units.mm_per_unit(tm.read_part(ROOT_MODEL))
    offset_for = _uniform_offset(offset["x"] / root_scale, offset["y"] / root_scale)

    try:
        rewritten, moved = _rewrite_items(tm.read_part(ROOT_MODEL), offset_for)
    except (UnicodeDecodeError, ValueError):
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": ("Studio could not read this project's model data as text, so "
                           "it will not rewrite it."),
                "before": before}
    if not moved:
        return {"schema_version": SCHEMA_VERSION, "ok": False,
                "reason": "Studio found no placed objects to move in this project.",
                "before": before}
    tm.replace_part(ROOT_MODEL, rewritten)

    out_parent = Path(out_dir) if out_dir else None
    if out_parent:
        out_parent.mkdir(parents=True, exist_ok=True)
    out = _unique_output(src, out_parent)
    tm.save(out)

    # Validate the fix by re-running the same check against the file that was
    # actually written — not against what the code intended to write.
    after = assess(str(out), bed=bed)
    proof = verify_only_placement_moved(str(src), str(out))
    delta = proof.get("delta_mm")
    if delta is not None:
        # the copy must have moved by what was asked, not merely by something uniform
        asked = abs(delta["x"] - offset["x"]) <= MOVE_TOLERANCE_MM and abs(delta["y"] - offset["y"]) <= MOVE_TOLERANCE_MM
        proof["checks"].append({"check": "the move is the one that was asked for", "pass": asked,
                                "detail": f"moved {delta}, asked {offset}"})
        proof["passed"] = proof["passed"] and asked
    if not proof["passed"]:
        out.unlink(missing_ok=True)
        return {
            "schema_version": SCHEMA_VERSION, "ok": False,
            "reason": ("Studio's moved copy changed something other than where the "
                       "objects sit, so it was not kept: "
                       + "; ".join(entry["check"] for entry in proof["checks"]
                                   if not entry["pass"])),
            "before": before, "verification": proof,
        }
    ok = bool(after.get("available")) and not after.get("off_plate")
    if not ok:
        # A copy that did not achieve what it was supposed to is not kept on disk: the
        # result says plainly that the move did not work and names no file.
        out.unlink(missing_ok=True)
        return {
            "schema_version": SCHEMA_VERSION, "ok": False,
            "reason": ("Studio could not move the objects onto the plate, so it did not "
                       "keep a copy. Open the original in Snapmaker Orca and use Arrange."),
            "before": before, "after": after,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "output_path": str(out),
        "output_name": out.name,
        "objects_moved": moved,
        "offset_mm": offset,
        "verification": proof,
        "before": before,
        "after": after,
        "changes": [{
            "what": "Moved the whole arrangement onto the U1 plate",
            "detail": (f"Every object shifted by X {offset['x']:+.1f} mm, "
                       f"Y {offset['y']:+.1f} mm."),
            "kept": "Layout, rotation, scale and height are unchanged.",
        }],
        "summary": (f"{moved} object(s) moved onto the U1 plate in a new copy — "
                    f"{out.name}. Your original file was not changed."),
    }
