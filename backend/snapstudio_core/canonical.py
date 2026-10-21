"""Canonical project representation — the smallest source-neutral view of a
design, the seam where multi-ecosystem support begins.

This is deliberately a THIN layer over the existing engine: it reuses Project
Intelligence (`project_info`) for the common reads and only adds what the
intelligence layer doesn't yet normalize — chiefly Prusa's INI-style config, so
a Prusa file's materials/printer surface in the same shape as a Bambu file's.

It does NOT convert, mutate, or rewrite anything. Read-only. The converter is
untouched; this just gives every ecosystem one structure to be read through.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .intelligence import project_info
from .container import ThreeMF

SCHEMA_VERSION = "canonical/1"
PRUSA_CONFIG = "Metadata/Slic3r_PE.config"


@dataclass
class Material:
    color: str | None = None
    type: str | None = None


@dataclass
class CanonicalProject:
    """One source-neutral view of a design. Every field is derived from the
    file or the existing engine — no invention, no defaults that hide ignorance."""
    schema_version: str = SCHEMA_VERSION
    name: str = ""
    source_family: str | None = None        # bambu-family | prusa | cura | generic | stl
    source_application: str | None = None
    source_printer_model: str | None = None
    objects: int | None = None
    plates: int | None = None
    materials: list[Material] = field(default_factory=list)
    color_count: int | None = None
    painted: bool | None = None
    dimensions_mm: dict | None = None
    geometry_basis: dict | None = None   # whether dimensions_mm is the physical size
    triangles: int | None = None
    complexity: str | None = None
    verdict: str | None = None
    readiness_score: int | None = None
    notes: list[str] = field(default_factory=list)  # ecosystem caveats

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_prusa_ini(raw: bytes) -> dict:
    """PrusaSlicer's Slic3r_PE.config is `key = value` INI. Multi-material values
    are ';'-separated. Returns a flat dict; list-valued keys stay as lists."""
    out: dict = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        out[key] = [v.strip() for v in val.split(";")] if ";" in val else val
    return out


def _prusa_extras(path: str) -> tuple[list[Material], str | None]:
    """Pull materials + printer model from a Prusa 3MF's INI config. The
    intelligence layer only reads Bambu JSON, so Prusa needs this to be visible
    in the canonical model — this is exactly the seam Prusa support extends."""
    try:
        tm = ThreeMF.open(path)
        if not tm.has_part(PRUSA_CONFIG):
            return [], None
        cfg = _parse_prusa_ini(tm.read_part(PRUSA_CONFIG))
    except Exception:
        return [], None
    colors = cfg.get("filament_colour") or cfg.get("extruder_colour") or []
    types = cfg.get("filament_type") or []
    if isinstance(colors, str): colors = [colors]
    if isinstance(types, str): types = [types]
    mats = [Material(color=c, type=(types[i] if i < len(types) else None))
            for i, c in enumerate(colors)]
    pm = cfg.get("printer_model")
    return mats, (pm if isinstance(pm, str) else None)


def to_canonical(path: str) -> CanonicalProject:
    """Build the canonical view of a design from the existing engine reads.
    Read-only; never raises on ecosystem extras (best-effort enrichment)."""
    info = project_info(path)
    family = info.get("source_family")
    is_stl = (info.get("source_type") == "stl")

    materials = [Material(color=m.get("color"), type=m.get("type"))
                 for m in (info.get("materials") or [])]
    printer_model = None
    notes: list[str] = []

    if family == "prusa":
        prusa_mats, printer_model = _prusa_extras(path)
        if prusa_mats:
            materials = prusa_mats
        # Honesty note: today's converter geometry-wraps Prusa; multi-material
        # intent is detected here but not yet preserved through conversion.
        if len(materials) > 1:
            notes.append("Prusa multi-material detected — colors are read, but "
                         "conversion currently wraps geometry without per-object "
                         "color assignment.")

    # Bambu fingerprint counts filaments from its JSON; Prusa/STL have none there,
    # so fall back to the materials we actually parsed.
    color_count = info.get("colors") or (len(materials) if materials else None)

    return CanonicalProject(
        name=info.get("name") or Path(path).name,
        source_family=("stl" if is_stl else family),
        source_application=None,
        source_printer_model=printer_model,
        objects=info.get("objects"),
        plates=info.get("plates"),
        materials=materials,
        color_count=color_count,
        painted=info.get("painted"),
        dimensions_mm=info.get("dimensions_mm"),
        geometry_basis=info.get("geometry_basis"),
        triangles=info.get("triangles"),
        complexity=info.get("complexity"),
        verdict=info.get("verdict"),
        readiness_score=info.get("readiness_score"),
        notes=notes,
    )
