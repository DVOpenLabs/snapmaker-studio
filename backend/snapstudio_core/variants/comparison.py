"""Bounded, local-only comparison of sliced 3MF and G-code outputs."""
from __future__ import annotations

import json
import lzma
import math
import os
import re
import zipfile
import zlib
from snapstudio_core import localpath
from pathlib import Path

from snapstudio_core import paths, preserve
from snapstudio_core.foundation import artifacts, capabilities, topology

MAX_GCODE_SCAN = 8 * 1024 * 1024
MAX_3MF_ENTRY = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 2048
TOOL_RE = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$", re.IGNORECASE)
GCODE_WEIGHT_RE = re.compile(r"^;\s*filament used \[g\]\s*=\s*(.*)$", re.IGNORECASE)
GCODE_TIME_RE = re.compile(r"^;\s*estimated printing time(?: \([^)]*\))?\s*=\s*(.+)$", re.IGNORECASE)
GCODE_TOWER_RE = re.compile(r"^;\s*(?:total )?(?:wipe tower|purge tower|flush tower)\s*(?:used|volume)?\s*=\s*(.+)$", re.IGNORECASE)


def _parse_number_list(raw: str) -> list[float] | None:
    try:
        values = [float(v.strip()) for v in raw.split(",")]
    except ValueError:
        return None
    return values if values and all(v >= 0 and v < float("inf") for v in values) else None


def _parse_time(raw: str) -> int | None:
    total = 0
    found = False
    for number, unit in re.findall(r"(\d+)\s*(d|h|m|s)", raw.lower()):
        total += int(number) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
        found = True
    return total if found else None


def _safe_path(path: object) -> Path:
    if not isinstance(path, str) or not path.strip() or len(path) > 4096:
        raise ValueError("Each output needs a local file path.")
    if not localpath.is_local_regular_file(str(Path(path).expanduser())):
        raise ValueError("A selected output could not be read as a local file.")
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise ValueError("A selected output could not be read as a file.")
    if candidate.suffix.lower() not in (".3mf", ".gcode", ".g", ".gco"):
        raise ValueError("Choose a sliced 3MF or G-code output.")
    return candidate


def _read_gcode(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(MAX_GCODE_SCAN + 1)
    truncated = size > MAX_GCODE_SCAN or len(raw) > MAX_GCODE_SCAN
    text = raw[:MAX_GCODE_SCAN].decode("utf-8", errors="replace")
    parsed: dict = {"settings": {}, "reported_tool_indices": None, "grams_by_tool": None,
                    "time_seconds": None, "tower": None}
    body_started = False
    active: int | None = None
    used: set[int] = set()
    changes = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not body_started and stripped.startswith(";"):
            match = GCODE_WEIGHT_RE.match(stripped)
            if match:
                grams = _parse_number_list(match.group(1))
                if grams is not None:
                    parsed["grams_by_tool"] = grams
                    parsed["reported_tool_indices"] = [i for i, amount in enumerate(grams) if amount > 0]
            match = GCODE_TIME_RE.match(stripped)
            if match:
                parsed["time_seconds"] = _parse_time(match.group(1))
            match = GCODE_TOWER_RE.match(stripped)
            if match:
                parsed["tower"] = _parse_number_list(match.group(1))
                parsed["tower"] = parsed["tower"][0] if parsed["tower"] and len(parsed["tower"]) == 1 else None
            if "=" in stripped:
                key, value = stripped[1:].split("=", 1)
                key = key.strip()
                if key in {"layer_height", "wall_loops", "sparse_infill_density", "support_type",
                           "brim_type", "nozzle_diameter", "temperature", "bed_temperature",
                           "print_speed", "filament_type", "filament_colour"}:
                    parsed["settings"][key] = value.strip()[:300]
            if "EXECUTABLE_BLOCK_START" in stripped:
                body_started = True
            continue
        if stripped.startswith(";") or not stripped:
            continue
        body_started = True
        match = TOOL_RE.match(stripped)
        if match:
            tool = int(match.group(1))
            used.add(tool)
            if active is not None and active != tool:
                changes += 1
            active = tool
    parsed["scan"] = {"truncated": truncated, "tools_used": sorted(used) if used and not truncated else None,
                      "tool_changes": changes if not truncated else None}
    if parsed["reported_tool_indices"] is None and used:
        parsed["reported_tool_indices"] = sorted(used)
    return parsed


def _finite_amount(value: object) -> bool:
    """A non-negative, finite number that converts to float. Overflowing integers and infinities are not amounts."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and number >= 0


def _read_3mf(path: Path) -> dict:
    try:
        return _read_3mf_archive(path)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError, lzma.LZMAError, OSError):
        raise ValueError("A selected 3MF could not be read as a valid archive.") from None


def _read_3mf_archive(path: Path) -> dict:
    settings: dict = {}
    slice_info: dict = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError("This 3MF contains too many entries to inspect safely.")
        for name, target in (("Metadata/project_settings.config", settings),
                             ("Metadata/slice_info.config", slice_info)):
            try:
                info = archive.getinfo(name)
            except KeyError:
                continue
            if info.file_size > MAX_3MF_ENTRY:
                continue
            raw = archive.read(info)                        # a corrupt or encrypted member is an archive error: the caller maps it to 400
            try:
                value = json.loads(raw.decode("utf-8"))
            except (ValueError, RecursionError):
                continue                                    # readable bytes that are not JSON: the metadata stays unknown
            if isinstance(value, dict):
                target.update(value)
    parsed = {"settings": settings, "reported_tool_indices": None, "grams_by_tool": None,
              "time_seconds": None, "tower": None,
              "scan": {"truncated": False, "tools_used": None, "tool_changes": None}}
    for key in ("filament_used_g", "filament_used_g_by_tool"):
        values = slice_info.get(key)
        if isinstance(values, list) and all(_finite_amount(v) for v in values):
            parsed["grams_by_tool"] = [float(v) for v in values]
            parsed["reported_tool_indices"] = [i for i, amount in enumerate(values) if amount > 0]
            break
    seconds = slice_info.get("estimated_time_s", slice_info.get("time_seconds"))
    if _finite_amount(seconds):
        parsed["time_seconds"] = float(seconds)
    tools = slice_info.get("tools_used")
    if isinstance(tools, list) and all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 31 for v in tools):
        parsed["scan"]["tools_used"] = sorted(set(tools))
    return parsed


def _load(path: Path, snapshots: str) -> dict:
    parsed = _read_3mf(path) if path.suffix.lower() == ".3mf" else _read_gcode(path)
    snap = artifacts.snapshot(str(path), "sliced", snapshot_dir=snapshots, data_dir=paths.data_dir())
    if snap.value is None:
        raise ValueError("Studio could not create a byte identity for a selected output.")
    copy_path = artifacts.snapshot_copy_path(snap.value, snapshots)
    if copy_path:
        parsed = _read_3mf(Path(copy_path)) if path.suffix.lower() == ".3mf" else _read_gcode(Path(copy_path))
    ref = snap.value.to_dict()
    ref["locator"] = None
    current = artifacts.same_bytes(snap.value, str(path)) == artifacts.SAME
    return {"ref": snap.value, "public_ref": ref, "parsed": parsed, "path": str(path),
            "status": "current" if current else "stale"}


def _grams_by_source(entry: dict) -> list[dict]:
    grams = entry["parsed"].get("grams_by_tool")
    if not isinstance(grams, list):
        return []
    bindings = entry.get("physical_bindings")
    result = []
    for index, amount in enumerate(grams):
        if amount <= 0:
            continue
        binding = bindings.get(str(index)) if isinstance(bindings, dict) else None
        source = _verified_physical_source(binding, index)
        result.append({"logical_tool": topology.denormalise_index("orca_filament", index), "grams": amount,
                       "physical_source": source,
                       "basis": "physical source" if source else "logical tool (physical unknown)"})
    return result


def _verified_physical_source(binding: object, index: int) -> str | None:
    """Resolve only a validated direct slot-to-head topology binding."""
    if not isinstance(binding, dict) or not isinstance(binding.get("topology"), dict):
        return None
    slot_id = topology.slot_id(index)
    decoded = topology.Topology.from_dict(binding["topology"])
    if decoded.value is None or any(d.severity == "error" for d in decoded.diagnostics):
        return None
    value = decoded.value
    if not value.complete or any(d.severity == "error" for d in topology.validate(value)):
        return None
    targets = {b.target for b in value.bindings if b.slot_id == slot_id and b.target is not None}
    slot = next((item for item in value.slots if item.id == slot_id), None)
    if slot is not None and slot.binding is not None:
        targets.add(slot.binding)
    if len(targets) != 1:
        return None
    target = next(iter(targets))
    if not target.startswith("head:"):
        return None
    head = next((item for item in value.heads if item.id == target), None)
    return f"head {head.index + 1}" if head is not None else None


def _requirements(raw: object) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 64:
        raise ValueError("Requirements must be a list of at most 64 entries.")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
            raise ValueError("Each requirement needs a capability key.")
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("Requirement parameters must be an object.")
        result.append(capabilities.Requirement(item["key"], params, source="variant comparison"))
    return result


def compare_outputs(data: dict) -> dict:
    """Compare two selected files; computed values remain advisory evidence."""
    outputs = data.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 2 or any(not isinstance(row, dict) for row in outputs):
        raise ValueError("Choose exactly two sliced outputs to compare.")
    snapshots = os.path.join(paths.data_dir(), "variants", "snapshots")
    left, right = (_load(_safe_path(row.get("path")), snapshots) for row in outputs)
    for entry, raw in zip((left, right), outputs):
        entry["physical_bindings"] = raw.get("physical_bindings")
    stale = left["status"] == "stale" or right["status"] == "stale"
    tools_a, tools_b = left["parsed"]["scan"]["tools_used"], right["parsed"]["scan"]["tools_used"]
    tools_known = isinstance(tools_a, list) and isinstance(tools_b, list)
    tools_union = sorted(set(tools_a or []) | set(tools_b or [])) if tools_known else None
    requirements: list[dict] = []
    raw_reqs = data.get("requirements")
    if raw_reqs is not None:
        reqs = _requirements(raw_reqs)
        capability_sets = data.get("capability_sets")
        if capability_sets is None:
            capability_sets = [data.get("capability_set"), data.get("capability_set")]
        decoded = [capabilities.CapabilitySet.from_dict(raw) for raw in capability_sets] \
            if isinstance(capability_sets, list) and len(capability_sets) == 2 else []
        if len(decoded) != 2 or any(item.value is None for item in decoded):
            requirements = [{"key": req.key, "result": "unknown", "reason": "Capability evidence was not usable."}
                            for req in reqs]
        elif decoded[0].value.to_dict() != decoded[1].value.to_dict():
            requirements = [{"key": req.key, "result": "unknown", "reason": "The capability evidence basis changed between outputs."}
                            for req in reqs]
        else:
            requirements = capabilities.evaluation_to_dict(capabilities.evaluate(reqs, decoded[0].value))

    def present(entry: dict) -> dict:
        parsed = entry["parsed"]
        scan = parsed["scan"]
        value = scan["tool_changes"]
        seconds = parsed.get("time_seconds")
        return {
            "artifact": entry["public_ref"], "freshness": entry["status"],
            "format": Path(entry["path"]).suffix.lower().lstrip("."),
            "tools_used": {"value": scan["tools_used"], "status": "computed" if scan["tools_used"] is not None else "unknown"},
            "tool_changes": {"value": value, "status": "computed" if value is not None else "unknown"},
            "grams_by_tool": _grams_by_source(entry),
            "time": {"value": seconds, "unit": "seconds", "status": "reported" if seconds is not None else "unknown"},
            "waste": {"value": parsed.get("tower") if scan["tools_used"] is not None else None,
                      "status": "reported" if parsed.get("tower") is not None and scan["tools_used"] is not None else "unknown"},
        }
    settings_diff = preserve.config_diff(left["parsed"].get("settings", {}), right["parsed"].get("settings", {}))
    return {"outputs": [present(left), present(right)], "stale": stale,
            "tools_union": {"value": tools_union, "status": "computed" if tools_known else "unknown"},
            "settings_diff": settings_diff, "requirements": requirements,
            "advisory": "Comparison is advisory. Computed tool changes come from a bounded G-code scan; unknown means Studio did not verify the value."}
