"""Compatibility Doctor — read-only diagnostics for common Snapmaker U1 /
Snorca / Orca project problems.

STRICTLY READ-ONLY. This module opens the 3MF, inspects
`Metadata/project_settings.config`, and returns findings. It NEVER writes,
mutates a profile, edits g-code, or touches the 3MF writer. It does not claim to
fix anything — it explains the problem and the safest next step.

Detects:
  A. Invalid 3MF/profile values (out-of-range slicer settings).
  B. Non-U1 / suspicious profile signature.
  C. Relative extrusion without a G92 E0 layer reset.
"""
from __future__ import annotations

from .container import ThreeMF
from .config_io import load_project_settings
from .collision import assess_spacing

SETTINGS = "Metadata/project_settings.config"

# key -> (min, max) inclusive valid range. Values below min / above max are flagged.
_RANGE_RULES: list[tuple[str, int, int]] = [
    ("prime_tower_brim_width", 0, 2147483647),
    ("raft_first_layer_expansion", 0, 2147483647),
    ("tree_support_wall_count", 0, 2),
    ("solid_infill_filament", 1, 2147483647),
    ("sparse_infill_filament", 1, 2147483647),
    ("wall_filament", 1, 2147483647),
]


def valid_range(key: str) -> tuple[int, int] | None:
    """The inclusive valid range the Compatibility check applies to a setting, or None if it has none."""
    for k, lo, hi in _RANGE_RULES:
        if k == key:
            return lo, hi
    return None


def _first(v):
    """Orca stores most values as strings or single-element lists; normalize."""
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _num(cfg: dict, key: str):
    """Return a float for a numeric setting, or None if absent/non-numeric."""
    if key not in cfg:
        return None
    raw = _first(cfg[key])
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _truthy(cfg: dict, key: str) -> bool:
    raw = _first(cfg.get(key))
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _text(cfg: dict, key: str) -> str:
    raw = _first(cfg.get(key))
    return "" if raw is None else str(raw)


def _finding(fid, severity, title, explanation, setting_path, action, evidence) -> dict:
    return {
        "id": fid,
        "severity": severity,           # "error" | "warning" | "info"
        "title": title,
        "explanation": explanation,
        "setting_path": setting_path,
        "suggested_action": action,
        "evidence": evidence,
    }


def check(path: str) -> dict:
    """Read-only compatibility check. Returns {findings, summary, recommendation}."""
    tm = ThreeMF.open(path)
    if not tm.has_part(SETTINGS):
        return {
            "findings": [],
            "summary": "No project settings found to check — this looks like a bare "
                       "model (e.g. an STL) rather than a slicer project.",
            "recommendation": "Open it in a clean Snapmaker U1 project to slice.",
        }

    cfg = load_project_settings(tm.read_part(SETTINGS))
    findings: list[dict] = []

    # A. invalid / out-of-range values
    for key, lo, hi in _RANGE_RULES:
        val = _num(cfg, key)
        if val is None:
            continue
        if val < lo or val > hi:
            findings.append(_finding(
                f"value.{key}", "error",
                f"Invalid value for {key}",
                "This file likely carries settings from another printer or a stale "
                "profile (often a MakerWorld/Bambu-style project). The model may be "
                "fine; the project settings are the problem.",
                f"{SETTINGS} -> {key}",
                "Import the model into a clean Snapmaker U1 project instead of opening "
                "the foreign 3MF as the active project.",
                f"{key} = {_first(cfg[key])} (valid range [{lo},{hi}])",
            ))

    # B. non-U1 / suspicious profile signature
    model = _text(cfg, "printer_model")
    settings_id = _text(cfg, "printer_settings_id")
    sig = f"{model} {settings_id}".lower()
    if model or settings_id:
        if "u1" not in sig or "snapmaker" not in sig:
            findings.append(_finding(
                "profile.not_u1", "warning",
                "Profile may not be a Snapmaker U1 profile",
                "This file likely carries settings from another printer. Slicing it "
                "as-is can produce wrong results.",
                f"{SETTINGS} -> printer_model / printer_settings_id",
                "Make sure the active printer profile is Snapmaker U1, or import the "
                "model into a clean Snapmaker U1 project.",
                f"printer_model={model or '(none)'}; printer_settings_id={settings_id or '(none)'}",
            ))

    # C. relative extrusion without a G92 E0 layer reset
    if _truthy(cfg, "use_relative_e_distances"):
        layer_gcode = (_text(cfg, "layer_change_gcode") + "\n"
                       + _text(cfg, "before_layer_change_gcode")).upper()
        if "G92 E0" not in layer_gcode:
            findings.append(_finding(
                "extrusion.relative_no_reset", "warning",
                "Relative extrusion without a per-layer reset",
                "Your profile uses relative extrusion but may not reset the extruder "
                "position each layer. Newer Orca/Snorca versions are stricter about this.",
                f"{SETTINGS} -> layer_change_gcode / before_layer_change_gcode",
                "Switch back to the official Snapmaker U1 profile (or reset the profile). "
                "Only add G92 E0 to the layer-change g-code if you understand the setting.",
                "use_relative_e_distances is enabled; no 'G92 E0' found in layer-change g-code",
            ))

    # Object spacing / collisions are NOT verified by Studio — surface that here so
    # this Doctor never implies a multi-object plate is collision-free.
    try:
        from .fingerprint import compute_fingerprint
        oc = compute_fingerprint(tm).object_count
    except Exception:
        oc = 0
    spacing = assess_spacing(oc, is_stl=False)
    if spacing["status"] != "pass":
        findings.append(_finding(
            "layout.object_spacing", "warning",
            "Object spacing / collisions are not verified by Studio yet",
            "Studio does not yet check object-to-object spacing for multi-part 3MF "
            "layouts, so it cannot confirm objects aren't too close or colliding.",
            "Object layout (plate)",
            "Open in Snapmaker Orca and check for too-close / collision warnings; use "
            "Arrange or move objects before slicing.",
            (f"{oc} object(s) on the plate; spacing unchecked by Studio" if oc
             else "object count unknown; spacing unchecked by Studio"),
        ))

    # Support enforcers present but support generation disabled — Orca warns
    # ("Support enforcers are used but support is not enabled"). Deterministic:
    # only flag when enable_support is explicitly off AND the model has enforcers.
    try:
        if "enable_support" in cfg and not _truthy(cfg, "enable_support"):
            enforcers = 0
            if tm.has_part("Metadata/model_settings.config"):
                ms = tm.read_part("Metadata/model_settings.config").decode("utf-8", "replace")
                enforcers = ms.count("support_enforcer")
            if enforcers:
                findings.append(_finding(
                    "support.enforcer_without_support", "warning",
                    "Support enforcers used but support is not enabled",
                    "This model marks regions that need support, but support generation "
                    "is turned off — those areas can print unsupported and fail.",
                    f"{SETTINGS} -> enable_support",
                    "Enable support in Snapmaker Orca (or remove the support enforcers) "
                    "before slicing.",
                    f"{enforcers} support-enforcer reference(s); enable_support is off",
                ))
    except Exception:
        pass

    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warning")
    if not findings:
        summary = "No known U1 compatibility issues detected in this project's settings."
        recommendation = ("No known U1 profile/settings issues. This check covers slicer "
                          "settings only — also review mesh quality, colours and plate layout "
                          "(Project Doctor) before slicing.")
    else:
        summary = f"Found {errors} invalid-value issue(s) and {warns} warning(s)."
        recommendation = (
            "Prefer importing the model into a clean Snapmaker U1 project rather than "
            "opening this foreign 3MF as the active project. Studio diagnoses these "
            "issues read-only; it does not change your file."
        )

    return {"findings": findings, "summary": summary, "recommendation": recommendation}
