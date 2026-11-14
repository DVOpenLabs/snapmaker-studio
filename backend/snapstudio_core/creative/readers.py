"""Version-specific readers for documented creative project settings.

Each reader is conservative: it extracts only published fields and leaves all
other project settings and archive members opaque.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from snapstudio_core.foundation.recipes import RecipeComponent, VirtualRecipe

from .container import ThreeMFManifest, read_3mf

_FORCA_KEYS = frozenset({
    "fos_filament_nozzle", "fos_filament_mms_slot", "fos_physical_nozzle_diameter",
    "fos_mms_topology", "fos_mms_unit_count", "fos_mms_head_ace", "mms_system",
    "mms_host", "color_patch_loops", "color_patch_enabled",
})
_LIX_KEYS = frozenset({"extruder_layer_height", "extruder_layer_height_exact"})
_FULLSPECTRUM_KEYS = frozenset({"mixed_filament_definitions"})


@dataclass
class CreativeProject:
    source_format: str
    artifact_identity: dict[str, Any]
    understood: dict[str, Any] = field(default_factory=dict)
    passed_through: tuple[dict[str, str], ...] = ()
    unknown: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    recipes: tuple[VirtualRecipe, ...] = ()
    physical_slots_needed: int | None = None
    source_component_ids: tuple[int, ...] = ()
    simulated: bool = True

    def loss_report(self) -> dict[str, Any]:
        return {"source_format": self.source_format, "understood": sorted(self.understood),
                "passed_through": list(self.passed_through), "unknown": list(self.unknown),
                "missing": list(self.missing), "diagnostics": list(self.diagnostics)}


def _settings(source: bytes | dict) -> tuple[dict, ThreeMFManifest | None]:
    if isinstance(source, dict):
        return source, None
    manifest = read_3mf(source)
    return manifest.project_settings or {}, manifest


def _digest_obj(raw: dict) -> dict[str, Any]:
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "size_bytes": len(encoded)}


def _reader(name: str, settings: dict, known: frozenset[str], *, require: tuple[str, ...] = (),
            manifest: ThreeMFManifest | None = None) -> CreativeProject:
    found = {k: v for k, v in settings.items() if k in known}
    unknown = tuple(sorted(k for k in settings if k.startswith(("fos_", "extruder_layer_height", "mixed_filament_")) and k not in known))
    passthrough = tuple({"name": k, "sha256": _digest_obj({k: v})["sha256"]} for k, v in sorted(settings.items()) if k not in known)
    if manifest is not None:
        archive_parts = tuple({"name": member.name, "sha256": member.sha256}
                              for member in manifest.passed_through)
        passthrough += archive_parts
    missing = tuple(k for k in require if k not in settings)
    return CreativeProject(name, _digest_obj(settings), found, passthrough, unknown, missing)


def read_forca(source: bytes | dict) -> CreativeProject:
    """Read published FOrca extension keys only.

    Shape references: saved device-research entry FOrcaSlicer lines 134-150;
    source blob receipt `fos_config` (PrintConfig.cpp lines 2175-2185,
    4067-4087 and 4664-4725). nozzle_diameter is deliberately not treated
    as physical because the research records its per-filament slicing meaning.
    """
    settings, manifest = _settings(source)
    return _reader("forcaslicer", settings, _FORCA_KEYS,
                   require=("fos_physical_nozzle_diameter",), manifest=manifest)


def read_lixnix(source: bytes | dict) -> CreativeProject:
    """Read the published LixNix per-extruder height settings.

    Shape references: saved device-research entry Full Multi-Nozzle/LixNix
    lines 155-168; source blob receipts `lix_config` (PrintConfig.cpp lines
    5600-5622) and `lix_plan` (Slicing.hpp lines 212-289).
    """
    settings, manifest = _settings(source)
    result = _reader("lixnix", settings, _LIX_KEYS,
                     require=("extruder_layer_height", "extruder_layer_height_exact"), manifest=manifest)
    heights = settings.get("extruder_layer_height")
    if settings.get("extruder_layer_height_exact") is True and (not isinstance(heights, list) or not heights):
        result.diagnostics = ("exact_flag_without_layer_height_values",)
    return result


def _parse_fullspectrum(raw: Any) -> tuple[tuple[VirtualRecipe, ...], tuple[int, ...], bool]:
    if not isinstance(raw, str) or not raw:
        return (), (), isinstance(raw, str)
    recipes = []
    slots: set[int] = set()
    valid = True
    for index, row in enumerate(raw.split(";")):
        if not row:
            continue
        parts = row.split(",")
        if len(parts) < 6 or any(not token.isdigit() for token in parts[:6]):
            valid = False
            continue
        a, b = int(parts[0]), int(parts[1])
        if (a <= 0 or b <= 0 or parts[2] not in ("0", "1") or parts[3] not in ("0", "1")
                or not 0 <= int(parts[4]) <= 100):
            valid = False
            continue
        source_ids = [a, b]
        for token in parts[6:]:
            if token == "g":
                continue
            if token.startswith("g"):
                gradient_ids = token[1:]
                if not gradient_ids.isdigit() or "0" in gradient_ids:
                    valid = False
                    continue
                source_ids.extend(int(digit) for digit in gradient_ids)
        # The row names source component ids. Ratios are not asserted by this
        # compact row grammar; preserve them as unknown.
        unique_ids = tuple(dict.fromkeys(source_ids))
        slots.update(unique_ids)
        components = [RecipeComponent(f"project:1:{n}", None, "unknown") for n in unique_ids]
        stable_ids = [token[1:] for token in parts[6:] if token.startswith("u") and token[1:].isdigit()]
        recipe_id = f"fullspectrum:{stable_ids[0]}" if len(stable_ids) == 1 else f"fullspectrum:row-{index}"
        recipes.append(VirtualRecipe(recipe_id, {"name": "FullSpectrum", "version": "0.9.12"},
                                     "fullspectrum", components, False))
    return tuple(recipes), tuple(sorted(slots)), valid


def read_fullspectrum(source: bytes | dict) -> CreativeProject:
    """Read the documented FullSpectrum mixed-row field into simulated recipes.

    Shape references: saved workflow-research entry `xipit-fullspectrum-ui`
    lines 232-272 and the captured v0.9.12 packaging notes lines 74-76,
    162-211. The draft vnext schema is intentionally not read.
    """
    settings, manifest = _settings(source)
    result = _reader("fullspectrum", settings, _FULLSPECTRUM_KEYS,
                     require=("mixed_filament_definitions",), manifest=manifest)
    raw = settings.get("mixed_filament_definitions")
    result.recipes, result.source_component_ids, valid = _parse_fullspectrum(raw)
    result.physical_slots_needed = len(result.source_component_ids) if valid else None
    if raw is not None and (not isinstance(raw, str) or not valid):
        result.unknown = tuple(sorted((*result.unknown, "mixed_filament_definitions")))
        result.understood.pop("mixed_filament_definitions", None)
        result.diagnostics = ("unrecognized_fullspectrum_row_shape",)
    return result


def read_imagemap(data: bytes) -> CreativeProject:
    """Preserve ImageMap content while reporting its untraced serialized shape.

    Shape references: saved creative-research entry OrcaSlicer-ImageMap lines
    138-156. It explicitly records that the exact 3MF carrier remains untraced;
    this reader therefore makes no field-level compatibility claim.
    """
    manifest = read_3mf(data)
    identity = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    passed = tuple({"name": item.name, "sha256": item.sha256} for item in manifest.members)
    return CreativeProject("imagemap", identity, {}, passed,
                           ("ImageMap serialized metadata carrier and zone shape",),
                           diagnostics=("shape_not_established_in_research",))


def read_lumina(data: bytes, *, file_id: str | None = None) -> CreativeProject:
    """Return identity for a Lumina-produced 3MF without interpreting its settings.

    Shape references: saved creative-research entry Lumina Layers lines 80-105
    and source receipt `creative/Lumina-Layers/api__routers__converter.py`
    lines 192-268, 469, 609, 730, 832 (generated files retrieved by file id).
    """
    manifest = read_3mf(data)
    name = "lumina:3mf"
    identity = {"file_id": file_id, "artifact_name": name, "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
    passed = tuple({"name": item.name, "sha256": item.sha256} for item in manifest.members)
    return CreativeProject("lumina", identity, {"3mf_artifact_identity": identity}, passed,
                           ("Lumina generation provenance",))


def read_project_settings(data: bytes) -> tuple[ThreeMFManifest, dict]:
    """Convenience seam used by 3MF format adapters."""
    manifest = read_3mf(data)
    return manifest, manifest.project_settings or {}
