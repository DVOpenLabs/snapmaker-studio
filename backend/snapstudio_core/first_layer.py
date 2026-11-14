"""First-Layer Intelligence — fuse the design with the printer's REAL measured bed.

This is not a bed-mesh viewer. It combines design geometry (footprint / contact area,
height, stability) with the U1's actual probed bed surface (from Moonraker) to answer
one question in plain language: **"Will this print's first layer stick on MY printer?"**

Pure + read-only: takes already-computed design metrics + reduced bed stats, returns
plain-language findings. No network here (the service layer gathers inputs).
"""
from __future__ import annotations

SCHEMA_VERSION = "firstlayer/1"

# Bed flatness bands (mm) under the print's footprint — grounded in typical FDM
# first-layer tolerance: a well-trammed bed stays under ~0.1mm; >0.2mm is visible squish.
_BED_MILD = 0.10
_BED_HIGH = 0.20
# Footprint contact thresholds (mm² / mm) for adhesion.
_FOOT_SMALL_AREA = 100.0
_FOOT_TINY_AREA = 40.0
_FOOT_NARROW_DIM = 10.0
_DEFAULT_BED = 270.0  # printable bed edge per Snapmaker Orca U1 profile (270x270)


def _f(level: str, text: str, id: str | None = None, action: str | None = None) -> dict:
    out = {"level": level, "text": text}
    if id:
        out["id"] = id         # the stable condition id (snapstudio_core.conditions)
    if action:
        out["action"] = action  # the step that belongs to THIS finding
    return out


def assess(footprint: dict | None, stability: dict | None, bed: dict | None,
           bed_dim_mm: float = _DEFAULT_BED) -> dict:
    """Return first-layer findings. `footprint`/`stability` from mesh diagnostics;
    `bed` = reduced bed-mesh stats (or None/unavailable when no printer/mesh)."""
    findings: list = []
    used: list = []
    worst = "ok"

    def bump(level):
        nonlocal worst
        order = {"ok": 0, "warn": 1, "risk": 2}
        if order[level] > order[worst]:
            worst = level

    area = (footprint or {}).get("base_area_mm2")
    min_dim = (footprint or {}).get("min_dim_mm")
    wx = (footprint or {}).get("width_x_mm") or 0.0
    wy = (footprint or {}).get("width_y_mm") or 0.0
    height = (stability or {}).get("height_mm")
    tip = bool((stability or {}).get("tip_risk"))

    # 1. Small / narrow footprint -> adhesion risk.
    if area is not None:
        used.append("contact area")
        if area < _FOOT_TINY_AREA or (min_dim is not None and min_dim < _FOOT_NARROW_DIM / 2):
            bump("risk")
            findings.append(_f("risk", f"Very small base ({area} mm²) — little grips the bed, so it can pop off mid-print. Add a brim or a raft, and slow the first layer.",
                                  id="first-layer-adhesion", action="Add a brim or a raft, and slow the first layer."))
        elif area < _FOOT_SMALL_AREA or (min_dim is not None and min_dim < _FOOT_NARROW_DIM):
            bump("warn")
            findings.append(_f("warn", f"Small base ({area} mm²) — adhesion may be marginal. A brim is a cheap insurance.",
                                  id="first-layer-adhesion", action="Add a brim."))

    # 2. Bed flatness UNDER the print (the open-stack insight).
    bed_ok = bool(bed and bed.get("available"))
    if bed_ok:
        used.append("measured bed mesh")
        big = max(wx, wy) > 0.5 * bed_dim_mm
        region = bed.get("range_mm") if big else (bed.get("center_range_mm") or bed.get("range_mm"))
        where = "across the bed" if big else "under where this print sits (centered)"
        if region is not None:
            if region >= _BED_HIGH:
                bump("risk")
                findings.append(_f("risk", f"Your printer's bed varies about {region} mm {where} — enough to leave the first layer too squished on one side and barely stuck on the other. Re-run bed leveling / Z-tramming, or add a brim and watch the first layer.",
                                  id="first-layer-bed-flatness", action="Re-run bed leveling / Z-tramming, or add a brim and watch the first layer."))
            elif region >= _BED_MILD:
                bump("warn")
                findings.append(_f("warn", f"Your bed varies about {region} mm {where} — a slight first-layer unevenness is possible. A brim helps; a fresh bed mesh helps more.",
                                  id="first-layer-bed-flatness", action="Add a brim, or take a fresh bed mesh."))
            else:
                findings.append(_f("ok", f"Your measured bed is flat ({region} mm {where}) — first layer should lay down evenly."))

    # 3. Corner-lift: wide flat base + tall + uneven bed edges/corners.
    corner = (bed or {}).get("corner_spread_mm") if bed_ok else None
    wide_flat = area is not None and area > 2000.0 and (min_dim or 0) > 40.0
    tall = height is not None and height > 60.0
    if wide_flat and tall:
        if corner is not None and corner >= _BED_MILD:
            bump("risk")
            findings.append(_f("risk", f"Wide flat base + tall print, and your bed's corners differ by ~{corner} mm — corners are likely to lift/warp. Use a brim, ensure good first-layer adhesion, and avoid drafts.",
                                  id="first-layer-corner-lift", action="Use a brim, ensure good first-layer adhesion, and avoid drafts."))
        else:
            bump("warn")
            findings.append(_f("warn", "Wide flat base on a tall print — corners can lift as it cools. A brim and a warm, draft-free area reduce warping.",
                                  id="first-layer-corner-lift", action="Add a brim and keep the print in a warm, draft-free area."))

    # 4. Orientation suggestion.
    if tip or (area is not None and area < _FOOT_SMALL_AREA):
        used.append("stability")
        findings.append(_f("warn", "Consider reorienting so a larger, flatter face sits on the bed — more contact means a more reliable first layer and less tip-over risk.",
                                  id="first-layer-orientation", action="Reorient so a larger, flatter face sits on the bed."))

    if not findings:
        findings.append(_f("ok", "No first-layer red flags — solid contact and (where measured) a flat bed."))

    overall_text = {
        "ok": "Looks good for a clean first layer on your printer.",
        "warn": "A few first-layer precautions worth taking (see below).",
        "risk": "First-layer risk on your printer — take the steps below before printing.",
    }[worst]
    return {
        "schema_version": SCHEMA_VERSION,
        "overall_level": worst,
        "overall_text": overall_text,
        "bed_aware": bed_ok,
        "findings": findings,
        "signals_used": used,
    }
