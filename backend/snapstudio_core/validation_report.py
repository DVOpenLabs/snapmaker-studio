"""Validation Center — a readiness + preservation report for a design, read-only.

Answers, in plain terms: will it print on the U1, what will be preserved, what
will change, and what (if anything) is at risk — derived from the Doctor
diagnosis, the project settings, and real geometry. No mutation, no fake data.

Note on colours: the Snapmaker U1 supports more colours than toolheads (real U1
exports carry up to 8 colours on 4 toolheads), so colour count is NOT capped on
conversion — colours are preserved, not lost.
"""
from __future__ import annotations
from pathlib import Path

from .doctor import diagnose_path, READY, CONVERTIBLE
from .intelligence import project_info
from .container import ThreeMF
from .config_io import load_project_settings
from .collision import assess_spacing

SCHEMA_VERSION = "report/1"
SETTINGS = "Metadata/project_settings.config"
# Approx U1 build volume (mm) from the U1 printable_area; used for a bed-fit check.
# Printable volume per the Snapmaker Orca U1 machine profile (printable_area
# 270x270, printable_height 270.05). Moonraker's axis_maximum reports travel
# limits (~271x335x275), not printable area — do not "correct" this to those.
U1_BUILD = (270.0, 270.0, 270.0)
U1_TOOLHEADS = 4  # the U1 has 4 toolheads; more colours need swaps/remap in Orca


def _check(name, ok, detail):
    return {"name": name, "status": "pass" if ok else "warn", "detail": detail}


def readiness_report(path: str) -> dict:
    info = project_info(path, placement_aware=True)
    diag = diagnose_path(path).to_dict()
    is_stl = diag.get("input_type") == "stl"
    verdict = diag.get("verdict")
    dims = info.get("dimensions_mm")
    colors = info.get("colors") or 0

    checks, preserved, changes, at_risk = [], [], [], []
    warnings = list(info.get("issues") or [])

    # --- compatibility checks -------------------------------------------------
    checks.append(_check(
        "Fits U1 profile checks",
        verdict in (READY, CONVERTIBLE, "REPAIRABLE"),
        "Prepare a U1 copy and review in Orca" if verdict != READY
        else "Review in Orca before slicing"))
    # SIZE, not position: each object against the bed on its own. Where the objects sit on the plate is
    # judged below under "Layout / plate fit", and the combined extents of several separated objects or
    # plates are never read as one big object. No per-object size means UNKNOWN, not the overall extents.
    sized = [o for o in (info.get("object_sizes_mm") or []) if o.get("dimensions_mm")]
    unmeasured = info.get("objects_unmeasured") or 0
    if sized:
        def _over(entry):
            d = entry["dimensions_mm"]
            return d["x"] > U1_BUILD[0] or d["y"] > U1_BUILD[1] or d["z"] > U1_BUILD[2]
        too_big = [o for o in sized if _over(o)]
        many = len(sized) > 1

        def _name(entry):
            return f'object {entry["object_id"]} ' if many and entry.get("object_id") is not None else ""

        bed_text = f"{U1_BUILD[0]:.0f} × {U1_BUILD[1]:.0f} × {U1_BUILD[2]:.0f} mm bed"
        if too_big:
            d = too_big[0]["dimensions_mm"]
            detail = (f'By size, {_name(too_big[0])}({d["x"]} × {d["y"]} × {d["z"]} mm) is larger than the U1 '
                      "bed — scale it down or split it."
                      if many else
                      f'By size, {d["x"]} × {d["y"]} × {d["z"]} mm is larger than the U1 bed — '
                      "scale it down or split it.")
            if len(too_big) > 1:
                detail += f" {len(too_big)} objects are larger than the bed."
        else:
            largest = max(sized, key=lambda o: o["dimensions_mm"]["x"] * o["dimensions_mm"]["y"])
            d = largest["dimensions_mm"]
            detail = (f'By size, the largest object ({_name(largest).strip()}, {d["x"]} × {d["y"]} × '
                      f'{d["z"]} mm) fits the U1\'s {bed_text}.'
                      if many else
                      f'By size, {d["x"]} × {d["y"]} × {d["z"]} mm fits the U1\'s {bed_text}.')
        if unmeasured:
            detail += (f" {unmeasured} build item{'s' if unmeasured != 1 else ''} could not be measured, "
                       "so Studio cannot say whether everything fits.")
        checks.append(_check("Fits the print bed", not too_big and not unmeasured, detail))
    elif dims:
        from .bed_fit import UNMEASURED_TEXT
        checks.append(_check("Fits the print bed", False, UNMEASURED_TEXT))
    if colors:
        colors_ok = colors <= U1_TOOLHEADS
        checks.append(_check(
            "Colours vs toolheads", colors_ok,
            f"{colors} colour(s) on {U1_TOOLHEADS} toolheads — prints directly"
            if colors_ok
            else f"{colors} colour(s) but the U1 has {U1_TOOLHEADS} toolheads — plan colour swaps "
                 f"or remap to {U1_TOOLHEADS} colours in Snapmaker Orca before slicing"))

    # --- preservation ---------------------------------------------------------
    preserved.append("3D geometry (mesh) — kept exactly")
    if colors:
        preserved.append(f"{colors} material colour(s)")
    if diag.get("painted"):
        preserved.append("painted / multi-colour regions")
    if (info.get("objects") or 0) > 1 or (info.get("plates") or 0) > 1:
        preserved.append("object layout and plates")

    # --- changes + at-risk ----------------------------------------------------
    if is_stl:
        changes.append("Wrapped into a native Snapmaker U1 project")
    else:
        cfg = {}
        try:
            tm = ThreeMF.open(path)
            if tm.has_part(SETTINGS):
                cfg = load_project_settings(tm.read_part(SETTINGS))
        except Exception:
            pass
        if cfg.get("printer_model") not in (None, "Snapmaker U1"):
            changes.append(f'Printer identity → Snapmaker U1 (was {cfg.get("printer_model")})')
        dss = cfg.get("different_settings_to_system")
        if (isinstance(dss, list) and any(str(x) for x in dss)) or (isinstance(dss, str) and dss):
            changes.append("Customized-preset markers cleared so Orca opens it clean — your setting values are kept")
        if cfg.get("print_sequence") not in (None, "by layer"):
            at_risk.append('Print order changes from "by object" to "by layer" (avoids a collision warning; re-enable in Orca if you need by-object)')
        if not changes and verdict == READY:
            changes.append("Already U1-compatible — no settings changes needed")

    # --- design (mesh) checks — best-effort, read-only; never break the report ----
    design_findings = []
    try:
        from .mesh_diagnostics import analyze as _mesh
        md = _mesh(path)
        if md.get("available"):
            integ = md["integrity"]
            if not integ["watertight"]:
                if integ["holes"]:
                    checks.append(_check("Mesh is watertight", False,
                        f"{integ['holes']} hole(s) — may print with gaps or fail; repair before printing"))
                if integ["non_manifold_edges"]:
                    checks.append(_check("Mesh is manifold", False,
                        f"{integ['non_manifold_edges']} non-manifold edge(s) — slicers may misread the surface; repair recommended"))
            else:
                checks.append(_check("Mesh is watertight", True, "Closed, manifold mesh — readable by the slicer"))
            if md["overhang"]["supports_likely"]:
                checks.append(_check("Overhangs", False,
                    f"{md['overhang']['overhang_pct']}% steep overhangs — supports will likely be needed (enable in Orca)"))
            if md["stability"]["tip_risk"]:
                checks.append(_check("Stability", False,
                    "Tall/narrow base — may tip or knock off the bed; add a brim or reorient"))
            design_findings = md.get("findings", [])
            warnings.extend(f["text"] for f in design_findings if f["level"] in ("warn", "risk"))
    except Exception:
        pass

    # Print-setup risks that block a clean "U1-ready" even when the U1 profile is compatible.
    if colors and colors > U1_TOOLHEADS:
        at_risk.append(
            f"{colors} colours but the U1 has {U1_TOOLHEADS} toolheads — plan colour swaps "
            f"or remap to {U1_TOOLHEADS} colours in Snapmaker Orca before slicing")
    if any("steep overhangs" in w or "supports" in w for w in warnings):
        at_risk.append("Supports likely needed — enable/check them in Snapmaker Orca before slicing")
    # Real layout / plate-fit detection (3MF only — STL is wrapped into a fresh centred project).
    layout = None
    if not is_stl:
        try:
            from .layout import assess_layout
            layout = assess_layout(path)
        except Exception:
            # A crash in layout analysis must NOT silently let the file pass as ready —
            # fall back to an explicit "unknown" that blocks readiness.
            layout = {"status": "unknown", "plates": 0, "object_count": 0,
                      "messages": ["Layout couldn't be checked — open in Snapmaker Orca and use "
                                   "Arrange all plates to confirm placement before slicing."]}
        if layout["status"] != "pass":
            checks.append(_check(
                "Layout / plate fit",
                False,
                layout["messages"][0] if layout["messages"] else "Layout needs review in Snapmaker Orca"))
            at_risk.extend(layout["messages"])

    # Object spacing / collisions — Studio does not yet verify object-to-object
    # spacing for multi-object 3MF layouts, so report an honest 'unknown' that
    # blocks a green "ready". A wrong collision guess would be worse than this.
    spacing = assess_spacing(info.get("objects"), is_stl)
    if spacing["status"] != "pass":
        checks.append(_check("Object spacing / collisions", False, spacing["messages"][0]))
        at_risk.extend(spacing["messages"])

    # Honest readiness: a failed check OR any at-risk item blocks a green verdict.
    # (Do not let a compatible profile verdict override real print-setup risks.)
    ready = all(c["status"] == "pass" for c in checks) and not at_risk
    base = diag.get("score")
    score = base
    if not ready and isinstance(base, (int, float)):
        score = min(int(base), 70)   # not a perfect score while setup review remains
    # Profile may be compatible, but if setup review remains do not surface a green "ready".
    out_verdict = "HIGH_RISK" if (not ready and verdict == READY) else verdict
    return {
        "schema_version": SCHEMA_VERSION,
        "name": Path(path).name,
        "verdict": out_verdict,
        "profile_verdict": verdict,        # the underlying U1-profile compatibility verdict
        "readiness_score": score,
        "ready": bool(ready),
        "print_setup_ready": bool(ready),
        "checks": checks,
        "preserved": preserved,
        "changes": changes,
        "at_risk": at_risk,
        "warnings": warnings,
        "layout_status": layout["status"] if layout else None,
        "layout_messages": layout["messages"] if layout else [],
        "collision_status": spacing["status"],
        "collision_messages": spacing["messages"],
    }
