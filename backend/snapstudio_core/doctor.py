from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from .container import ThreeMF
from .config_io import load_project_settings
from .detect import detect_source
from .fingerprint import compute_fingerprint
from .validate import validate
from .rules import load_rules
from .filaments import PER_FILAMENT_KEYS

SETTINGS = "Metadata/project_settings.config"
SCHEMA_VERSION = "doctor/1"

# verdicts
READY = "READY"               # loads cleanly on the U1 as-is
REPAIRABLE = "REPAIRABLE"      # well-formed project, fixable with `repair`
HIGH_RISK = "HIGH_RISK"        # not a usable project (broken / not a 3MF)
CONVERTIBLE = "CONVERTIBLE"    # an STL - convert it with `repair`


@dataclass
class Diagnosis:
    verdict: str
    score: int | None
    family: str
    printer_model: str | None
    is_u1: bool
    object_count: int
    plate_count: int
    filament_count: int
    painted: bool
    input_type: str = "3mf"
    validation_issues: list = field(default_factory=list)
    compatibility_issues: list = field(default_factory=list)
    recommended_action: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        d["is_compatible"] = self.verdict == READY
        return d


def _bad_slicer_values(cfg: dict) -> list[str]:
    """Read-only: list known-incompatible values without mutating (mirrors apply_clamps)."""
    out = []
    for c in load_rules()["clamps"]:
        k = c["key"]
        if k in cfg and str(cfg[k]) == c["bad"]:
            out.append(f"{k}={c['bad']}")
    return out


def _filament_inconsistencies(cfg: dict) -> list[str]:
    """Per-filament arrays must all match the filament count; purge structures must be N*N / N*2."""
    out = []
    n = len(cfg.get("filament_colour", []))
    if not n:
        return out
    for k in PER_FILAMENT_KEYS:
        v = cfg.get(k)
        if isinstance(v, list) and len(v) != n:
            out.append(f"{k} length {len(v)} != filament count {n}")
    m = cfg.get("flush_volumes_matrix")
    if isinstance(m, list) and len(m) != n * n:
        out.append(f"flush_volumes_matrix length {len(m)} != {n * n}")
    return out


def diagnose(tm: ThreeMF) -> Diagnosis:
    """Diagnose a 3MF project (in-memory). Read-only. Score calculation unchanged."""
    src = detect_source(tm)
    fp = compute_fingerprint(tm)
    res = validate(tm, against=None)
    cfg = load_project_settings(tm.read_part(SETTINGS)) if tm.has_part(SETTINGS) else {}

    validation_issues = [e for e in res.errors if e.startswith("missing required part")]
    compatibility_issues: list[str] = []
    score = 100

    if not res.structural_ok:
        score -= 50

    if src.family != "bambu-family":
        compatibility_issues.append(f"source family is {src.family}, not bambu-family")
        score -= 15

    if not src.is_u1:
        compatibility_issues.append(
            f"printer identity is {src.printer_model!r}, not Snapmaker U1")
        score -= 20

    for bad in _bad_slicer_values(cfg):
        compatibility_issues.append(f"incompatible slicer value: {bad}")
        score -= 10

    fil = _filament_inconsistencies(cfg)
    if fil:
        compatibility_issues.append("filament metadata inconsistent: " + "; ".join(fil))
        score -= 15

    score = max(0, min(100, score))
    # The same structure gate Prepare runs, applied to the source: a file Prepare
    # would refuse must not be sent to Prepare.
    from .convert import structure_problems
    try:
        structure = structure_problems(tm)
    except Exception:  # noqa: BLE001 — a doctor never fails on an unreadable corner
        structure = []
    validation_issues.extend(structure)
    painted = sum(fp.painted_triangles.values()) > 0

    if not res.structural_ok:
        verdict = HIGH_RISK
        action = "This file is not a usable U1 project (missing required parts); repair may not recover it."
    elif structure:
        # Checked BEFORE the score-based READY: a genuine U1 project that Prepare would
        # refuse must not be told "open it and slice". Minimal change: schema doctor/1
        # and the verdict set are unchanged; HIGH_RISK is shown as "needs review".
        verdict = HIGH_RISK
        action = ("Studio has not verified this file: it carries settings or structure "
                  "Studio cannot confirm Snapmaker Orca reads, so it will not prepare a copy "
                  "and does not call it ready. Your original is not changed. Open it in "
                  "Snapmaker Orca to review it.")
    elif score == 100 and not compatibility_issues:
        verdict = READY
        action = "Ready for Snapmaker U1 - open it in Snapmaker Orca and slice."
    else:
        verdict = REPAIRABLE
        action = "Prepare a U1 profile copy, then review it in Snapmaker Orca before slicing."

    return Diagnosis(
        verdict=verdict, score=score, family=src.family, printer_model=src.printer_model,
        is_u1=src.is_u1, object_count=fp.object_count, plate_count=fp.plate_count,
        filament_count=fp.filament_count, painted=painted, input_type="3mf",
        validation_issues=validation_issues, compatibility_issues=compatibility_issues,
        recommended_action=action,
    )


def _stl_design_score(md: dict) -> int | None:
    """A 0-100 design-health score for a readable STL mesh — geometry quality only
    (an STL carries no U1 profile to judge, so this is mesh health, not profile
    compatibility). None when the mesh can't be read."""
    if not md.get("available"):
        return None
    s = 100
    integ = md.get("integrity") or {}
    if not integ.get("watertight"):
        s -= 25
        if integ.get("non_manifold_edges"):
            s -= 10
    if (md.get("overhang") or {}).get("supports_likely"):
        s -= 15
    if (md.get("stability") or {}).get("tip_risk"):
        s -= 15
    return max(0, min(100, s))


def diagnose_path(path) -> Diagnosis:
    """Entry point: classify by file type, then diagnose. Read-only."""
    p = Path(path)
    if p.suffix.lower() == ".stl":
        # An STL has real geometry but no U1 profile. Score its DESIGN HEALTH from
        # the mesh (separate from U1-profile preparation); only fall back to "—"
        # when the geometry genuinely can't be read. Never show CLI text in the GUI.
        from .mesh_diagnostics import analyze as _mesh
        md = _mesh(str(path))
        if md.get("available"):
            score = _stl_design_score(md)
            action = "Create a U1 profile copy, then review it in Snapmaker Orca before slicing."
            issues: list = []
        else:
            score = None
            action = ("Studio could not read the geometry from this STL. Try opening it in "
                      "Snapmaker Orca, or export it again from the source.")
            issues = ["Geometry could not be read from this STL."]
        return Diagnosis(
            verdict=CONVERTIBLE, score=score, family="stl", printer_model=None, is_u1=False,
            object_count=0, plate_count=0, filament_count=0, painted=False, input_type="stl",
            validation_issues=issues, recommended_action=action)
    try:
        tm = ThreeMF.open(path)
    except Exception:
        return Diagnosis(
            verdict=HIGH_RISK, score=0, family="unknown", printer_model=None, is_u1=False,
            object_count=0, plate_count=0, filament_count=0, painted=False, input_type="unknown",
            validation_issues=["not a valid 3MF/ZIP archive"],
            recommended_action="This file is not a 3MF project and cannot be diagnosed.")
    return diagnose(tm)
