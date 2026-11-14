from __future__ import annotations

from pathlib import Path

from snapstudio_core.foundation import capabilities
from snapstudio_core.foundation import topology
from snapstudio_core.variants.comparison import MAX_GCODE_SCAN, compare_outputs

FIXTURES = Path(__file__).parents[1] / "fixtures" / "variants"


def compare(a: Path, b: Path, **extra):
    return compare_outputs({"outputs": [{"path": str(a)}, {"path": str(b)}], **extra})


def test_two_outputs_have_byte_backed_artifact_refs():
    report = compare(FIXTURES / "left.gcode", FIXTURES / "right.gcode")
    assert all(row["artifact"]["artifact_id"].startswith("sha256:") for row in report["outputs"])
    assert all(row["artifact"]["locator"] is None for row in report["outputs"])


def test_grams_are_logical_until_a_binding_is_verified():
    rows = compare(FIXTURES / "left.gcode", FIXTURES / "right.gcode")["outputs"][0]["grams_by_tool"]
    assert rows[0]["logical_tool"] == 1
    assert rows[0]["basis"] == "logical tool (physical unknown)"
    setup = {
        "schema_version": "topology/1", "snapshot_id": "synthetic", "received_at": "2026-10-31T00:00:00Z",
        "heads": [{"id": "head:0", "index": 0, "nozzle_mm": None, "evidence": []}],
        "units": [], "slots": [{"id": "slot:0", "index": 0, "binding": "head:0", "nozzle_mm": None}],
        "bindings": [], "complete": True, "evidence": [], "diagnostics": [],
    }
    assert topology.Topology.from_dict(setup).value is not None
    bound = compare_outputs({"outputs": [
        {"path": str(FIXTURES / "left.gcode"), "physical_bindings": {"0": {"topology": setup}}},
        {"path": str(FIXTURES / "right.gcode")},
    ]})["outputs"][0]["grams_by_tool"]
    assert bound[0]["physical_source"] == "head 1"
    assert bound[0]["basis"] == "physical source"


def test_gcode_zero_based_tools_and_project_one_based_slots_normalise():
    report = compare(FIXTURES / "left.gcode", FIXTURES / "right.gcode")
    assert report["outputs"][0]["tools_used"]["value"] == [0, 1]
    assert [row["logical_tool"] for row in report["outputs"][0]["grams_by_tool"]] == [1, 2]


def test_tool_change_count_is_computed_from_bounded_gcode_body():
    output = compare(FIXTURES / "left.gcode", FIXTURES / "right.gcode")["outputs"][0]
    assert output["tool_changes"] == {"value": 2, "status": "computed"}


def test_unknown_tool_usage_keeps_waste_unknown():
    output = compare(FIXTURES / "unknown.gcode", FIXTURES / "right.gcode")["outputs"][0]
    assert output["tools_used"]["status"] == "unknown"
    assert output["waste"]["status"] == "unknown"


def test_missing_time_stays_unknown():
    output = compare(FIXTURES / "unknown.gcode", FIXTURES / "right.gcode")["outputs"][0]
    assert output["time"] == {"value": None, "unit": "seconds", "status": "unknown"}


def test_changed_bytes_are_marked_stale(tmp_path):
    changed = tmp_path / "changed.gcode"
    changed.write_text((FIXTURES / "left.gcode").read_text() + "; changed\n", encoding="utf-8")
    # Compare against a snapshot candidate then mutate its source during artifact admission.
    from snapstudio_core.foundation import artifacts
    original = artifacts.snapshot

    def snapshot_then_mutate(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if Path(path) == changed:
            Path(path).write_text(Path(path).read_text(encoding="utf-8") + "; mutation\n", encoding="utf-8")
        return result

    artifacts.snapshot = snapshot_then_mutate
    try:
        report = compare_outputs({"outputs": [{"path": str(changed)}, {"path": str(FIXTURES / "right.gcode")}]})
    finally:
        artifacts.snapshot = original
    assert report["stale"] is True
    assert report["outputs"][0]["freshness"] == "stale"


def test_settings_diff_uses_preserve_config_diff():
    report = compare(FIXTURES / "left.gcode", FIXTURES / "right.gcode")
    assert {"key": "layer_height", "old": "0.20", "new": "0.24", "removed": False} in report["settings_diff"]


def test_requirements_use_foundation_capability_evaluator_and_basis_changes_unknown():
    evidence = capabilities.CapabilitySet()
    evidence.add(capabilities.Capability("supports_material_x", "supported"))
    other_basis = capabilities.CapabilitySet()
    other_basis.add(capabilities.Capability("supports_material_x", "unsupported"))
    report = compare_outputs({"outputs": [{"path": str(FIXTURES / "left.gcode")},
                                           {"path": str(FIXTURES / "right.gcode")}],
                              "requirements": [{"key": "supports_material_x"}],
                              "capability_sets": [evidence.to_dict(), other_basis.to_dict()]})
    assert report["requirements"][0]["result"] == "unknown"
    same_basis = compare_outputs({"outputs": [{"path": str(FIXTURES / "left.gcode")},
                                               {"path": str(FIXTURES / "left.gcode")}],
                                  "requirements": [{"key": "supports_material_x"}],
                                  "capability_set": evidence.to_dict()})
    assert same_basis["requirements"][0]["result"] == "satisfied"


def test_gcode_scan_limit_is_bounded(tmp_path):
    text = ";\n" + "G1 X0\n" * ((MAX_GCODE_SCAN // 6) + 100)
    path = tmp_path / "oversize.gcode"
    path.write_text(text, encoding="utf-8")
    report = compare(path, FIXTURES / "right.gcode")
    assert report["outputs"][0]["tool_changes"] == {"value": None, "status": "unknown"}
