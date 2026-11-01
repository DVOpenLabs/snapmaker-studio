"""The explicit list of input formats the Creative inspector supports, and what each one reads.

This table is the contract returned by `POST /creative/formats` and mirrored in
docs/internal/CREATIVE_COMPAT.md. Support is never inferred from generic ZIP inspection: a format is
listed only with the carrier, the documented markers or keys, what is established and what is not.
"""
from __future__ import annotations

from . import generators, readers

EVIDENCE = "fixture-tested"
_CARRIER = "3MF (ZIP) with 3D/3dmodel.model in the 3MF core namespace"

SUPPORTED_FORMATS: tuple[dict, ...] = (
    {"key": "ditherforge", "label": "DitherForge", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": list(generators.MARKERS["ditherforge"]),
     "reads": ["application tag and variant", "object part files", "triangle and painted-triangle counts",
               "paint extruders used (documented 1-2 character paint_color values)",
               "object names and extruders from model_settings.config",
               "filament_colour, filament_type, printer_settings_id, print_settings_id"],
     "kept_untouched": ["every other part and settings key, by name and SHA-256"],
     "not_read": ["geometry beyond counts", "longer paint_color strings (split-triangle encoding)",
                  "settings JSON and collection TXT written beside the 3MF"],
     "prepare_limits": ["Prepare works on the Bambu-path export (Application tag BambuStudio-<version>+ditherforge-<version>).",
                        "The generic-path export writes part id 1 under a component with objectid 2 or more. Studio's "
                        "structure check does not accept that, so such a file is inspect-only: Prepare refuses it and "
                        "writes nothing."],
     "upstream": "rtwfroody/ditherforge (MIT) 4d3552a434e8084d9b5fe573959a3493325be29f"},
    {"key": "kromacut", "label": "Kromacut", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": list(generators.MARKERS["kromacut"]),
     "reads": ["layer height and first layer height metadata", "colour layer object count and assembly object",
               "parts and their extruders from model_settings.config", "base material colours",
               "filament_colour, layer_height, initial_layer_print_height"],
     "kept_untouched": ["Metadata/kromacut.config and every other part, by name and SHA-256"],
     "not_read": ["the payload of Metadata/kromacut.config", "mesh geometry",
                  "optional custom metadata files"],
     "upstream": "vycdev/Kromacut (AGPL-3.0, format only) 94874755426ee7f33b3684a5544e7fab0e2e73f7"},
    {"key": "sindricad", "label": "SindriCAD", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": list(generators.MARKERS["sindricad"]),
     "reads": ["named bodies with palette slot (pindex) and extruder", "palette base materials",
               "per-face paint (documented 1-2 character paint_color values)",
               "filament_colour and filament_type"],
     "kept_untouched": ["every other part and settings key, by name and SHA-256"],
     "not_read": ["mesh geometry beyond counts", "longer paint_color strings"],
     "upstream": "MakerViking/sindricad (AGPL-3.0, format only) 8b2e9dc4f82fba58b39c206c993534c487cc1eab"},
    {"key": "forcaslicer", "label": "FOrcaSlicer", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": ["published fos_*, mms_* and color_patch_* keys in project_settings.config"],
     "reads": sorted(readers._FORCA_KEYS), "kept_untouched": ["all other keys and parts"],
     "not_read": ["unknown fos_* keys", "plain nozzle_diameter as a physical value"], "upstream": None},
    {"key": "lixnix", "label": "LixNix Full Multi-Nozzle", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": sorted(readers._LIX_KEYS), "reads": sorted(readers._LIX_KEYS),
     "kept_untouched": ["all other keys and parts"], "not_read": ["effective heights", "unpublished variants"],
     "upstream": None},
    {"key": "fullspectrum", "label": "FullSpectrum 0.9.12", "carrier": _CARRIER, "selection": "automatic",
     "identified_by": sorted(readers._FULLSPECTRUM_KEYS), "reads": ["mixed_filament_definitions rows (simulated recipes)"],
     "kept_untouched": ["all other keys and parts"],
     "not_read": ["ratios", "pattern semantics", "execution", "the draft vnext schema"], "upstream": None},
    {"key": "imagemap", "label": "OrcaSlicer ImageMap", "carrier": _CARRIER, "selection": "manual only",
     "identified_by": [], "reads": ["3MF artifact identity (size, SHA-256, member list)"],
     "kept_untouched": ["every part, by name and SHA-256"],
     "not_read": ["the zone shape: the exact serialized carrier is not established, so no zone claim is made"],
     "upstream": None},
    {"key": "lumina", "label": "Lumina Layers", "carrier": _CARRIER, "selection": "manual only",
     "identified_by": [], "reads": ["3MF artifact identity (size, SHA-256, member list)"],
     "kept_untouched": ["every part, by name and SHA-256"],
     "not_read": ["generation provenance", "session behaviour", "file-ID lifetime"], "upstream": None},
)

KEYS = tuple(f["key"] for f in SUPPORTED_FORMATS)
MANUAL_ONLY = tuple(f["key"] for f in SUPPORTED_FORMATS if f["selection"] == "manual only")
LABELS = {f["key"]: f["label"] for f in SUPPORTED_FORMATS}
