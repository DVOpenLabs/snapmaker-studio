"""The assembly document: tiles, shared roles, spool bindings and an attribution manifest.

An assembly is user-defined input, so every field is validated and bounded here. A bad
document raises `AssemblyInputError` (the route turns that into a 400); nothing else in
this module raises on data. Grams are `float | None` and None means "not stated": it is
never turned into zero.

Slots are 0-based `slot:n` ids (foundation topology). An Orca project's 1-based filament
number and a G-code `T<n>` both land on the same id.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from snapstudio_core.foundation import topology
from snapstudio_core.foundation.decode import is_finite_number
from snapstudio_core.foundation.materials import SpoolAlias, SpoolRef

SCHEMA_VERSION = "assembly/1"

MAX_TILES = 64
MAX_PARTS = 64
MAX_ROLES = 32
MAX_ATTRIBUTION = 64
MAX_SLOTS = 64
MAX_TEXT = 200
MAX_GRAMS = 1_000_000.0

_ROLE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ \-]{0,39}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SLOT_RE = re.compile(r"^slot:(\d{1,3})$")


class AssemblyInputError(ValueError):
    """The assembly document is not usable. The message is safe to show to the user."""


def _obj(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise AssemblyInputError(f"{what} must be an object.")
    return value


def _list(value: Any, what: str, limit: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AssemblyInputError(f"{what} must be a list.")
    if len(value) > limit:
        raise AssemblyInputError(f"{what} has more than {limit} entries.")
    return value


def _text(value: Any, what: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise AssemblyInputError(f"{what} is required.")
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise AssemblyInputError(f"{what} must be text of at most {MAX_TEXT} characters.")
    return value.strip() or None


def _ident(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise AssemblyInputError(f"{what} must be 1-64 letters, digits, dots, dashes or underscores.")
    return value


def _role(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _ROLE_RE.match(value):
        raise AssemblyInputError(f"{what} must be 1-40 letters, digits, spaces, dashes or underscores.")
    return value


def grams_or_none(value: Any, what: str) -> float | None:
    """A gram figure: finite, non-negative, bounded. null stays null; anything else unusable is refused."""
    if value is None:
        return None
    if not is_finite_number(value) or value < 0 or value > MAX_GRAMS:
        raise AssemblyInputError(f"{what} must be a number from 0 up, or null when it is not known.")
    return float(value)


def slot_key(value: Any, what: str) -> str:
    match = _SLOT_RE.match(value) if isinstance(value, str) else None
    if not match or int(match.group(1)) >= MAX_SLOTS:
        raise AssemblyInputError(f"{what} must look like slot:0 (slots count from 0).")
    return topology.slot_id(int(match.group(1)))


def spool_ref(value: Any, what: str) -> SpoolRef:
    d = _obj(value, what)
    try:
        return SpoolRef(d.get("provider_instance_id"), d.get("provider_spool_id"))
    except ValueError:
        raise AssemblyInputError(f"{what} needs a provider_instance_id and a provider_spool_id.") from None


@dataclass(frozen=True)
class LibraryRef:
    """Cross-reference to a library project: its id and the sha256 the user recorded. No foreign key."""
    project_id: int
    sha256: str | None

    def to_dict(self) -> dict:
        return {"project_id": self.project_id, "sha256": self.sha256}


@dataclass
class Tile:
    tile_id: str
    name: str
    plate: str | None = None
    part_id: str | None = None
    library: LibraryRef | None = None
    roles: dict = field(default_factory=dict)      # role -> slot id
    usage: dict = field(default_factory=dict)      # slot id -> grams | None
    usage_source: str | None = None                # declared | slot_usage | gcode_facts | None
    scale: float | None = None
    attribution: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"tile_id": self.tile_id, "name": self.name, "plate": self.plate, "part_id": self.part_id,
                "library": self.library.to_dict() if self.library else None,
                "roles": dict(self.roles), "usage": dict(self.usage), "usage_source": self.usage_source,
                "scale": self.scale, "attribution": dict(self.attribution)}


@dataclass
class Assembly:
    name: str
    tiles: list = field(default_factory=list)
    parts: list = field(default_factory=list)          # [{part_id, name}]
    bindings: dict = field(default_factory=dict)       # role -> SpoolRef
    aliases: list = field(default_factory=list)        # [SpoolAlias]
    attribution: list = field(default_factory=list)    # retained as written: [{item, author, license, source}]

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "name": self.name,
                "tiles": [t.to_dict() for t in self.tiles], "parts": [dict(p) for p in self.parts],
                "bindings": {role: ref.to_dict() for role, ref in self.bindings.items()},
                "aliases": [a.to_dict() for a in self.aliases],
                "attribution": [dict(a) for a in self.attribution]}


# -- gram sources ----------------------------------------------------------------
def usage_from_slot_usage(slot_usage: Any) -> dict:
    """`project_compare.slot_usage` output (slots numbered from 1) -> {slot:n: grams | None}.

    Only `sliced_g` counts as grams. A slot the project references but that carries no slicer
    figure is None (unknown), never 0.
    """
    slots = _obj(_obj(slot_usage, "slot_usage").get("slots"), "slot_usage.slots")
    if len(slots) > MAX_SLOTS:
        raise AssemblyInputError("slot_usage has too many slots.")
    out: dict = {}
    for key, entry in slots.items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            raise AssemblyInputError("slot_usage slots must be numbered from 1.") from None
        index = topology.normalise_index("orca_filament", number)
        if index is None:
            raise AssemblyInputError("slot_usage slots must be numbered from 1.")
        out[topology.slot_id(index)] = grams_or_none(_obj(entry, "A slot_usage entry").get("sliced_g"), "sliced_g")
    return out


def usage_from_gcode_facts(facts: Any) -> dict:
    """`gcode.read_facts` output (tools numbered from 0) -> {slot:n: grams | None}.

    A file Studio could not read (`available` false) states nothing: empty usage, every
    figure unknown.
    """
    facts = _obj(facts, "gcode_facts")
    if not facts.get("available"):
        return {}
    out: dict = {}
    for entry in _list(facts.get("slots"), "gcode_facts.slots", MAX_SLOTS):
        entry = _obj(entry, "A gcode_facts slot")
        tool = topology.normalise_index("gcode_t", entry.get("tool"))
        if tool is None:
            raise AssemblyInputError("gcode_facts slots need a tool number from 0.")
        out[topology.slot_id(tool)] = grams_or_none(entry.get("grams"), "grams")
    return out


# -- reading ---------------------------------------------------------------------
def _read_tile(raw: Any) -> Tile:
    d = _obj(raw, "A tile")
    tile = Tile(tile_id=_ident(d.get("tile_id"), "tile_id"),
                name=_text(d.get("name"), "The tile name", required=True) or "")
    plate = d.get("plate")
    if plate is not None and (isinstance(plate, bool) or not isinstance(plate, (str, int))):
        raise AssemblyInputError("plate must be text or a number.")
    tile.plate = None if plate in (None, "") else str(plate)[:MAX_TEXT]
    part_id = d.get("part_id")
    tile.part_id = None if part_id in (None, "") else _ident(part_id, "part_id")

    library = d.get("library")
    if library is not None:
        lib = _obj(library, "library")
        pid = lib.get("project_id")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
            raise AssemblyInputError("library.project_id must be a whole number.")
        sha = lib.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not _SHA_RE.match(sha.lower())):
            raise AssemblyInputError("library.sha256 must be 64 hex characters or null.")
        tile.library = LibraryRef(pid, sha.lower() if sha else None)

    roles = _obj(d.get("roles") or {}, "roles")
    if len(roles) > MAX_ROLES:
        raise AssemblyInputError("A tile has too many roles.")
    for role, slot in roles.items():
        tile.roles[_role(role, "A role name")] = slot_key(slot, f"Role {role}")

    sources = [k for k in ("usage", "slot_usage", "gcode_facts") if d.get(k) is not None]
    if len(sources) > 1:
        raise AssemblyInputError("Give a tile one source of gram figures: usage, slot_usage or gcode_facts.")
    if sources == ["usage"]:
        for slot, grams in _obj(d["usage"], "usage").items():
            tile.usage[slot_key(slot, "A usage key")] = grams_or_none(grams, "A gram figure")
        tile.usage_source = "declared"
    elif sources == ["slot_usage"]:
        tile.usage, tile.usage_source = usage_from_slot_usage(d["slot_usage"]), "slot_usage"
    elif sources == ["gcode_facts"]:
        tile.usage, tile.usage_source = usage_from_gcode_facts(d["gcode_facts"]), "gcode_facts"

    scale = d.get("scale")
    if scale is not None:
        if not is_finite_number(scale) or scale <= 0 or scale > 1000:
            raise AssemblyInputError("scale must be a positive number, or null when it is not known.")
        tile.scale = float(scale)

    for key, value in _obj(d.get("attribution") or {}, "attribution").items():
        if not isinstance(key, str) or len(key) > 40:
            raise AssemblyInputError("An attribution key must be short text.")
        tile.attribution[key] = _text(value, f"Attribution {key}")
    return tile


def read_assembly(raw: Any) -> Assembly:
    d = _obj(raw, "The assembly")
    stamp = d.get("schema_version")
    if stamp is not None and stamp != SCHEMA_VERSION:
        raise AssemblyInputError("This assembly was written in a format this version of Studio does not read.")
    asm = Assembly(name=_text(d.get("name"), "The assembly name", required=True) or "")
    seen: set = set()
    for item in _list(d.get("tiles"), "tiles", MAX_TILES):
        tile = _read_tile(item)
        if tile.tile_id in seen:
            raise AssemblyInputError("Two tiles share the same tile_id.")
        seen.add(tile.tile_id)
        asm.tiles.append(tile)
    part_ids: set = set()
    for item in _list(d.get("parts"), "parts", MAX_PARTS):
        p = _obj(item, "A part")
        pid = _ident(p.get("part_id"), "part_id")
        if pid in part_ids:
            raise AssemblyInputError("Two parts share the same part_id.")
        part_ids.add(pid)
        asm.parts.append({"part_id": pid, "name": _text(p.get("name"), "The part name") or pid})
    bindings = _obj(d.get("bindings") or {}, "bindings")
    if len(bindings) > MAX_ROLES:
        raise AssemblyInputError("There are too many bindings.")
    for role, ref in bindings.items():
        asm.bindings[_role(role, "A binding role")] = spool_ref(ref, f"The binding for {role}")
    for item in _list(d.get("aliases"), "aliases", 32):
        a = _obj(item, "An alias")
        refs = [spool_ref(r, "An alias reference") for r in _list(a.get("refs"), "alias refs", 8)]
        evidence = _text(a.get("evidence"), "The alias evidence", required=True) or ""
        declared_by = _text(a.get("declared_by"), "The alias declared_by", required=True) or ""
        try:
            asm.aliases.append(SpoolAlias(tuple(refs), evidence, declared_by))
        except ValueError:
            raise AssemblyInputError("An alias needs at least two spool references.") from None
    for item in _list(d.get("attribution"), "attribution", MAX_ATTRIBUTION):
        a = _obj(item, "An attribution entry")
        entry = {}
        for key, value in a.items():
            if not isinstance(key, str) or len(key) > 40:
                raise AssemblyInputError("An attribution key must be short text.")
            entry[key] = _text(value, f"Attribution {key}")
        asm.attribution.append(entry)
    return asm
