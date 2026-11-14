"""The passport document: which files a job was made from, and what was kept or lost.

A passport records the derivation chain original -> prepared -> sliced (or any generated
artifact) as `foundation.artifacts` byte identities and derivations, plus the recipes and
material mappings that travelled with the job. It never contains a local path: names only.

Who vouches for a link matters. A chain the user states when building a passport, and any
chain read from a passport file, is `declared`; only a derivation Studio itself witnessed
could be `local`, and importing can never produce one. Anything that cannot be carried over
is listed in `losses`, never dropped silently.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from snapstudio_core.foundation import recipes as _recipes
from snapstudio_core.foundation.artifacts import ArtifactRef, Derivation
from snapstudio_core.foundation.decode import (
    ERROR, NOTE, WARNING, Decoded, Diagnostic, Reader, canonical_json, decode_document, diag,
)

SCHEMA_VERSION = "passport/1"
PRODUCER = {"tool": "snapstudio-passport", "version": None}

#: Roles a job chain may carry. Others in foundation.artifacts.ROLES belong to other tracks.
CHAIN_ROLES = ("original", "prepared", "generated", "sliced", "settings")

MAX_ARTIFACTS = 64
MAX_DERIVATIONS = 128
MAX_RECIPES = 64
MAX_MAPPINGS = 64
MAX_TEXT = 64

_SLOT_REF_RE = re.compile(r"^(slot:\d{1,3}|project:[01]:\d{1,3})$")
_COLOUR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAPPING_KEYS = ("slot_ref", "material", "colour", "spool")


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def hash_file(path: str) -> tuple[str, int]:
    """sha256 and size of a file, read in chunks. Raises OSError; the caller reports it."""
    digest, total = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest(), total
            digest.update(chunk)
            total += len(chunk)


def loss(kind: str, ident: Any, reason: str) -> dict:
    return {"kind": kind, "id": str(ident)[:MAX_TEXT * 2], "reason": reason}


@dataclass
class Passport:
    passport_id: str
    created_at: str
    artifacts: list
    derivations: list
    recipes: list = field(default_factory=list)
    material_mappings: list = field(default_factory=list)
    losses: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "passport_id": self.passport_id,
                "created_at": self.created_at, "producer": dict(PRODUCER),
                "artifacts": [a.to_dict() for a in self.artifacts],
                "derivations": [d.to_dict() for d in self.derivations],
                "recipes": [r.to_dict() for r in self.recipes],
                "material_mappings": [dict(m) for m in self.material_mappings],
                "losses": [dict(item) for item in self.losses]}


def compute_passport_id(artifacts: list, derivations: list, recipes: list, mappings: list) -> str:
    """Content-derived: the same chain, recipes and mappings always give the same id."""
    body = {"artifacts": sorted(a.artifact_id for a in artifacts),
            "derivations": sorted(d.derivation_id for d in derivations),
            "recipes": sorted((r.to_dict() for r in recipes), key=lambda r: r["recipe_id"]),
            "mappings": sorted((dict(m) for m in mappings), key=lambda m: m["slot_ref"])}
    return "pp:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()[:40]


# -- recipes and mappings: retained, or reported lost ---------------------------------
def retain_recipes(raws: Any) -> tuple[list, list, list]:
    """(recipes, losses, diagnostics). A recipe that cannot be decoded is reported lost, never hidden."""
    kept: list = []
    losses: list = []
    diagnostics: list[Diagnostic] = []
    if raws is None:
        return kept, losses, diagnostics
    if not isinstance(raws, list):
        return kept, [loss("recipe", "recipes", "not_a_list")], [diag("recipes_not_a_list", "recipes", ERROR)]
    if len(raws) > MAX_RECIPES:
        return kept, [loss("recipe", "recipes", "too_many")], [diag("too_many_recipes", "recipes", ERROR)]
    seen: set = set()
    for i, raw in enumerate(raws):
        ident = raw.get("recipe_id") if isinstance(raw, dict) and isinstance(raw.get("recipe_id"), str) else f"#{i}"
        decoded = _recipes.VirtualRecipe.from_dict(raw if isinstance(raw, dict) else None)
        if decoded.value is None:
            code = decoded.diagnostics[0].code if decoded.diagnostics else "undecodable"
            losses.append(loss("recipe", ident, code))
            continue
        if decoded.value.recipe_id in seen:
            losses.append(loss("recipe", ident, "duplicate"))
            continue
        seen.add(decoded.value.recipe_id)
        recipe, found = _recipes.assess(decoded.value)
        diagnostics.extend(diag(d.code, f"recipes[{i}].{d.field}", d.severity) for d in found)
        if recipe.execution_supported is not False:
            # A passport only records a recipe; whatever execution claim came with it is not Studio's to repeat.
            diagnostics.append(diag("execution_claim_ignored", f"recipes[{i}].execution_supported", NOTE))
            recipe = dataclasses.replace(recipe, execution_supported=False)
        kept.append(recipe)
    return kept, losses, diagnostics


def retain_mappings(raws: Any) -> tuple[list, list]:
    """(mappings, losses). Only slot_ref, material, colour and spool are kept; a dropped field is listed."""
    kept: list = []
    losses: list = []
    if raws is None:
        return kept, losses
    if not isinstance(raws, list):
        return kept, [loss("material_mapping", "material_mappings", "not_a_list")]
    if len(raws) > MAX_MAPPINGS:
        return kept, [loss("material_mapping", "material_mappings", "too_many")]
    seen: set = set()
    for i, raw in enumerate(raws):
        ident = raw.get("slot_ref") if isinstance(raw, dict) and isinstance(raw.get("slot_ref"), str) else f"#{i}"
        if not isinstance(raw, dict) or not isinstance(raw.get("slot_ref"), str) \
                or not _SLOT_REF_RE.match(raw["slot_ref"]):
            losses.append(loss("material_mapping", ident, "bad_slot_ref"))
            continue
        if raw["slot_ref"] in seen:
            losses.append(loss("material_mapping", ident, "duplicate"))
            continue
        entry: dict = {"slot_ref": raw["slot_ref"]}
        material, colour, spool = raw.get("material"), raw.get("colour"), raw.get("spool")
        if isinstance(material, str) and 0 < len(material.strip()) <= MAX_TEXT:
            entry["material"] = material.strip()
        elif material is not None:
            losses.append(loss("material_mapping", ident, "bad_material"))
        if isinstance(colour, str) and _COLOUR_RE.match(colour):
            entry["colour"] = colour.upper()
        elif colour is not None:
            losses.append(loss("material_mapping", ident, "bad_colour"))
        if isinstance(spool, dict) and all(isinstance(spool.get(k), str) and 0 < len(spool[k]) <= 128
                                           for k in ("provider_instance_id", "provider_spool_id")):
            entry["spool"] = {"provider_instance_id": spool["provider_instance_id"],
                              "provider_spool_id": spool["provider_spool_id"]}
        elif spool is not None:
            losses.append(loss("material_mapping", ident, "bad_spool"))
        for key in raw:
            if key not in _MAPPING_KEYS:
                losses.append(loss("material_mapping", ident, f"field_not_retained:{str(key)[:32]}"))
        seen.add(raw["slot_ref"])
        kept.append(entry)
    return kept, losses


# -- decoding an imported passport ----------------------------------------------------
def decode_passport(raw: Any) -> Decoded[Passport]:
    """Decode a passport from a file or request. Never raises.

    Every derivation comes back `declared`; locators are discarded (a foreign path is neither
    trusted nor read); an artifact or derivation that cannot be decoded, or that refers to
    something not in the passport, is dropped and listed in `losses`.
    """
    return decode_document(raw, SCHEMA_VERSION, _build_passport)


def _prefixed(source: list, prefix: str, sink: list) -> None:
    """Child diagnostics, re-pathed; the child is dropped on error so they only warn here."""
    for d in source:
        sink.append(diag(d.code, f"{prefix}.{d.field}".rstrip("."), WARNING))


def _item_id(item: Any, key: str, index: int) -> str:
    return str(item.get(key)) if isinstance(item, dict) and isinstance(item.get(key), str) else f"#{index}"


def _build_passport(r: Reader) -> Passport:
    for name, cap in (("artifacts", MAX_ARTIFACTS), ("derivations", MAX_DERIVATIONS),
                      ("recipes", MAX_RECIPES), ("material_mappings", MAX_MAPPINGS)):
        if isinstance(r.raw.get(name), list) and len(r.raw[name]) > cap:
            r.error(f"too_many_{name}", name)
    if any(d.severity == ERROR for d in r.diagnostics):
        return Passport("", "", [], [])
    losses: list = []
    artifacts: list = []
    for i, item in enumerate(r.items("artifacts", required=True)):
        decoded = ArtifactRef.from_dict(item)
        if decoded.value is None:
            _prefixed(decoded.diagnostics, f"artifacts[{i}]", r.diagnostics)
            reason = decoded.diagnostics[0].code if decoded.diagnostics else "undecodable"
            losses.append(loss("artifact", _item_id(item, "artifact_id", i), reason))
            continue
        ref = decoded.value
        if ref.role not in CHAIN_ROLES:
            losses.append(loss("artifact", ref.artifact_id, "role_not_supported"))
            continue
        if ref.locator is not None:
            r.note("locator_dropped", f"artifacts[{i}].locator")
        ref.locator = None
        if any(a.artifact_id == ref.artifact_id for a in artifacts):
            losses.append(loss("artifact", ref.artifact_id, "duplicate"))
            continue
        artifacts.append(ref)
    if not artifacts:
        r.error("no_artifacts", "artifacts")
    known = {a.artifact_id for a in artifacts}
    derivations: list = []
    for i, item in enumerate(r.items("derivations", required=True)):
        decoded = Derivation.from_dict(item, imported=True)
        _prefixed(decoded.diagnostics, f"derivations[{i}]", r.diagnostics)
        if decoded.value is None:
            code = decoded.diagnostics[0].code if decoded.diagnostics else "undecodable"
            losses.append(loss("derivation", _item_id(item, "derivation_id", i), code))
            continue
        drv = decoded.value
        if drv.output not in known or any(inp["ref"] not in known for inp in drv.inputs):
            losses.append(loss("derivation", drv.derivation_id, "dangling_ref"))
            continue
        if any(d.derivation_id == drv.derivation_id for d in derivations):
            losses.append(loss("derivation", drv.derivation_id, "duplicate"))
            continue
        derivations.append(drv)
    recipes, recipe_losses, recipe_diags = retain_recipes(r.raw.get("recipes"))
    mappings, mapping_losses = retain_mappings(r.raw.get("material_mappings"))
    r.diagnostics.extend(diag(d.code, d.field, WARNING) for d in recipe_diags)
    recorded = r.raw.get("losses")
    carried = ([loss(str(x.get("kind"))[:32], x.get("id"), str(x.get("reason"))[:64])
                for x in recorded if isinstance(x, dict)][:MAX_ARTIFACTS] if isinstance(recorded, list) else [])
    created = r.string("created_at", required=False) or ""
    new_id = compute_passport_id(artifacts, derivations, recipes, mappings)
    declared_id = r.string("passport_id", required=False)
    if declared_id and declared_id != new_id:
        r.warn("passport_id_recomputed", "passport_id")
    return Passport(new_id, created, artifacts, derivations, recipes, mappings,
                    carried + losses + recipe_losses + mapping_losses)
