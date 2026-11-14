"""Which volumes print: ONE rule for the scene, the sizes and the placed bounds.

A project says what each part of an object is for in its ``model_settings.config`` part records
(``normal_part``, ``modifier_part``, ``negative_part``, ``support_blocker``, ``support_enforcer``). Only a
normal part prints; the others are instructions to the slicer. The rule, in one place so that the scene, an
object's size, its placed footprint and its height cannot disagree:

* **A part record belongs to one (object, component) pair.** The record for component C under object O says
  what C is *for the purpose of O*.
* **A non-printing role is inherited by everything beneath it.** A modifier set on an assembly applies to
  every descendant; a descendant cannot print again by being a plain part. A child's own record is resolved
  against what it inherits: ``inherit``.
* **No record means a normal part** when the project has no record for that component (``missing`` says
  what the caller wants instead, the scene reports it as unknown). An object with no part records at all
  passes its inherited role down unchanged.
* **Conflicting records** (two records for one (object, part) that disagree) and **unrecognised words** are
  role ``unknown``. The scene reports unknown. A size or a footprint cannot prove such a volume does not
  print, so it COUNTS (``counts_toward_size``): the answer can be too big, never falsely small.
* Part records are matched against objects of the root model. A build item whose object lives in another part
  (``p:path``) has no provable records; its volumes inherit nothing and count.
"""
from __future__ import annotations

#: Stands in for a subtype when two records for one (object, part) disagree; ``role_of`` reads it as unknown.
CONFLICTING_SUBTYPE = "conflicting_records"


def merge_record(parts: dict, part_id: str, subtype: str | None) -> None:
    """Record ``part_id``'s subtype; a second, different record makes it the conflicting marker."""
    if part_id in parts and parts[part_id] != subtype:
        subtype = CONFLICTING_SUBTYPE
    parts[part_id] = subtype


class Records:
    """The part records of a settings file: ``subtypes[object id][part id]`` and the objects that have any."""

    def __init__(self) -> None:
        self.part_subtypes: dict[str, dict[str, str | None]] = {}
        self.metadata_objects: set[str] = set()


def read_records(settings_xml: str) -> Records:
    """Part records from the text of a ``model_settings.config`` (empty if it cannot be read)."""
    from .config_io import load_model_settings

    out = Records()
    if not settings_xml:
        return out
    try:
        root = load_model_settings(settings_xml.encode("utf-8"))
        for obj in root.iter("object"):
            oid = obj.get("id") or ""
            parts = out.part_subtypes.setdefault(oid, {})
            for part in obj.iterchildren("part"):
                out.metadata_objects.add(oid)
                pid = part.get("id")
                if pid is not None:
                    merge_record(parts, pid, part.get("subtype"))
    except Exception:  # noqa: BLE001 - unreadable settings mean no records, never a crash
        return Records()
    return out


def own_role(part_subtypes: dict, metadata_objects, object_id: str, via: str, *, missing):
    """The role the project's records give component ``via`` of object ``object_id``, or None if the
    object has no part records. ``missing`` is returned for an object that HAS records but none for ``via``."""
    from .assignments import role_of

    subtypes = part_subtypes.get(object_id)
    if object_id in metadata_objects and subtypes is not None:
        return role_of(subtypes[via]) if via in subtypes else missing
    return None


def inherit(inherited, own):
    """The role of a node from the role it inherits and its own record: a non-printing inherited role wins."""
    from .assignments import PART

    if inherited not in (None, PART):
        return inherited
    return own if own is not None else inherited


def counts_toward_size(role) -> bool:
    """Whether a volume with this role counts when measuring what prints (see the module docstring)."""
    from .assignments import PART, ROLE_UNKNOWN

    return role in (None, PART, ROLE_UNKNOWN)
