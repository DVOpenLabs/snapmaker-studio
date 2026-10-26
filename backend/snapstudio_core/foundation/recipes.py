"""Virtual recipes: material mixes a generator describes.

A recipe is a simulation input, never a claim about what the printer will do:
`simulated` is always True. Definitions Studio cannot interpret are preserved with
`execution_supported=False`, never dropped, and an unknown `ratio_kind` is kept as
unknown rather than read as a consumption figure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .decode import Decoded, Diagnostic, ERROR, NOTE, Reader, WARNING, decode_document, diag, is_finite_number
from .topology import SlotBinding

SCHEMA_VERSION = "virtual_recipe/1"

KINDS = ("fullspectrum", "dither", "colorpatch", "custom", "unknown")
RATIO_KINDS = ("mass", "area", "layer", "unknown")

_SLOT_RE = re.compile(r"^slot:(\d+)$")
_PROJECT_RE = re.compile(r"^project:([01]):(\d+)$")   # project:<base>:<n>, base 0 or 1
_RECIPE_RE = re.compile(r"^recipe:(.+)$")


@dataclass
class RecipeComponent:
    slot_ref: str                 # slot:<n> | project:<base>:<n> | recipe:<recipe_id>
    ratio: float | None = None
    ratio_kind: str = "unknown"
    ratio_invalid: bool = False   # a ratio was supplied but is not a finite number (NaN, inf, bool, text, huge)

    def to_dict(self) -> dict:
        out = {"slot_ref": self.slot_ref, "ratio": self.ratio, "ratio_kind": self.ratio_kind}
        if self.ratio_invalid:
            out["ratio_invalid"] = True
        return out


@dataclass
class VirtualRecipe:
    recipe_id: str                # "<generator>:<local id>"
    generator: dict               # {name, version|None}
    kind: str = "unknown"
    components: list = field(default_factory=list)
    execution_supported: bool | None = None

    @property
    def simulated(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "recipe_id": self.recipe_id,
                "generator": dict(self.generator), "kind": self.kind,
                "components": [c.to_dict() for c in self.components], "simulated": True,
                "execution_supported": self.execution_supported}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["VirtualRecipe"]:
        return decode_document(raw, SCHEMA_VERSION, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "VirtualRecipe":
        gr = r.child(r.mapping("generator", required=True), "generator")
        generator = {"name": gr.string("name"), "version": gr.string("version", required=False)}
        components = []
        for i, item in enumerate(r.items("components")):
            cr = r.child(item, f"components[{i}]")
            ratio_raw = cr.raw.get("ratio")
            ratio = None
            ratio_invalid = cr.raw.get("ratio_invalid") is True      # our own serialisation of an earlier verdict
            if ratio_raw is not None:
                if is_finite_number(ratio_raw):
                    try:
                        ratio = float(ratio_raw)    # negative values are kept; validate() reports them
                    except OverflowError:
                        ratio_invalid = True
                else:
                    ratio_invalid = True
            if ratio_invalid:
                cr.warn("bad_ratio", "ratio")       # kept as invalid, never dropped: assess() withdraws execution
            kind = cr.raw.get("ratio_kind")
            if kind not in RATIO_KINDS:
                if kind is not None:
                    cr.warn("unknown_ratio_kind", "ratio_kind")
                kind = "unknown"
            components.append(RecipeComponent(cr.string("slot_ref") or "", ratio, kind, ratio_invalid))
        kind = r.raw.get("kind")
        if kind not in KINDS:
            r.warn("unknown_kind", "kind")
            kind = "unknown"
        return cls(r.string("recipe_id") or "", generator, kind, components,
                   r.boolean("execution_supported", default=None))


def _resolve(slot_ref: str) -> str | None:
    """A slot reference as an internal `slot:<n>` id, or None when it is not a slot reference."""
    m = _SLOT_RE.match(slot_ref)
    if m:
        return f"slot:{int(m.group(1))}"
    m = _PROJECT_RE.match(slot_ref)
    if m and int(m.group(2)) - int(m.group(1)) >= 0:
        return f"slot:{int(m.group(2)) - int(m.group(1))}"
    return None


def validate(recipe: VirtualRecipe, *, known_slots: Iterable[str] | None = None,
             recipes: dict | None = None) -> list[Diagnostic]:
    """Diagnostics for one recipe. `known_slots` (slot ids) enables missing-component checks and
    `recipes` (id -> VirtualRecipe) enables recipe-to-recipe cycle checks."""
    out: list[Diagnostic] = []
    known = set(known_slots) if known_slots is not None else None
    if not recipe.components:
        out.append(diag("no_components", "components", ERROR))
    seen: set = set()
    for i, comp in enumerate(recipe.components):
        where = f"components[{i}]"
        if comp.slot_ref in seen:
            out.append(diag("duplicate_component", where, ERROR))
        seen.add(comp.slot_ref)
        recipe_ref = _RECIPE_RE.match(comp.slot_ref)
        if recipe_ref:
            target = recipe_ref.group(1)
            if recipes is not None and target not in recipes:
                out.append(diag("missing_component", where, ERROR))
            elif recipes is not None and _reaches(target, recipe.recipe_id, recipes, set()):
                out.append(diag("recipe_cycle", where, ERROR))
            elif target == recipe.recipe_id:
                out.append(diag("recipe_cycle", where, ERROR))
        else:
            slot = _resolve(comp.slot_ref)
            if slot is None:
                out.append(diag("unknown_slot_ref", where, ERROR))
            elif known is not None and slot not in known:
                out.append(diag("missing_component", where, ERROR))
        ratio = comp.ratio
        if comp.ratio_invalid:
            out.append(diag("non_finite_ratio", f"{where}.ratio", ERROR))
        elif ratio is not None:
            if not is_finite_number(ratio):
                out.append(diag("non_finite_ratio", f"{where}.ratio", ERROR))
            elif ratio < 0:
                out.append(diag("negative_ratio", f"{where}.ratio", ERROR))
        if comp.ratio_kind not in RATIO_KINDS or comp.ratio_kind == "unknown":
            out.append(diag("unknown_ratio_kind", f"{where}.ratio_kind", NOTE))
    if recipe.kind == "unknown" or recipe.kind not in KINDS:
        out.append(diag("unsupported_dialect", "kind", WARNING))
    return out


def _reaches(start: str, goal: str, recipes: dict, visiting: set) -> bool:
    """True if recipe `start` references `goal` through recipe components."""
    if start == goal:
        return True
    if start in visiting or start not in recipes:
        return False
    visiting.add(start)
    for comp in recipes[start].components:
        m = _RECIPE_RE.match(comp.slot_ref)
        if m and _reaches(m.group(1), goal, recipes, visiting):
            return True
    return False


def assess(recipe: VirtualRecipe, **kwargs: Any) -> tuple[VirtualRecipe, list[Diagnostic]]:
    """Validate and return the recipe with `execution_supported=False` when anything is unusable.
    The recipe is always preserved; only the flag changes."""
    diagnostics = validate(recipe, **kwargs)
    blocking = any(d.severity == ERROR or d.code in ("unsupported_dialect", "unknown_ratio_kind")
                   for d in diagnostics)
    if not blocking:
        return recipe, diagnostics
    return VirtualRecipe(recipe.recipe_id, dict(recipe.generator), recipe.kind, list(recipe.components),
                         False), diagnostics


def physical_inputs(recipe: VirtualRecipe, bindings: Iterable[SlotBinding] = ()) -> dict:
    """The physical inputs a recipe refers to: slot ids, and how many distinct lanes/heads they bind to.

    This is a count of referenced inputs, not a nozzle count. `count` is None when any referenced
    slot is unbound or a component refers to another recipe (which this function does not expand)."""
    slot_ids: list[str] = []
    unresolved = False
    for comp in recipe.components:
        slot = _resolve(comp.slot_ref)
        if slot is None:
            unresolved = True
        elif slot not in slot_ids:
            slot_ids.append(slot)
    by_slot: dict[str, set] = {}
    for b in bindings:
        if b.target is not None:
            by_slot.setdefault(b.slot_id, set()).add(b.target)
    targets: set = set()
    for slot in slot_ids:
        bound = by_slot.get(slot)
        if not bound or len(bound) != 1:
            unresolved = True
        else:
            targets |= bound
    return {"slot_ids": slot_ids, "count": None if unresolved else len(targets)}
