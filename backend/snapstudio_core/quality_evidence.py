"""Print Quality Doctor — evidence aggregation (pure).

Given a symptom and the OTHER doctors' results for the same file (mesh, insights,
bed-fit, first-layer), produce a short list of file-specific evidence items so the
advice is grounded in *this* model instead of generic tips. Pure + defensive: every
field is read with .get(), missing doctors simply yield no evidence. Advisory only —
no guarantees, no auto-fix.
"""
from __future__ import annotations

LEVELS = ("ok", "warn", "risk")


def _lvl(v) -> str:
    v = (v or "").lower() if isinstance(v, str) else ""
    return v if v in LEVELS else "warn"


def _kw(symptom: str, *needles: str) -> bool:
    s = (symptom or "").lower()
    return any(n in s for n in needles)


def evidence_for(symptom: str, mesh: dict | None, insights: dict | None,
                 bed_fit: dict | None, first_layer: dict | None) -> list[dict]:
    """Return [{label, level, text, doctor}] grounded in this file. Best-effort."""
    out: list[dict] = []
    mesh = mesh or {}
    insights = insights or {}
    bed_fit = bed_fit or {}
    first_layer = first_layer or {}
    overhang = mesh.get("overhang") or {}
    stability = mesh.get("stability") or {}
    footprint = mesh.get("footprint") or {}
    # Footprint area and heights are raw-mesh numbers; without an established physical size they
    # are not evidence, so they are not offered as such.
    if not (mesh.get("geometry_basis") or {}).get("established", True):
        footprint = {}
        stability = {k: v for k, v in stability.items() if k == "tip_risk"}

    def add(label, level, text, doctor):
        if text:
            out.append({"label": label, "level": _lvl(level), "text": text, "doctor": doctor})

    # Bed adhesion / first layer / warping — contact area + bed fit + first-layer doctor.
    if _kw(symptom, "bed", "adhesion", "first_layer", "first layer", "warp", "lift"):
        if bed_fit.get("overall_level"):
            add("Bed fit", bed_fit["overall_level"],
                bed_fit.get("overall_text") or "Bed-fit check ran on this file.", "Bed Fit Doctor")
        ba = footprint.get("base_area_mm2")
        if ba is not None:
            small = ba < 400
            add("Footprint", "warn" if small else "ok",
                f"First-layer contact area is about {round(ba)} mm²"
                + (" — small footprints lift more easily." if small else " — a reasonable contact area."),
                "Mesh")
        for f in (first_layer.get("findings") or [])[:2]:
            if f.get("text"):
                add("First layer", f.get("level"), f["text"], "First Layer Doctor")

    # Supports / overhang / bridging — overhang %, supports-likely, tip risk.
    if _kw(symptom, "support", "overhang", "bridg"):
        if overhang.get("supports_likely") is not None:
            likely = bool(overhang["supports_likely"])
            sev = overhang.get("severe_pct")
            add("Overhangs", "risk" if likely else "ok",
                ("This model likely needs supports"
                 + (f" (~{round(sev)}% steep overhangs)." if isinstance(sev, (int, float)) else ".")) if likely
                else "Overhangs look mild — supports may not be needed.", "Mesh")
        if stability.get("tip_risk"):
            add("Stability", "risk", "Tall/narrow shape — it can tip or shift mid-print; check brim/supports.", "Mesh")

    # Warping detail — tall + narrow.
    if _kw(symptom, "warp", "lift", "layer_shift", "shift"):
        md = footprint.get("min_dim_mm"); h = stability.get("height_mm"); asp = stability.get("aspect")
        if isinstance(asp, (int, float)) and asp >= 3:
            add("Proportions", "warn",
                f"Tall and narrow (aspect ~{round(asp, 1)}"
                + (f", height ~{round(h)} mm" if isinstance(h, (int, float)) else "") + ") — more prone to warping/shift.",
                "Mesh")
        elif isinstance(md, (int, float)) and md < 10:
            add("Proportions", "warn", f"Thin features (~{round(md)} mm) — corners lift more easily.", "Mesh")

    # Stringing / under-extrusion / temperature — material types.
    if _kw(symptom, "string", "ooz", "extru", "temp"):
        mats = insights.get("materials") or []
        types = sorted({(m.get("type") or "").upper() for m in mats if m.get("type")})
        if types:
            add("Materials", "warn" if any(t in ("PETG", "TPU", "SILK", "PLA-SILK") for t in types) else "ok",
                "Filament types in this file: " + ", ".join(types)
                + (" — these string more; tune retraction/temperature." if any(t in ("PETG", "TPU") for t in types) else "."),
                "Project Doctor")

    # Colour / tool-change — colour count.
    if _kw(symptom, "color", "colour", "tool", "change", "multi"):
        c = insights.get("colors")
        if isinstance(c, int) and c > 1:
            add("Colours", "warn", f"This file uses {c} colours — colour/tool-change issues scale with colour count; "
                                   "check purge and flush volumes in Orca.", "Project Doctor")

    return out
