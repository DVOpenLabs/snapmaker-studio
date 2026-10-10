"""Which filament each object is assigned to, in whichever dialect says so.

A project's per-object filament assignment is the quietest thing a converter can
destroy. The mesh survives, the file opens, the colours are all still listed —
and every object prints in filament 1. Studio did exactly that to every
PrusaSlicer project it prepared: an object assigned filament 3 arrived assigned
filament 1, with nothing anywhere saying so.

So the assignment is read as a fact in its own right, from both dialects, in a
shape that can be compared across the crossing:

* **PrusaSlicer** — `Metadata/Slic3r_PE_model.config`, objects carrying
  `<metadata type="object" key="extruder">`, with volumes able to carry their own.
* **Bambu / Orca / Snapmaker Orca** — `Metadata/model_settings.config`, objects
  and their parts carrying `<metadata key="extruder">`.

Two distinctions are kept rather than flattened. An object with no assignment is
*default*, which is not the same claim as an object explicitly assigned slot 1.
And an object whose volumes disagree cannot be represented as a single U1 part,
which is a real limit of the crossing and is reported as one — never resolved by
picking a volume and hoping.
"""
from __future__ import annotations

import re

from .container import ThreeMF

PRUSA_CONFIG = "Metadata/Slic3r_PE_model.config"
BAMBU_CONFIG = "Metadata/model_settings.config"

DIALECT_PRUSA = "prusa"
DIALECT_BAMBU = "bambu"

# How an object's slot came to be what it is.
EXPLICIT = "explicit"      # the object says so itself
FROM_VOLUME = "from_volume"  # its volumes agree and the object is silent
DEFAULT = "default"        # nothing says, so the project's first filament

# What a volume is *for*. Both dialects record this and both have their own
# vocabulary for it, so it is normalised here — a modifier is a modifier whether
# the file calls it a ParameterModifier or a modifier_part.
#
# The names on each side were established by round-tripping files through the
# slicers themselves (see docs/internal/PRUSA_SEMANTICS.md), not read off a wiki:
# PrusaSlicer 2.9.6 writes ModelPart / ParameterModifier / NegativeVolume /
# SupportEnforcer / SupportBlocker, and silently rewrites anything it does not
# recognise to ModelPart. Snapmaker Orca 2.3.5 writes `subtype="normal_part"`.
PART = "part"
MODIFIER = "modifier"
NEGATIVE = "negative"
SUPPORT_ENFORCER = "support_enforcer"
SUPPORT_BLOCKER = "support_blocker"
ROLE_UNKNOWN = "unknown"

_ROLES = {
    # PrusaSlicer
    "modelpart": PART,
    "parametermodifier": MODIFIER,
    "negativevolume": NEGATIVE,
    "supportenforcer": SUPPORT_ENFORCER,
    "supportblocker": SUPPORT_BLOCKER,
    # Bambu / Orca / Snapmaker Orca
    "normal_part": PART,
    "modifier_part": MODIFIER,
    "negative_part": NEGATIVE,
    "support_enforcer": SUPPORT_ENFORCER,
    "support_blocker": SUPPORT_BLOCKER,
}

#: Object-level keys that are the assignment itself or the object's identity,
#: rather than a setting somebody overrode on this object.
_NOT_AN_OVERRIDE = {"extruder", "name", "matrix", "source_file", "source_object_id",
                    "source_volume_id", "source_offset_x", "source_offset_y",
                    "source_offset_z", "volume_type", "subtype"}


def role_of(value: str | None) -> str:
    """Normalise a dialect's volume-role word, or say it is not one Studio knows.

    An unrecognised role is *not* quietly a part. PrusaSlicer itself converts an
    unknown `volume_type` into `ModelPart`, which turns a modifier into printable
    geometry — exactly the failure this vocabulary exists to make visible.
    """
    if value is None:
        return ROLE_UNKNOWN
    return _ROLES.get(str(value).strip().lower(), ROLE_UNKNOWN)

_OBJECT = re.compile(r"<object\b")
_VOLUME = re.compile(r"<volume\b")
_PART = re.compile(r"<part\b")
_ID = re.compile(r'id="([^"]+)"')
_INSTANCES = re.compile(r'instances_count="(\d+)"')
_SUBTYPE = re.compile(r'subtype="([^"]+)"')
_PRUSA_META = re.compile(
    r'<metadata\s+type="(object|volume|part)"\s+key="([^"]+)"\s+value="([^"]*)"')
_BAMBU_META = re.compile(r'<metadata\s+key="([^"]+)"\s+value="([^"]*)"')


#: Beyond this a value is not a filament slot, it is a corrupted number. Slicers
#: cap filaments far below it; nothing sane lands here, and an unbounded integer
#: from someone else's file has no business being carried as an assignment.
MAX_SLOT = 999


def _int(value: str):
    """A slot number, or nothing.

    `str.isdigit()` is true for Unicode digits, so "٣" would arrive as slot 3 —
    a silent normalisation of a value no slicer wrote, which is exactly the class
    of quiet wrongness this module exists to avoid. ASCII only, and bounded.
    """
    value = (value or "").strip()
    if not value or not all("0" <= c <= "9" for c in value):
        return None
    number = int(value)
    return number if 0 <= number <= MAX_SLOT else None


def _read(tm: ThreeMF, part: str) -> str | None:
    if not tm.has_part(part):
        return None
    try:
        return tm.read_part(part).decode("utf-8", "ignore")
    except Exception:
        return None


def _own_body(chunk: str) -> str:
    """One object's own text, stopping where the object does.

    Splitting on `<object` alone runs the last object to the end of the file, so
    an object with no parts swallowed the `<plate>` block that follows it and
    `plater_id` arrived as a setting somebody had overridden on that object. The
    closing tag is the boundary; a chunk without one is the whole of what is left.
    """
    return chunk.split("</object>", 1)[0]


def _prusa(text: str) -> list[dict]:
    out = []
    chunks = [_own_body(c) for c in re.split(_OBJECT, text)[1:]]
    for position, chunk in enumerate(chunks):
        head = chunk.split(">", 1)[0]
        found = _ID.search(head)
        entry = {"object_id": found.group(1) if found else str(position + 1),
                 "index": position, "name": None, "slot": None,
                 "source": DEFAULT, "volume_slots": [], "volumes": [],
                 # Zero placements is not a statement, it is a broken one.
                 "instances": (_int(_INSTANCES.search(head).group(1)) or None)
                              if _INSTANCES.search(head) else None,
                 "overrides": {}, "dialect": DIALECT_PRUSA}
        for kind, key, value in _PRUSA_META.findall(chunk.split("<volume", 1)[0]):
            if key == "extruder":
                slot = _int(value)
                if slot:
                    entry["slot"], entry["source"] = slot, EXPLICIT
            elif key == "name" and entry["name"] is None:
                entry["name"] = value
            elif key not in _NOT_AN_OVERRIDE:
                # A setting somebody changed on this object alone. Recorded as a
                # fact; whether it can cross is decided later and separately.
                entry["overrides"][key] = value
        for order, volume in enumerate(re.split(_VOLUME, chunk)[1:]):
            slot = None
            name = None
            role_word = None
            for _kind, key, value in _PRUSA_META.findall(volume):
                if key == "extruder":
                    slot = _int(value) or slot
                elif key == "name" and name is None:
                    name = value
                elif key == "volume_type":
                    role_word = value
            entry["volume_slots"].append(slot)
            entry["volumes"].append({"index": order, "name": name, "slot": slot,
                                     "role": role_of(role_word),
                                     "role_word": role_word})
        if entry["slot"] is None:
            stated = {slot for slot in entry["volume_slots"] if slot}
            if len(stated) == 1:
                entry["slot"], entry["source"] = stated.pop(), FROM_VOLUME
        out.append(entry)
    return out


def _bambu(text: str) -> list[dict]:
    out = []
    for position, chunk in enumerate(_own_body(c) for c in re.split(_OBJECT, text)[1:]):
        head = chunk.split(">", 1)[0]
        found = _ID.search(head)
        entry = {"object_id": found.group(1) if found else str(position + 1),
                 "index": position, "name": None, "slot": None,
                 "source": DEFAULT, "volume_slots": [], "volumes": [],
                 "instances": None, "overrides": {}}
        for key, value in _BAMBU_META.findall(chunk.split("<part", 1)[0]):
            if key == "extruder":
                # Snapmaker Orca writes `extruder="0"` for an object nobody has
                # assigned — its own way of saying default, seen in a file Orca
                # 2.3.5 wrote itself. Zero is therefore not slot zero.
                slot = _int(value)
                if slot:
                    entry["slot"], entry["source"] = slot, EXPLICIT
            elif key == "name" and entry["name"] is None:
                entry["name"] = value
            elif key not in _NOT_AN_OVERRIDE:
                entry["overrides"][key] = value
        for order, part in enumerate(re.split(_PART, chunk)[1:]):
            head_part = part.split(">", 1)[0]
            subtype = _SUBTYPE.search(head_part)
            slot = None
            name = None
            for key, value in _BAMBU_META.findall(part):
                if key == "extruder":
                    slot = _int(value) or slot
                elif key == "name" and name is None:
                    name = value
            entry["volume_slots"].append(slot)
            entry["volumes"].append({"index": order, "name": name, "slot": slot,
                                     "role": role_of(subtype.group(1) if subtype else None),
                                     "role_word": subtype.group(1) if subtype else None})
        out.append(entry)
    return out


MODEL_PART = "3D/3dmodel.model"
_BUILD_ITEM = re.compile(r'<item\s[^>]*objectid="([^"]+)"')


def _instances_from_build(tm: ThreeMF) -> dict[str, int]:
    """How many times each object id appears in the build, when that is readable.

    Two facts, both measured against PrusaSlicer 2.9.6, and they pull in different
    directions:

    * a config claiming three instances against a build holding one item came back
      claiming one — so the config cannot invent placements the build does not
      have;
    * three build items came back as three *separate* objects with their own ids,
      not as one object placed three times — so the build's object ids do not map
      one-to-one onto the config's.

    The slicer maintains `instances_count` truthfully against the build it has, so
    that is the statement to believe. This counting is the fallback for a file that
    does not carry one, and it is only meaningful when the ids line up.
    """
    text = _read(tm, MODEL_PART)
    if text is None:
        return {}
    counts: dict[str, int] = {}
    for object_id in _BUILD_ITEM.findall(text):
        counts[object_id] = counts.get(object_id, 0) + 1
    return counts


def _with_instances(objects: list[dict], counts: dict[str, int]) -> list[dict]:
    """Fill in a placement count only where the file did not state one."""
    for entry in objects:
        if entry.get("instances") is not None:
            continue
        placed = counts.get(str(entry.get("object_id")))
        if placed is not None:
            entry["instances"] = placed
    return objects


def read(tm: ThreeMF) -> dict:
    """Every object's filament assignment, from whichever dialect the file speaks."""
    counts = _instances_from_build(tm)
    prusa = _read(tm, PRUSA_CONFIG)
    if prusa is not None:
        return {"available": True, "dialect": DIALECT_PRUSA,
                "objects": _with_instances(_prusa(prusa), counts)}
    bambu = _read(tm, BAMBU_CONFIG)
    if bambu is not None:
        return {"available": True, "dialect": DIALECT_BAMBU,
                "objects": _with_instances(_bambu(bambu), counts)}
    return {"available": False, "dialect": None, "objects": [],
            "reason": "this project records no per-object filament assignment"}


# --- comparing one side with the other ---------------------------------------

PRESERVED = "preserved"
CHANGED = "changed"
LOST = "lost"
NOT_REPRESENTABLE = "not_representable"
UNKNOWN = "unknown"


def compare(before: dict, after: dict, filaments: int = 1) -> dict:
    """Object by object, what happened to the assignment.

    Objects are matched by position, because the two dialects number objects
    differently and preparing a copy renames them: a Prusa object id and a U1
    object id that happen to share a number are not the same claim. Position is
    the one thing the crossing preserves, and where the counts differ the extra
    objects are reported as unknown rather than paired up hopefully.
    """
    if not before.get("available") or not after.get("available"):
        return {"available": False, "rows": [],
                "reason": "one side records no assignments to compare"}

    rows = []
    source_objects = before["objects"]
    prepared_objects = after["objects"]
    for index, source in enumerate(source_objects):
        prepared = prepared_objects[index] if index < len(prepared_objects) else None
        name = source.get("name") or f"object {index + 1}"
        if prepared is None:
            rows.append({"object": name, "index": index, "from": source["slot"],
                         "to": None, "status": UNKNOWN,
                         "detail": "this object is not in the prepared copy"})
            continue
        wanted = source["slot"]
        got = prepared["slot"]
        if wanted is None and source["source"] == DEFAULT:
            # "Nobody assigned this" and "somebody chose filament 1" are different
            # source facts, and PrusaSlicer keeps them apart: given a file with no
            # extruder metadata it writes none back, and given `extruder="1"` it
            # writes that explicitly rather than dropping it as redundant. Both
            # were verified by round-tripping through PrusaSlicer 2.9.6 itself.
            # Snapmaker Orca says the same thing its own way, writing
            # `extruder="0"` for an object nobody has assigned.
            #
            # So a copy that turns the first into the second has changed what the
            # project says, even though both happen to print from filament 1 under
            # today's defaults. Calling that "preserved" is how an assignment
            # silently becomes a decision Studio made.
            if got is None:
                status = PRESERVED
                detail = "no filament was assigned, and none is assigned in the copy"
            else:
                status = CHANGED
                detail = (f"the source assigns no filament; the copy states slot {got}. "
                          "Both print from filament 1 today, but the copy now claims a "
                          "choice the project never made")
        elif wanted == got:
            status = PRESERVED
            detail = (f"slot {wanted} carried over"
                      + (" (stated by the object's volume)"
                         if source["source"] == FROM_VOLUME else ""))
        elif got is None:
            status = LOST
            detail = f"the source assigns slot {wanted}; the copy assigns none"
        else:
            status = CHANGED
            detail = f"slot {wanted} → slot {got}"
        row = {"object": name, "index": index, "from": wanted, "to": got,
               "status": status, "detail": detail,
               "from_source": source["source"]}
        stated = {slot for slot in source.get("volume_slots") or [] if slot}
        carried = {slot for slot in prepared.get("volume_slots") or [] if slot}
        if len(stated) > 1 and carried == stated:
            # The copy holds real parts with these filaments. The object's own
            # slot is a separate fact and has already been judged above; this
            # object is not the "cannot be represented" case any more, and saying
            # it is would report a loss that did not happen.
            row["detail"] = (row["detail"] + "; each part keeps its own filament "
                             + f"({sorted(stated)})")
        elif len(stated) > 1:
            # A U1 object is one part. Volumes that disagree cannot all be
            # represented, and that is a fact about the crossing, not a defect.
            row["status"] = NOT_REPRESENTABLE
            row["detail"] = (
                f"this object's volumes use filaments {sorted(stated)}, and a "
                "prepared U1 object is a single part — the object's own slot "
                f"({wanted}) is carried and the rest cannot be represented")
        rows.append(row)

    semantics = _semantic_rows(source_objects, prepared_objects, filaments)

    for index in range(len(source_objects), len(prepared_objects)):
        prepared = prepared_objects[index]
        rows.append({"object": prepared.get("name") or f"object {index + 1}",
                     "index": index, "from": None, "to": prepared["slot"],
                     "status": UNKNOWN,
                     "detail": "this object is only in the prepared copy"})

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"available": True, "rows": rows, "semantics": semantics, "counts": counts,
            "all_preserved": all(row["status"] == PRESERVED for row in rows),
            "source_dialect": before.get("dialect"),
            "prepared_dialect": after.get("dialect")}


# --- the facts underneath the assignment -------------------------------------

PRESERVED_EXACT = "preserved_exact"
PRESERVED_SEMANTIC = "preserved_semantic"
UNSUPPORTED = "unsupported"
UNVERIFIED = "unverified"


def _flattened(source_objects: list[dict], prepared_objects: list[dict]) -> bool:
    """Did the copy turn instances into separate objects, keeping every placement?

    True only when the arithmetic works out exactly: the prepared side holds one
    object per source placement, each placed once. Anything else is a genuine
    difference in count and is reported as one.
    """
    placements = sum((entry.get("instances") or 1) for entry in source_objects)
    if len(prepared_objects) != placements or placements == len(source_objects):
        return False
    return all((entry.get("instances") or 1) == 1 for entry in prepared_objects)


def _semantic_rows(source_objects: list[dict], prepared_objects: list[dict],
                   filaments: int = 1) -> list[dict]:
    """Volumes, roles, instances and overrides, each answered for itself.

    One row saying "objects preserved" is how a copy passes an audit while the
    structure underneath it has changed. A volume's filament, a modifier's role,
    how many instances were on the plate and a setting somebody overrode are four
    separate claims, and each is either carried or it is not.

    Nothing here decides *what to do* about a loss. It reports what happened, in
    the vocabulary the fidelity card and the tests both read.
    """
    rows: list[dict] = []
    for index, source in enumerate(source_objects):
        prepared = prepared_objects[index] if index < len(prepared_objects) else None
        name = source.get("name") or f"object {index + 1}"
        if prepared is None:
            continue

        # --- volumes ---------------------------------------------------------
        source_volumes = source.get("volumes") or []
        prepared_volumes = prepared.get("volumes") or []
        stated = [v for v in source_volumes if v.get("slot")]
        if stated:
            carried = {v.get("slot") for v in prepared_volumes if v.get("slot")}
            wanted = {v["slot"] for v in stated}
            if wanted == carried:
                status, detail = PRESERVED_EXACT, (
                    f"every part keeps its filament ({sorted(wanted)})")
            elif len(wanted) > 1 and len(prepared_volumes) <= 1:
                # The target format can hold this — a Snapmaker Orca project can
                # carry many parts on different filaments, seen in files Orca
                # wrote. What cannot is Studio's own prepare path, which writes
                # one part per object. That is a limit of this tool, and it is
                # reported as one rather than as a limit of the format.
                status, detail = UNSUPPORTED, (
                    ", ".join(f"part {v['index'] + 1} uses filament {v['slot']}"
                              for v in stated)
                    + ". The prepared U1 copy holds one part per object, so it cannot "
                      "carry both — Studio does not choose one for you")
            else:
                status, detail = CHANGED, (
                    f"the source parts use filaments {sorted(wanted)}; "
                    f"the copy uses {sorted(carried) or 'none'}")
            rows.append({"object": name, "index": index, "kind": "volume_filament",
                         "status": status, "detail": detail})

        # --- roles -----------------------------------------------------------
        special = [v for v in source_volumes if v.get("role") not in (PART, None)]
        if special:
            # Position matters. Asking only whether the role appears *somewhere*
            # in the copy passes a file where two parts swapped roles — the
            # modifier printing and the solid vanishing — which is the exact
            # failure the row exists to catch.
            by_position = {v.get("index"): v.get("role") for v in prepared_volumes}
            elsewhere = {v.get("role") for v in prepared_volumes}
            for volume in special:
                here = by_position.get(volume["index"])
                if here == volume["role"]:
                    status, detail = PRESERVED_EXACT, (
                        f"part {volume['index'] + 1} is a {volume['role']} in both")
                elif volume["role"] in elsewhere:
                    status, detail = CHANGED, (
                        f"part {volume['index'] + 1} is a {volume['role']} in the source "
                        f"and a {here or 'part with no role'} in the copy; the role is on "
                        "a different part there")
                else:
                    status, detail = UNSUPPORTED, (
                        f"part {volume['index'] + 1} is a {volume['role']} and the prepared "
                        "copy has no such part. Its shape is still in the object, so "
                        "Snapmaker Orca will treat it as solid and print it. Remove it "
                        "there, or keep slicing this one in PrusaSlicer")
                rows.append({"object": name, "index": index, "kind": "volume_role",
                             "status": status, "detail": detail})

        # --- instances -------------------------------------------------------
        before, after = source.get("instances"), prepared.get("instances")
        if before is not None and before > 1 and _flattened(source_objects, prepared_objects):
            # Prepare writes one object per placement: a source holding one object
            # placed three times becomes three objects placed once each. The plate
            # is the same and every copy is still there — what is lost is the
            # record that they were copies of one thing. That is a real change to
            # the project's structure and a real preservation of what will print,
            # so it is neither "exact" nor "changed".
            rows.append({
                "object": name, "index": index, "kind": "instances",
                "status": PRESERVED_SEMANTIC,
                "detail": (f"{before} copies of this object are all on the plate, but the "
                           "copy records them as separate objects rather than as copies "
                           "of one")})
        elif before is not None and before > 1:
            rows.append({
                "object": name, "index": index, "kind": "instances",
                "status": (PRESERVED_EXACT if after == before else
                           UNVERIFIED if after is None else CHANGED),
                "detail": (f"{before} copies on the plate"
                           if after == before else
                           "Studio could not count the copies in the prepared file"
                           if after is None else
                           f"the source places {before} copies; the copy places {after}")})

        # --- per-object overrides --------------------------------------------
        rows.extend(_override_rows(source, prepared, name, index, filaments))
    return rows


def _override_rows(source: dict, prepared: dict, name: str, index: int,
                   filaments: int = 1) -> list[dict]:
    """One row per per-object setting, on both sides of the crossing.

    The source key and the target key are not the same word for two of the three
    settings Studio carries, so asking "is the source's key still there" answers
    the wrong question: it reports a carried setting as lost. Each row states
    what the source said, what the copy says, and in which vocabulary.

    A setting the copy states that the source never did is its own failure and
    gets its own row. A prepared copy inventing a per-object setting would change
    what prints, and no audit should let that pass as "preserved".
    """
    from . import overrides as object_overrides

    source_overrides = dict(source.get("overrides") or {})
    kept = dict(prepared.get("overrides") or {})
    rows: list[dict] = []

    # Settings that arrive in Snapmaker Orca's own words are kept as they are, not
    # translated: compare them key for key, before the translation table sees them.
    # Only a Bambu/Orca-dialect source states these in Orca's words. A PrusaSlicer
    # project can reuse a name (its own `brim_type`) with its own meaning, which the
    # prepared copy does not carry: that falls through to the translation table below,
    # which reports it as not carried, exactly as before.
    native = [] if source.get("dialect") == DIALECT_PRUSA else sorted(
        k for k in source_overrides if k in object_overrides.NATIVE_KEPT)
    for key in native:
        said = source_overrides.pop(key)
        found = kept.pop(key, None)
        if found == said and object_overrides.NATIVE_KEPT[key](said):
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": PRESERVED_EXACT,
                "detail": f"{key} = {said}, in the same words on both sides"})
        elif found is None:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": CHANGED,
                "detail": f"{key} = {said} is set on this object and the copy states nothing"})
        else:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": CHANGED,
                "detail": f"{key} = {said} on the source, but the copy states {found}"})

    # The same count the writer used. Without it the audit believes a layer
    # height should have crossed on a plate that needs a prime tower, and
    # reports Studio's correct refusal as a fault.
    for entry in object_overrides.plan(
            source_overrides, filaments=filaments)["rows"]:
        source_key, source_value = entry["source_key"], entry["source_value"]
        target_key = entry["target_key"]
        found = kept.pop(target_key, None) if target_key else None
        if not entry["carried"]:
            # Studio decided this one cannot cross. If the copy carries it
            # anyway, something wrote a value this module refused — a fault, not
            # a bonus.
            if found is not None:
                rows.append({
                    "object": name, "index": index, "kind": "override",
                    "status": CHANGED,
                    "detail": (f"{source_key} = {source_value} was not carried, but the "
                               f"copy states {target_key} = {found}")})
                continue
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": UNSUPPORTED,
                "detail": (f"{source_key} = {source_value} is set on this object and the "
                           f"prepared copy does not carry it: {entry['why']}")})
            continue
        wanted = entry["target_value"]
        if found is None:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": CHANGED,
                "detail": (f"{source_key} = {source_value} should have crossed as "
                           f"{target_key} = {wanted}, and the copy states nothing")})
        elif found != wanted:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": CHANGED,
                "detail": (f"{source_key} = {source_value} crossed as {target_key} = "
                           f"{found}, and should have been {wanted}")})
        elif entry["kind"] == object_overrides.EXACT:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": PRESERVED_EXACT,
                "detail": f"{source_key} = {wanted}, in the same words on both sides"})
        else:
            rows.append({
                "object": name, "index": index, "kind": "override",
                "status": PRESERVED_SEMANTIC,
                "detail": (f"{source_key} = {source_value} crossed as {target_key} = "
                           f"{wanted} — Snapmaker Orca's own word for "
                           f"{entry['meaning']}")})

    for target_key, value in sorted(kept.items()):
        rows.append({
            "object": name, "index": index, "kind": "override",
            "status": CHANGED,
            "detail": (f"the copy sets {target_key} = {value} on this object and the "
                       "source never did")})
    return rows
