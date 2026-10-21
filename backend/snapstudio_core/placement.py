"""Where a prepared object actually lands on the target's plate, and whether it fits.

Studio carries a source project's placement exactly, which is right: moving
somebody's arrangement without being asked is how a print ends up somewhere they
did not choose. But a placement that is legal on the bed it came from need not be
legal on the U1's. A PrusaSlicer object at build transform `10 10 10` whose mesh
runs from −10 to +10 occupies 0 to 20 mm, and the U1's printable polygon starts at
x = 0.5 and y = 1 — so half a millimetre of it is off the plate and Snapmaker Orca
files the whole object under *Outside*.

Two separate facts, and this module exists to keep them apart:

    the placement was preserved     — Studio did not move anything
    the placement does not fit      — the target cannot print it there

The second is not a fidelity loss. It is a thing worth saying, and worth offering
to fix, and never worth fixing silently.

Nothing here moves anything. `translation_to_fit` works out what a move *would*
be; writing one is `reposition.py`, and only when somebody asks.
"""
from __future__ import annotations

import json
import re
import zipfile

SCHEMA_VERSION = "placement/1"

#: The states an object's footprint can be in against the target polygon. They are
#: kept apart because "outside" is four different problems with four different
#: answers, and one of them has no answer at all.
INSIDE = "inside"
TOUCHING_BOUNDARY = "touching_boundary"
PARTLY_OUTSIDE = "partly_outside"
FULLY_OUTSIDE = "fully_outside"
TOO_LARGE_TO_FIT = "too_large_to_fit"
UNKNOWN = "unknown"

PROJECT_SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
ROOT_MODEL = "3D/3dmodel.model"
OBJECTS_DIR = "3D/Objects/"

#: Half a micron. Coordinates arrive as decimal text from two different writers, so
#: an exact equality test on a boundary would call a model that sits precisely on
#: the edge "outside" because of the last digit.
TOLERANCE = 5e-4

_VERTEX = re.compile(r'<vertex[^>]*x="([^"]*)"[^>]*y="([^"]*)"[^>]*z="([^"]*)"')
_OBJECT_WITH_ID = re.compile(r'<object[^>]* id="([0-9]+)"[^>]*>.*?</object>', re.S)
_OBJECT_BLOCK = re.compile(r"<object[^>]*>.*?</object>", re.S)
_COMPONENT = re.compile(r'<component[^>]* objectid="([0-9]+)"[^>]*'
                        r'(?: transform="([^"]*)")?[^>]*/>')
_BUILD_ITEM = re.compile(r'<item[^>]* objectid="([0-9]+)"[^>]*'
                         r' transform="([^"]*)"')


# --- transforms ---------------------------------------------------------------
#
# 3MF writes a transform as twelve numbers: the three basis vectors and then the
# translation, all row-major. `model_settings.config` writes a part's matrix as
# sixteen, and the same twelve live in its first three rows of four. Reading the
# wrong twelve is how a rotation becomes a translation, so both shapes are named.

def parse_transform(text: str | None) -> tuple | None:
    """A 3MF transform as ((a, b, c), (d, e, f), (g, h, i), (tx, ty, tz))."""
    if not text:
        return None
    try:
        values = [float(token) for token in text.replace(",", " ").split()]
    except ValueError:
        return None
    if len(values) == 12:
        rows = values
    elif len(values) == 16:
        # A part matrix: four rows of four, the last column the translation.
        rows = [values[0], values[1], values[2],
                values[4], values[5], values[6],
                values[8], values[9], values[10],
                values[3], values[7], values[11]]
    else:
        return None
    return ((rows[0], rows[1], rows[2]), (rows[3], rows[4], rows[5]),
            (rows[6], rows[7], rows[8]), (rows[9], rows[10], rows[11]))


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))


def apply(transform: tuple | None, point: tuple) -> tuple:
    """One point through one transform."""
    if transform is None:
        return point
    (a, b, c), (d, e, f), (g, h, i), (tx, ty, tz) = transform
    x, y, z = point
    return (a * x + d * y + g * z + tx,
            b * x + e * y + h * z + ty,
            c * x + f * y + i * z + tz)


def compose(outer: tuple | None, inner: tuple | None) -> tuple | None:
    """`outer` applied after `inner`, as one transform.

    Composing rather than applying twice is what keeps a matrix from being used
    on coordinates it has already been used on.
    """
    if outer is None:
        return inner
    if inner is None:
        return outer
    basis = []
    for row in range(3):
        vector = (inner[row][0], inner[row][1], inner[row][2])
        (a, b, c), (d, e, f), (g, h, i), _t = outer
        basis.append((a * vector[0] + d * vector[1] + g * vector[2],
                      b * vector[0] + e * vector[1] + h * vector[2],
                      c * vector[0] + f * vector[1] + i * vector[2]))
    moved = apply(outer, inner[3])
    return (basis[0], basis[1], basis[2], moved)


def translated(transform: tuple | None, dx: float, dy: float) -> tuple:
    """The same transform, moved in X and Y and in nothing else."""
    base = transform or IDENTITY
    return (base[0], base[1], base[2],
            (base[3][0] + dx, base[3][1] + dy, base[3][2]))


def format_transform(transform: tuple) -> str:
    """Back to the twelve numbers a 3MF build item carries."""
    numbers = list(transform[0]) + list(transform[1]) + list(transform[2]) + list(
        transform[3])
    return " ".join(_number(value) for value in numbers)


def _number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(round(value, 6))


# --- the target's printable polygon -------------------------------------------

def polygon_of(project_settings: dict | None) -> list[tuple] | None:
    """The printable outline the project itself states, in millimetres.

    Read from the project rather than from a remembered number, because that is
    the polygon Snapmaker Orca will judge the file against. It is a polygon and
    not a width and a depth: today's U1 outline happens to be a rectangle, and
    treating every bed as one would quietly mis-answer the first that is not.
    """
    if not isinstance(project_settings, dict):
        return None
    area = project_settings.get("printable_area")
    if not isinstance(area, list) or len(area) < 3:
        return None
    points = []
    for entry in area:
        try:
            x, y = str(entry).lower().split("x")
            points.append((float(x), float(y)))
        except (ValueError, AttributeError):
            return None
    return points


def bounds_of(polygon: list[tuple]) -> tuple:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _inside_polygon(point: tuple, polygon: list[tuple]) -> bool:
    """Ray casting, with points on an edge counted as inside."""
    x, y = point
    if _on_boundary(point, polygon):
        return True
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def _on_boundary(point: tuple, polygon: list[tuple]) -> bool:
    x, y = point
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if abs(cross) > TOLERANCE:
            continue
        if (min(x1, x2) - TOLERANCE <= x <= max(x1, x2) + TOLERANCE
                and min(y1, y2) - TOLERANCE <= y <= max(y1, y2) + TOLERANCE):
            return True
    return False


# --- what a prepared project puts where ---------------------------------------

def _read(archive: zipfile.ZipFile, name: str) -> str:
    try:
        return archive.read(name).decode("utf-8", "ignore")
    except KeyError:
        return ""


def read_objects(path: str) -> dict:
    """Every logical object in a prepared project, with its footprint on the plate.

    The footprint is the printable geometry only. A modifier or a support blocker
    is a instruction to the slicer rather than something that prints, and letting
    one push an otherwise valid arrangement off the plate would be reporting a
    problem the plate does not have. Whether the target agrees is a question for
    the target, and it is recorded in the project's own documentation.
    """
    from . import multipart

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        root = _read(archive, ROOT_MODEL)
        settings_text = _read(archive, MODEL_SETTINGS)
        try:
            project = json.loads(_read(archive, PROJECT_SETTINGS) or "{}")
        except json.JSONDecodeError:
            project = {}
        meshes: dict[str, list[tuple]] = {}
        for name in sorted(n for n in names if n.startswith(OBJECTS_DIR)):
            body = _read(archive, name)
            for mesh_id in re.findall(r'<object id="([0-9]+)"', body):
                block = re.search(rf'<object id="{mesh_id}".*?</object>', body, re.S)
                if block:
                    meshes[mesh_id] = _points(block.group(0))
        if not meshes:
            # A project whose geometry is still in the root model.
            for mesh_id, block in zip(_OBJECT_WITH_ID.findall(root),
                                      _OBJECT_BLOCK.findall(root)):
                meshes[mesh_id] = _points(block)

    polygon = polygon_of(project)
    parts_by_object = multipart._parts_by_object(settings_text) if settings_text else {}
    placements = dict(_BUILD_ITEM.findall(root))
    components = _components_by_object(root)

    objects = []
    for object_id, transform_text in placements.items():
        item = parse_transform(transform_text)
        part_ids = [part_id for part_id, _subtype in parts_by_object.get(object_id, [])]
        roles = dict(parts_by_object.get(object_id, []))
        own_components = components.get(object_id) or [
            (part_id, None) for part_id in part_ids]
        printable: list[tuple] = []
        every: list[tuple] = []
        for mesh_id, component_transform in own_components:
            points = meshes.get(mesh_id)
            if points is None:
                continue
            whole = compose(item, parse_transform(component_transform))
            moved = [apply(whole, point) for point in points]
            every.extend(moved)
            if roles.get(mesh_id, "normal_part") == "normal_part":
                printable.extend(moved)
        objects.append({
            "object_id": object_id,
            "name": _name_of(settings_text, object_id),
            "transform": transform_text,
            "part_ids": part_ids,
            "footprint": _footprint(printable),
            "footprint_with_helpers": _footprint(every),
            "printable_points": [(x, y) for x, y, _z in printable],
        })

    return {"schema_version": SCHEMA_VERSION, "objects": objects,
            "polygon": polygon,
            "polygon_source": PROJECT_SETTINGS if polygon else None}


def _components_by_object(root: str) -> dict:
    out: dict[str, list] = {}
    for match in re.finditer(
            r'<object id="([0-9]+)"[^>]*>\s*<components>(.*?)</components>', root, re.S):
        entries = []
        for component in re.findall(r"<component[^>]*/>", match.group(2)):
            mesh_id = re.search(r'objectid="([0-9]+)"', component)
            transform = re.search(r'transform="([^"]*)"', component)
            if mesh_id:
                entries.append((mesh_id.group(1),
                                transform.group(1) if transform else None))
        out[match.group(1)] = entries
    return out


def _name_of(settings: str, object_id: str) -> str | None:
    match = re.search(rf'<object id="{object_id}">(.*?)(?=<part |</object>)',
                      settings, re.S)
    if not match:
        return None
    found = re.search(r'key="name" value="([^"]*)"', match.group(1))
    return found.group(1) if found else None


def _points(block: str) -> list[tuple]:
    return [(float(x), float(y), float(z)) for x, y, z in _VERTEX.findall(block)]


def _footprint(points: list[tuple]) -> dict | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys),
            "width": max(xs) - min(xs), "depth": max(ys) - min(ys)}


# --- does it fit --------------------------------------------------------------

def classify(footprint: dict | None, polygon: list[tuple] | None,
             points: list[tuple] | None = None) -> dict:
    """Where this footprint stands against the target's printable outline."""
    if footprint is None or not polygon:
        return {"status": UNKNOWN,
                "reason": ("Studio could not work out where this object sits, or what "
                           "the printer's printable area is")}

    left, front, right, back = bounds_of(polygon)
    corners = [(footprint["min_x"], footprint["min_y"]),
               (footprint["max_x"], footprint["min_y"]),
               (footprint["max_x"], footprint["max_y"]),
               (footprint["min_x"], footprint["max_y"])]
    tested = points if points else corners
    inside = [_inside_polygon(point, polygon) for point in tested]

    excess = {
        "left": max(0.0, left - footprint["min_x"]),
        "right": max(0.0, footprint["max_x"] - right),
        "front": max(0.0, front - footprint["min_y"]),
        "back": max(0.0, footprint["max_y"] - back),
    }
    excess = {side: round(value, 4) for side, value in excess.items() if value > TOLERANCE}

    if footprint["width"] > (right - left) + TOLERANCE or \
            footprint["depth"] > (back - front) + TOLERANCE:
        return {"status": TOO_LARGE_TO_FIT, "excess_mm": excess,
                "reason": ("this object is larger than the printable area, so no amount "
                           "of moving it will make it fit"),
                "fits_by_translation": False}

    if all(inside) and not excess:
        touching = any(_on_boundary(point, polygon) for point in corners)
        return {"status": TOUCHING_BOUNDARY if touching else INSIDE,
                "excess_mm": {}, "fits_by_translation": True}
    if not any(inside):
        return {"status": FULLY_OUTSIDE, "excess_mm": excess,
                "fits_by_translation": True}
    return {"status": PARTLY_OUTSIDE, "excess_mm": excess, "fits_by_translation": True}


SIDE_WORDS = {"left": "the left", "right": "the right",
              "front": "the front", "back": "the back"}


def describe(name: str | None, verdict: dict, printer: str = "printer") -> str:
    """One sentence a beginner can act on."""
    label = name or "This object"
    status = verdict.get("status")
    if status in (INSIDE, TOUCHING_BOUNDARY):
        return f"{label} is on the {printer} plate."
    if status == TOO_LARGE_TO_FIT:
        return f"{label} is larger than the {printer} printable area."
    if status == UNKNOWN:
        return f"Studio cannot tell whether {label} is on the {printer} plate."
    excess = verdict.get("excess_mm") or {}
    if len(excess) == 1:
        side, amount = next(iter(excess.items()))
        return (f"{label} is {amount:g} mm outside the {printer} printable area on "
                f"{SIDE_WORDS[side]}.")
    return f"{label} extends outside the {printer} printable area."


# --- can one move fix the whole plate -----------------------------------------

def translation_to_fit(objects: list[dict], polygon: list[tuple] | None) -> dict:
    """The single move that would put every printable object on the plate.

    One translation for the whole arrangement, so the objects keep the distances
    and orientation somebody chose for them. Rotating, rescaling or re-packing
    them would answer a question nobody asked.

    The move is the smallest one that works and is the same on every run: the
    shortest distance, and where two are equally short, the one that moves in X.
    """
    if not polygon:
        return {"possible": False, "reason": "the printer's printable area is unknown"}
    footprints = [entry["footprint"] for entry in objects if entry.get("footprint")]
    if not footprints:
        return {"possible": False, "reason": "no printable geometry to place"}

    left, front, right, back = bounds_of(polygon)
    min_x = min(f["min_x"] for f in footprints)
    min_y = min(f["min_y"] for f in footprints)
    max_x = max(f["max_x"] for f in footprints)
    max_y = max(f["max_y"] for f in footprints)

    if (max_x - min_x) > (right - left) + TOLERANCE or \
            (max_y - min_y) > (back - front) + TOLERANCE:
        return {"possible": False,
                "reason": ("the arrangement is wider or deeper than the printable "
                           "area, so it cannot fit without changing the spacing "
                           "between objects"),
                "too_large": True}

    # The window of translations that lands the whole arrangement inside, then the
    # point in it closest to not moving at all.
    dx = _clamp(0.0, left - min_x, right - max_x)
    dy = _clamp(0.0, front - min_y, back - max_y)
    dx, dy = round(dx, 4), round(dy, 4)
    return {"possible": True, "dx": dx, "dy": dy,
            "moves": abs(dx) > TOLERANCE or abs(dy) > TOLERANCE}


def _clamp(value: float, low: float, high: float) -> float:
    """The number in [low, high] nearest `value`, with an empty range meaning 0."""
    if low > high:
        return 0.0
    return max(low, min(high, value))


# --- the whole project --------------------------------------------------------

def assess(path: str, printer: str = "Snapmaker U1") -> dict:
    """Every object's placement against the target's plate, and what it would take.

    Never moves anything, and never reports a preserved placement as a change.
    Where an object sits and whether the target can print it there are two facts,
    and this returns both.
    """
    try:
        read = read_objects(path)
    except Exception as exc:  # noqa: BLE001 — a report, never a crash
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": f"Studio could not read the prepared copy: {exc}"}

    polygon = read["polygon"]
    if not polygon:
        return {"schema_version": SCHEMA_VERSION, "available": False,
                "reason": ("this project records no printable area, so Studio cannot "
                           "say whether anything is on the plate")}

    objects = []
    for entry in read["objects"]:
        verdict = classify(entry["footprint"], polygon, entry.get("printable_points"))
        objects.append({
            "object_id": entry["object_id"],
            "name": entry["name"],
            "transform": entry["transform"],
            "footprint_mm": _rounded(entry["footprint"]),
            "status": verdict["status"],
            "excess_mm": verdict.get("excess_mm") or {},
            "fits_by_translation": verdict.get("fits_by_translation"),
            "message": describe(entry["name"], verdict, printer),
            "reason": verdict.get("reason"),
        })

    move = translation_to_fit(read["objects"], polygon)
    outside = [entry for entry in objects
               if entry["status"] in (PARTLY_OUTSIDE, FULLY_OUTSIDE)]
    too_large = [entry for entry in objects if entry["status"] == TOO_LARGE_TO_FIT]

    if too_large:
        summary = (f"{len(too_large)} object(s) are larger than the {printer} "
                   "printable area. Moving cannot fix that.")
    elif not outside:
        summary = f"Every object is on the {printer} plate."
    elif move.get("possible") and move.get("moves"):
        summary = (f"{len(outside)} object(s) sit outside the {printer} printable "
                   f"area. The whole arrangement fits if it moves "
                   f"{_offset(move['dx'], move['dy'])}.")
    else:
        summary = (f"{len(outside)} object(s) sit outside the {printer} printable "
                   "area, and the arrangement cannot fit without changing the "
                   "spacing between objects.")

    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "printer": printer,
        "polygon": polygon,
        "polygon_source": read["polygon_source"],
        "objects": objects,
        "objects_total": len(objects),
        "objects_outside": len(outside),
        "objects_too_large": len(too_large),
        "all_inside": not outside and not too_large,
        "rigid_move": move,
        "summary": summary,
    }


def _offset(dx: float, dy: float) -> str:
    parts = []
    if abs(dx) > TOLERANCE:
        parts.append(f"{dx:+g} mm X")
    if abs(dy) > TOLERANCE:
        parts.append(f"{dy:+g} mm Y")
    return " · ".join(parts) or "nowhere"


def _rounded(footprint: dict | None) -> dict | None:
    if not footprint:
        return None
    return {key: round(value, 4) for key, value in footprint.items()}
