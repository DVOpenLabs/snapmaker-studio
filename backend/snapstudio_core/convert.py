"""Make a file Snapmaker U1-ready and save it — the desktop 'Convert' action.

Pure engine orchestration (no network/UI): STL files are wrapped into a minimal
U1 3MF; Bambu/Orca 3MF projects are repaired into U1 form. The original is never
overwritten — output is written next to the source as `<stem>_SnapmakerU1.3mf`,
and 3MF repairs also leave a `<stem>.orig.3mf` backup.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import shutil
import copy
import hashlib
import re
from importlib.metadata import PackageNotFoundError, version

from .container import ThreeMF
from .config_io import load_project_settings
from .fingerprint import compute_fingerprint
from .repair import repair as do_repair
from .validate import validate as do_validate
from .u1_identity import is_u1_clean
from .profile import load_profile
from .preserve import config_diff, display_value, machine_compat_keys

SETTINGS = "Metadata/project_settings.config"


@dataclass
class ConversionResult:
    source_type: str          # "stl" | "3mf" | "stl-scaled" | "blocked"
    output_path: str
    output_name: str
    validated_ok: bool
    errors: list
    prepare_mode: str = "preserve"  # preserve | recommended | starter
    settings_summary: dict | None = None
    schema_version: str = "convert/2"
    # Scaled-copy fields (None for a plain convert)
    scale_percent: float | None = None
    original_mm: list | None = None   # [x, y, z] before scaling
    scaled_mm: list | None = None     # [x, y, z] after scaling
    fits_u1: bool | None = None
    blocked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _finish(source_type: str, tm: ThreeMF, out: Path | None, res, *,
            prepare_mode: str, settings_summary: dict | None = None) -> ConversionResult:
    """Fold structural/preservation validation together with the U1-cleanliness
    gate: a project that still carries Bambu/BBL/H2D identity is NOT validated_ok,
    even if its geometry checks pass."""
    errors = list(res.errors)
    clean_ok = True
    if SETTINGS in tm.list_parts():
        cfg = load_project_settings(tm.read_part(SETTINGS))
        clean_ok, clean_issues = is_u1_clean(
            cfg, preserve_creator_settings=prepare_mode == "preserve")
        errors += [issue for issue in clean_issues if not issue.startswith("warning:")]
    return ConversionResult(source_type, str(out) if out else "", out.name if out else "",
                            bool(res.ok and clean_ok), errors, prepare_mode, settings_summary)


def _engine_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text("utf-8"), re.M)
        if match:
            return match.group(1)
    except OSError:
        pass
    try:
        return version("snapmaker-studio")
    except PackageNotFoundError:
        return "unknown"


def _starter_summary(*, geometry_only: bool) -> dict:
    subject = "This file" if geometry_only else "This STL"
    warnings = [f"{subject} does not include creator slicer settings. Studio will use a U1 starter profile unless you choose another Orca profile."]
    could_not_carry = []
    if geometry_only:
        could_not_carry.append({"key": "foreign model/slicer metadata",
                                "reason": "geometry only; foreign model/slicer metadata is not carried"})
    return {
        "summary_schema": "settings-summary/2", "engine_version": _engine_version(),
        "profile_name": "Snapmaker U1 starter profile", "source_config_sha256": None,
        "source_has_creator_settings": False, "kept_count": 0,
        "compat_changed": [], "mapped_to_u1": [], "could_not_carry": could_not_carry,
        "warnings": warnings,
        "recommendations_available": False, "recommended_changes": [],
    }


def _action_reasons(report: dict) -> tuple[dict[str, dict], set[str], set[str]]:
    """Consume RepairOutcome detail while the independent diff remains authoritative.

    Each key has one atomic record. A later record replaces or clears all four
    provenance fields together, so an explanation can never retain old source data."""
    records: dict[str, dict] = {}
    cleared: set[str] = set()
    mapped: set[str] = set()
    groups = [report.get("normalizations", []), report.get("profile_changes", []),
              report.get("filament_array_changes", []),
              report.get("value_normalizations", []), report.get("preserved_value_changes", []),
              report.get("presets_normalized", []), report.get("foreign_cleared", []),
              report.get("orca_compatibility", []),
              # The declaration that makes every change above reach the slicer.
              # Without it in this list a real, reported change looks like an
              # unexplained mutation and the copy fails its own validation.
              [report["preset_deviations_declared"]]
              if report.get("preset_deviations_declared") else []]
    groups.append(report.get("project_materials_changes", []))
    identity = report.get("identity", {})
    groups.append(identity.get("changed", []) if isinstance(identity, dict) else [])
    for group in groups:
        for item in group:
            if not isinstance(item, dict) or "key" not in item:
                continue
            key = item["key"]
            reason = item.get("reason")
            if isinstance(reason, str) and reason:
                # reason always; the other three only when this step supplied them, so a
                # later record never inherits an earlier explanation, source or kind.
                records[key] = {"reason": reason, **{field: item[field] for field in ("explanation", "source", "kind")
                                                      if isinstance(item.get(field), str) and item[field]}}
            elif reason == "":
                # An explicit empty reason clears the complete atomic record.
                records.pop(key, None)
            else:
                # A later report item without a reason is not a clear marker.
                # Preserve the prior complete record.
                pass
            if item.get("category") == "mapped":
                mapped.add(item["key"])
    for item in report.get("foreign_cleared", []):
        if isinstance(item, dict):
            cleared.add(item["key"])
    return records, cleared, mapped


def _strict_value_equal(a, b) -> bool:
    """Compare settings values without Python's cross-type equality coercion."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_strict_value_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        unmatched = list(b)
        for key, value in a.items():
            for candidate in unmatched:
                if _strict_value_equal(key, candidate):
                    break
            else:
                return False
            if not _strict_value_equal(value, b[candidate]):
                return False
            unmatched.remove(candidate)
        return True
    return a == b


def _is_preserved_value_mapping(old, new) -> bool:
    """Whether a resize only retained values or repeated the final one."""
    values = old if isinstance(old, list) else [old]
    if not values or not isinstance(new, list):
        return False
    if len(new) >= len(values):
        expected = values + [values[-1]] * (len(new) - len(values))
    else:
        expected = values[:len(new)]
    return _strict_value_equal(new, expected)


def _settings_summary(before: dict, after: dict, raw_config: bytes, outcome,
                      prepare_mode: str, profile_name: str = "snapmaker_u1",
                      recommended_after: dict | None = None) -> dict:
    profile = load_profile(profile_name)
    diffs = config_diff(before, after)  # independent source of truth (A13)
    records, cleared, mapped_keys = _action_reasons(outcome.report)
    allowlist = machine_compat_keys(profile)
    slice_info = {
        item["key"]: item["reason"]
        for item in outcome.report.get("slice_info", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
        and isinstance(item.get("reason"), str) and item["reason"]
    }
    compat, mapped_to_u1, could_not_carry = [], [], []
    unexplained = []
    for item in diffs:
        key = item["key"]
        if key in cleared:
            # Values in this category were deliberately discarded.  They may
            # be credentials or arbitrary creator G-code, so never echo them.
            could_not_carry.append({"key": key, "reason": records[key]["reason"]})
        elif key in mapped_keys and _is_preserved_value_mapping(item["old"], item["new"]):
            mapped_to_u1.append({
                "key": key, "old": display_value(item["old"], key=key),
                "new": display_value(item["new"], key=key),
                "reason": "carried over to U1 toolheads (values preserved)",
            })
        elif key in records:
            entry = {"key": key, "old": display_value(item["old"], key=key),
                     "new": display_value(item["new"], key=key), **records[key]}
            compat.append(entry)
        elif key in allowlist:
            compat.append({"key": key, "old": display_value(item["old"], key=key),
                           "new": display_value(item["new"], key=key),
                           "reason": "changed only for U1 compatibility"})
        elif key in slice_info:
            could_not_carry.append({"key": key, "reason": slice_info[key]})
        else:
            unexplained.append(key)
            # Recommended mode remains non-strict, but an unreported mutation
            # is never presented as a deliberate compatibility change.
            if prepare_mode != "preserve":
                compat.append({"key": key, "old": display_value(item["old"], key=key),
                               "new": display_value(item["new"], key=key),
                               "reason": "change was not reported by the repair pipeline"})

    for key, reason in slice_info.items():
        if not any(item["key"] == key for item in could_not_carry):
            could_not_carry.append({"key": key, "reason": reason})

    recommended_changes = []
    if prepare_mode == "preserve" and recommended_after is not None:
        # This is the actual recommended pipeline's complete dry-run result,
        # not a hand-maintained subset of profile swaps.
        for item in config_diff(before, recommended_after):
            key = item["key"]
            recommended_changes.append({
                "key": key, "old": display_value(item["old"], key=key),
                "new": display_value(item["new"], key=key),
                "reason": "available with the recommended U1 profile",
            })

    summary = {
        "summary_schema": "settings-summary/2", "engine_version": _engine_version(),
        "profile_name": profile.get("name", profile_name),
        "source_config_sha256": hashlib.sha256(raw_config).hexdigest(),
        "source_has_creator_settings": True,
        "kept_count": sum(1 for key, value in before.items() if key in after and after[key] == value),
        "compat_changed": compat, "mapped_to_u1": mapped_to_u1,
        "could_not_carry": could_not_carry,
        "warnings": list(outcome.report.get("warnings", [])),
        "recommendations_available": prepare_mode == "preserve",
        "recommended_changes": recommended_changes if prepare_mode == "preserve" else [],
    }
    # Preservation invariant: every changed source setting needs a specific
    # repair-pipeline reason, a deliberate foreign-value clear, or the
    # profile-owned machine/compat allowlist.  The independent diff is the
    # authority; summary rendering cannot make a mutation accounted for.
    violations = [key for key in unexplained if key in before]
    if prepare_mode == "preserve" and violations:
        raise ValueError("preservation invariant failed for: " + ", ".join(violations))
    return summary


_U1_OUTPUT_SUFFIX = re.compile(r"(?:_SnapmakerU1(?:_\d+)?)+$", re.IGNORECASE)


def _output_base_stem(stem: str) -> str:
    return _U1_OUTPUT_SUFFIX.sub("", stem)


def _unique_output(src: Path, out_dir: Path | None) -> Path:
    target_dir = out_dir if out_dir else src.parent
    base_stem = _output_base_stem(src.stem)
    out = target_dir / f"{base_stem}_SnapmakerU1.3mf"
    # Never collide with the source, and never silently overwrite a previous
    # conversion: bump a numeric suffix until the path is free.
    n = 2
    while out.resolve() == src.resolve() or out.exists():
        out = target_dir / f"{_output_base_stem(src.stem)}_SnapmakerU1_{n}.3mf"
        n += 1
    return out


def _carry_prusa_settings(source: ThreeMF, wrapped: ThreeMF) -> dict | None:
    """Write the Prusa settings that survive the crossing into the U1 copy.

    Only the ones whose meaning is the same on both sides — `prusa.CARRIED` is the
    list and the reasoning. A project sliced at 0.15 mm with four walls used to
    arrive as the starter profile's 0.2 mm and two walls, which is a different
    print of the same shape with nothing to say so.

    Anything that goes wrong here leaves the copy exactly as it was: a starter
    profile is a working project, and a half-applied one might not be.
    """
    from .config_io import dump_project_settings
    from . import preset_deviation, prusa

    try:
        if not source.has_part(prusa.SETTINGS_PART):
            return None
        config = prusa.settings(source.read_part(prusa.SETTINGS_PART))
        carried = prusa.to_u1_settings(config)
        if not carried["settings"]:
            return None
        settings = load_project_settings(wrapped.read_part(SETTINGS))
        for key, value in carried["settings"].items():
            if isinstance(value, list) and isinstance(settings.get(key), list):
                # Per-slot values fill the slots the project defines and leave the
                # rest of the U1's four as they were.
                merged = list(settings[key])
                for index, item in enumerate(value[:len(merged)]):
                    merged[index] = item
                settings[key] = merged
            else:
                settings[key] = value
        # A carried setting that is not declared is a carried setting the slicer
        # throws away. Measured on Snapmaker Orca 2.3.6: a project stating
        # layer_height=0.28 came back at the preset's 0.2 undeclared, and at 0.28
        # declared. Without this the whole of `prusa.CARRIED` — the layer height,
        # the first layer, the infill density, the wall count and the brim —
        # arrives correct in the file and never reaches the slicer.
        declared = preset_deviation.declare(
            settings, carried["settings"].keys(),
            filaments=len(settings.get("filament_colour") or []) or 4)
        if declared:
            carried["declared"] = declared
        wrapped.replace_part(SETTINGS, dump_project_settings(settings))
        return carried
    except Exception:  # noqa: BLE001 — a starter profile is a working project
        return None


def check_structure(tm) -> None:
    """Refuse to save a prepared copy whose descriptions of itself disagree.

    The validator has caught every corruption the tests throw at it since it was
    written, and until now nothing ran it outside those tests — so a writer bug
    would have reached the user as a project Snapmaker Orca opens wrongly. It runs
    on every prepared copy now, before the file is written.
    """
    from . import multipart
    from .errors import UnsoundOutput

    result = multipart.validate_archive(tm)
    if not result.get("ok", True):
        raise UnsoundOutput(result.get("problems") or ["the structure is unsound"])


def convert_to_u1(path: str, out_dir: str | None = None, prepare_mode: str = "preserve",
                  dry_run: bool = False, confirmed_presets: dict | None = None,
                  filament_catalog=None, confirmed_colours: dict | None = None,
                  material_context: dict | None = None) -> ConversionResult:
    """Convert a single STL or 3MF into a saved U1-ready 3MF. Returns the result.

    `confirmed_presets` maps a filament slot to the exact installed Orca preset the
    person confirmed for it. Slots not listed keep the project's own filament identity
    in every mode; `filament_catalog` only lets the report suggest a preset for them.
    `confirmed_colours` maps a slot to the colour of the spool the person selected.
    `material_context` maps a slot to the selected spool and how its preset was matched; it
    only feeds the plain-language record of what happened and changes nothing in the copy.

    With `confirmed_presets`, a project whose existing vendor/type declarations Orca would
    copy between slots sharing a preset is not prepared: the result is `blocked`."""
    src = Path(path)
    if prepare_mode == "u1":
        prepare_mode = "recommended"
    if prepare_mode not in ("preserve", "recommended"):
        raise ValueError("prepare_mode must be 'preserve' or 'recommended'")
    out_parent = Path(out_dir) if out_dir else None
    if out_parent and not dry_run:
        out_parent.mkdir(parents=True, exist_ok=True)
    out = _unique_output(src, out_parent) if not dry_run else None

    if src.suffix.lower() == ".stl":
        from .stl_wrap import wrap_stl

        tm = wrap_stl(str(src))
        check_structure(tm)
        if out:
            tm.save(out)
        res = do_validate(tm, against=None)
        return _finish("stl", tm, out, res, prepare_mode="starter",
                       settings_summary=_starter_summary(geometry_only=False))

    tm = ThreeMF.open(src)
    if not tm.has_part(SETTINGS):
        # Geometry-only / foreign-slicer 3MF (e.g. a PrusaSlicer export with no
        # project_settings.config): there is no project to repair, so wrap the
        # existing geometry into a clean U1 project, like the STL path.
        from .stl_wrap import wrap_geometry_3mf

        wrapped = wrap_geometry_3mf(str(src))
        # A PrusaSlicer project has no U1 settings to repair, but it does state
        # how it was meant to print. Carrying the settings that mean the same
        # thing on both sides is the difference between a copy of the shape and a
        # copy of the print.
        carried = _carry_prusa_settings(tm, wrapped)
        check_structure(wrapped)
        if out:
            wrapped.save(out)
        res = do_validate(wrapped, against=None)
        summary = _starter_summary(geometry_only=True)
        if carried:
            summary["mapped_to_u1"] = carried["evidence"]
            summary["kept_count"] = len(carried["evidence"])
        return _finish("3mf-geometry", wrapped, out, res, prepare_mode="starter",
                       settings_summary=summary)

    # 3MF: repair into U1, validate against the source fingerprint (preservation).
    src_fp = compute_fingerprint(tm)
    raw_config = tm.read_part(SETTINGS)
    before = load_project_settings(raw_config)
    material_guard = None
    recommended_tm = copy.deepcopy(tm) if prepare_mode == "preserve" else None
    internal_mode = "preserve" if prepare_mode == "preserve" else "u1"
    outcome = do_repair(tm, mode=internal_mode, remap=None, dry_run=dry_run, opt_profile=None,
                        confirmed_presets=confirmed_presets, filament_catalog=filament_catalog,
                        confirmed_colours=confirmed_colours)
    after = load_project_settings(tm.read_part(SETTINGS))
    if confirmed_presets:
        # Judged on what this mode will actually write, not on what the source declared:
        # Orca propagates the written declarations. Nothing is saved when this blocks.
        from . import project_materials as pm
        material_guard = pm.effective_guard(before, after, confirmed_presets, filament_catalog,
                                            pm.project_nozzle(before), prepare_mode)
        if material_guard["blocking"]:
            return ConversionResult(
                "blocked", "", "", False, [pm.guard_message(material_guard)], prepare_mode,
                {"project_materials": {"guard": material_guard}}, blocked=True)
    recommended_after = None
    if recommended_tm is not None:
        # Use the normal repair path on a wholly in-memory project so preview
        # results cannot diverge from a real recommended conversion or write.
        do_repair(recommended_tm, mode="u1", remap=None, dry_run=True, opt_profile=None,
                  confirmed_presets=confirmed_presets, filament_catalog=filament_catalog,
                  confirmed_colours=confirmed_colours)
        recommended_after = load_project_settings(recommended_tm.read_part(SETTINGS))
    summary = _settings_summary(before, after, raw_config, outcome, prepare_mode,
                                recommended_after=recommended_after)
    if confirmed_presets or confirmed_colours or filament_catalog is not None:
        # Only when Project Materials is in use, so a plain Prepare reports exactly what it did.
        summary["project_materials"] = {
            **(outcome.report.get("filament_identity") or {}), "guard": material_guard}
        if confirmed_presets or confirmed_colours:
            from . import materials_fidelity
            from . import project_materials as pm
            summary["project_materials"]["fidelity"] = materials_fidelity.build(
                source=before, prepared=after, report=outcome.report, mode=prepare_mode,
                confirmed_presets=confirmed_presets, confirmed_colours=confirmed_colours,
                context=material_context, catalog=filament_catalog, nozzle=pm.project_nozzle(before),
                guard=material_guard)
    check_structure(tm)
    backup = src.with_suffix(".orig.3mf")
    if not dry_run and not backup.exists():
        shutil.copy2(src, backup)
    if out:
        tm.save(out)
    res = do_validate(tm, against=src_fp)
    return _finish("3mf", tm, out, res, prepare_mode=prepare_mode, settings_summary=summary)


def _scaled_output(src: Path, out_dir: Path | None, pct: float) -> Path:
    target_dir = out_dir if out_dir else src.parent
    tag = f"{int(round(pct))}"
    out = target_dir / f"{src.stem}_scaled_{tag}_U1.3mf"
    n = 2
    while out.resolve() == src.resolve() or out.exists():
        out = target_dir / f"{src.stem}_scaled_{tag}_U1_{n}.3mf"
        n += 1
    return out


def prepare_scaled_copy(path: str, scale_percent: float,
                        out_dir: str | None = None) -> ConversionResult:
    """Create a NEW uniformly-scaled U1 3MF copy. The original is never modified.

    beta.17: STL input is fully supported (vertex scale, geometry verified by bbox).
    3MF input is intentionally blocked with a clear message — uniform multi-part /
    painted-project scaling is not yet verified against Snapmaker Orca, and we do not
    ship unverified scaling. Preview (read-only) still works for any input.
    """
    src = Path(path)
    pct = float(scale_percent)
    if not (10.0 <= pct <= 1000.0):
        raise ValueError("scale_percent must be between 10 and 1000")
    s = pct / 100.0

    if src.suffix.lower() != ".stl":
        return ConversionResult(
            "blocked", "", "", False,
            ["Scaled copy currently supports STL files. For a 3MF project, preview the "
             "scale here, then resize in Snapmaker Orca — verified 3MF scaled export is "
             "coming. Your file was not changed."],
            scale_percent=pct, blocked=True)

    from .stl_wrap import wrap_stl
    from .geometry import load_mesh
    from .scale_doctor import _fits, _bed

    mesh = load_mesh(str(src))
    if mesh is None or not mesh.verts:
        raise ValueError("could not read STL geometry")
    xs = [v[0] for v in mesh.verts]; ys = [v[1] for v in mesh.verts]; zs = [v[2] for v in mesh.verts]
    orig = [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)]
    scaled = [d * s for d in orig]

    out_parent = Path(out_dir) if out_dir else None
    if out_parent:
        out_parent.mkdir(parents=True, exist_ok=True)
    out = _scaled_output(src, out_parent, pct)

    tm = wrap_stl(str(src), scale=s)
    tm.save(out)
    res = do_validate(ThreeMF.open(out), against=None)
    result = _finish("stl-scaled", ThreeMF.open(out), out, res, prepare_mode="starter",
                     settings_summary=_starter_summary(geometry_only=False))
    result.scale_percent = pct
    result.original_mm = [round(d, 2) for d in orig]
    result.scaled_mm = [round(d, 2) for d in scaled]
    # `fits_u1` is exactly what its name says: this is the prepare path, and the
    # copy being written is a U1 copy.
    result.fits_u1 = bool(_fits({"x": scaled[0], "y": scaled[1], "z": scaled[2]}, _bed()))
    return result
