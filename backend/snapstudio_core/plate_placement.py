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
    footprints = {entry["object_id"]: entry["footprint"]
                  for entry in read.get("objects") or ()
                  if entry.get("footprint")}
    if not footprints:
        return items

    out = []
    for item in items:
        box = footprints.get(str(item.get("object_id")))
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


def _plates_from_model_settings(tm: ThreeMF) -> list[dict]:
    """UI plate number -> the object ids on it, from the project's own records."""
    part = "Metadata/model_settings.config"
    if not tm.has_part(part):
        return []
    try:
        from .plate_remap import _parse_plates

        return _parse_plates(tm.read_part(part).decode("utf-8", "ignore"))
    except Exception:
        return []


def _group_items_by_plate(items: list[dict], plates: list[dict]):
    """Split build items across plates. Returns (grouped, unresolved).

    An item whose object is on no plate record is 'unresolved': Studio cannot say
    which plate it belongs to, and therefore cannot judge it.
    """
    owner: dict[str, int] = {}
    for plate in plates:
        for oid in plate.get("object_ids") or []:
            owner[str(oid)] = plate["ui_number"]
    grouped: dict[int, list[dict]] = {}
    unresolved: list[dict] = []
    for item in items:
        plate_no = owner.get(str(item["object_id"]))
        if plate_no is None:
            unresolved.append(item)
        else:
            grouped.setdefault(plate_no, []).append(item)
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

    items = geometry.build_item_dims(path)
    items = _printable_only(path, items)
    if not items:
        return _unavailable(
            "Studio could not read where the objects sit in this project, so it "
            "cannot check their placement. Open it in Snapmaker Orca to see the plate.")

    source_bed = _source_bed(tm)

    multi_plate = bool(plate_count and plate_count > 1)
    unresolved: list[dict] = []
    grouped: dict[int, list[dict]] = {}
    plate_fit: list[dict] = []
    if multi_plate:
        plates = _plates_from_model_settings(tm)
        grouped, unresolved_items = _group_items_by_plate(items, plates)
        unresolved = [{"object_id": i["object_id"]} for i in unresolved_items]
        plate_fit = _plate_fit(grouped, target, whose)

    reported = []
    for item in items:
        lo, hi = item["bounds"]["min"], item["bounds"]["max"]
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
            "dimensions": item["dimensions"],
            "position": {"x": round((lo[0] + hi[0]) / 2.0, 2),
                         "y": round((lo[1] + hi[1]) / 2.0, 2)},
            "off_plate": off,
            "overhang_mm": over,
            "edges": _edges_text(over) or None,
        })

    oversized_plates = [p for p in plate_fit if not p["fits"]]
    if multi_plate:
        oversized_ids = {oid for p in oversized_plates for oid in p["object_ids"]}
        for row in reported:
            if row["object_id"] in oversized_ids:
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
    fixable = (not multi_plate) and bool(off_plate) and would_fit

    if multi_plate and not off_plate:
        summary = (f"All {len(plate_fit)} plates fit {whose} printable area. Studio does "
                   "not reposition multi-plate projects — open the project in Snapmaker "
                   "Orca to arrange the plates.")
    elif multi_plate and oversized_plates:
        names = ", ".join(str(p["plate"]) for p in oversized_plates)
        summary = (f"Plate {names} does not fit {whose} printable area: "
                   f"{oversized_plates[0]['reason']}. Scale it down or split it. "
                   + MULTI_PLATE_REFUSAL)
    elif multi_plate:
        summary = MULTI_PLATE_REFUSAL
    elif not off_plate:
        summary = (f"Every object sits inside {whose} printable area."
                   if len(reported) > 1 else
                   f"The object sits inside {whose} printable area.")
    elif too_wide:
        summary = (f"{len(off_plate)} object(s) fall outside {whose} plate, and the "
                   "whole arrangement is wider than the plate — moving it cannot fix "
                   "this. Scale it down or split it across plates.")
    elif would_fit:
        summary = (f"{len(off_plate)} object(s) fall outside {whose} plate, but the "
                   "whole arrangement fits — moving it as one piece brings everything "
                   "back on, keeping the creator's layout, rotation and scale.")
    else:
        summary = (f"{len(off_plate)} object(s) fall outside {whose} plate and one "
                   "move will not fix it. Open it in Snapmaker Orca and use Arrange.")

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


def verify_only_placement_moved(source: str, moved: str) -> dict:
    """Prove the copy differs from the original in where the objects sit, and in
    nothing else.

    A move that quietly re-serialised a mesh, dropped a painted facet or rewrote a
    setting would still pass a placement check, because a placement check only
    looks at placement.
    """
    import zipfile

    from . import multipart, painted_color, placement

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

    items_before = dict(placement._BUILD_ITEM.findall(root_before))
    items_after = dict(placement._BUILD_ITEM.findall(root_after))
    check("every object is still placed", set(items_before) == set(items_after))

    deltas = set()
    same_basis = True
    for object_id, text in items_before.items():
        one = placement.parse_transform(text)
        two = placement.parse_transform(items_after.get(object_id))
        if one is None or two is None:
            same_basis = False
            break
        if one[0] != two[0] or one[1] != two[1] or one[2] != two[2]:
            same_basis = False        # a rotation or a scale crept in
            break
        deltas.add((round(two[3][0] - one[3][0], 4), round(two[3][1] - one[3][1], 4),
                    round(two[3][2] - one[3][2], 4)))
    check("nothing was rotated or rescaled", same_basis)
    check("every object moved by the same amount, in X and Y only",
          len(deltas) == 1 and abs(next(iter(deltas))[2]) <= 1e-6 if deltas else False,
          str(sorted(deltas)))

    structure = multipart.validate_archive(ThreeMF.open(moved))
    check("the moved copy still describes itself consistently",
          structure.get("ok", False), "; ".join(structure.get("problems") or ()))

    one_paint = painted_color.read_container(ThreeMF.open(source))
    two_paint = painted_color.read_container(ThreeMF.open(moved))
    check("the painting is unchanged",
          one_paint.get("painted_triangle_count") == two_paint.get("painted_triangle_count")
          and one_paint.get("slots_referenced") == two_paint.get("slots_referenced"))

    return {"passed": all(entry["pass"] for entry in checks), "checks": checks}


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
    offset_for = _uniform_offset(offset["x"], offset["y"])

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
        # The copy is left in place so a user can inspect it, but the result says
        # plainly that the move did not achieve what it was supposed to.
        return {
            "schema_version": SCHEMA_VERSION, "ok": False,
            "reason": ("Studio moved the arrangement but the copy still has objects "
                       "off the plate, so it is not safe to rely on. Open the original "
                       "in Snapmaker Orca and use Arrange."),
            "output_path": str(out), "output_name": out.name,
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
