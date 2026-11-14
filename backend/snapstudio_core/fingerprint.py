from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from .container import ThreeMF
from .config_io import load_project_settings

PAINT_TOKENS = (b"paint_color", b"paint_supports", b"mmu_segmentation")

@dataclass(frozen=True)
class Fingerprint:
    object_count: int
    painted_triangles: dict
    plate_count: int
    filament_count: int
    filament_colors: tuple
    object_part_sha256: dict

def compute_fingerprint(tm: ThreeMF) -> Fingerprint:
    parts = tm.list_parts()
    model_parts = [p for p in parts if p.endswith(".model")]
    painted, shas, obj_count = {}, {}, 0
    for p in model_parts:
        b = tm.read_part(p)
        obj_count += b.count(b"<object ")
        c = sum(b.count(tok) for tok in PAINT_TOKENS)
        if p.startswith("3D/Objects/"):
            shas[p] = hashlib.sha256(b).hexdigest()
        if c: painted[p] = c
    # Plates are what model_settings.config declares. `Metadata/plate_N.json` is the
    # authoring slicer's slice cache, which Prepare removes on purpose; counting it made
    # every multi-plate project look like it had lost plates.
    plate_count = 0
    if tm.has_part("Metadata/model_settings.config"):
        plate_count = len(re.findall(rb"<plate\b", tm.read_part("Metadata/model_settings.config")))
    if not plate_count:
        plate_count = sum(1 for p in parts if p.startswith("Metadata/plate_") and p.endswith(".json"))
    colors = ()
    if tm.has_part("Metadata/project_settings.config"):
        cfg = load_project_settings(tm.read_part("Metadata/project_settings.config"))
        colors = tuple(cfg.get("filament_colour", []))
    return Fingerprint(obj_count, painted, max(plate_count, 1),
                       len(colors), colors, shas)
