"""Issue #67: a Bambu Studio / P1S project that carries per-object support or wall
settings used to be refused whole ("Studio built a prepared copy it cannot vouch
for") because those keys were not on the proven list.

Snapmaker Orca v2.4.0 reads exactly these keys at object level, in the same words
Bambu Studio writes them (see `overrides.NATIVE_KEPT`). The fixture here is built at
test time from a small real Bambu project by adding the same per-object metadata a
real model carries — no third-party model file is committed.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import zipfile

import pytest

from snapstudio_core import convert as conv
from snapstudio_core import overrides
from snapstudio_core.errors import UnsoundOutput

HERE = os.path.dirname(__file__)
BASE = os.path.join(HERE, "fixtures", "painted", "bambustudio-2.08.02.61-authored.3mf")  # committed, Bambu Studio-authored
CONFIG = "Metadata/model_settings.config"

# The shape in the reporter's screenshot, and the shape in the current model file.
SUPPORT_SHAPE = {"support_type": "tree(auto)", "support_style": "default"}
WALL_SHAPE = {"wall_generator": "arachne", "wall_loops": "3"}
# Value shapes seen in real Bambu Studio projects that used to be refused whole.
INFILL_SHAPE = {"sparse_infill_pattern": "gyroid", "skeleton_infill_density": "30%",
                "skin_infill_density": "30%"}
SHELL_SHAPE = {"top_shell_layers": "0", "bottom_shell_layers": "0",
               "skeleton_infill_density": "12%", "skin_infill_density": "12%"}
BRIM_SHAPES = [{"brim_type": v} for v in
               ("no_brim", "outer_only", "inner_only", "outer_and_inner", "brim_ears")]


def _inject(tmp_path, extra: dict, name="p1s-object-settings.3mf") -> str:
    """Copy the base project, adding `extra` as per-object metadata on every object."""
    out = tmp_path / name
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == CONFIG:
                text = data.decode("utf-8")
                add = "".join(f'    <metadata key="{k}" value="{v}"/>\n' for k, v in extra.items())
                text, n = re.subn(r'(<object id="\d+">\s*\n(?:\s*<metadata key="(?:name|extruder)"[^>]*/>\s*\n)+)',
                                  lambda m: m.group(1) + add, text)
                assert n, "fixture shape changed: no object metadata block found"
                data = text.encode("utf-8")
            dst.writestr(item, data)
    return str(out)


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _object_pairs(path: str) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        text = z.read(CONFIG).decode("utf-8")
    rows = []
    for m in re.finditer(r'<object id="\d+">(.*?)</object>', text, re.S):
        head = m.group(1).split("<part")[0]
        rows.append(dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', head)))
    return rows


def _object_keys(path: str) -> list[set]:
    with zipfile.ZipFile(path) as z:
        text = z.read(CONFIG).decode("utf-8")
    rows = []
    for m in re.finditer(r'<object id="\d+">(.*?)</object>', text, re.S):
        head = m.group(1).split("<part")[0]
        rows.append(set(re.findall(r'<metadata key="([^"]+)"', head)))
    return rows


@pytest.mark.parametrize("shape", [SUPPORT_SHAPE, WALL_SHAPE, {**SUPPORT_SHAPE, **WALL_SHAPE},
                                   INFILL_SHAPE, SHELL_SHAPE, *BRIM_SHAPES,
                                   {**INFILL_SHAPE, **SUPPORT_SHAPE, "wall_loops": "3",
                                    "enable_support": "1", "sparse_infill_density": "30%"}])
def test_native_object_settings_prepare_and_are_kept(tmp_path, shape):
    src = _inject(tmp_path, shape)
    before = _sha(src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = conv.convert_to_u1(src, str(out_dir))
    assert result.validated_ok, result.errors
    assert _sha(src) == before                      # the original is never modified
    out = result.output_path
    assert os.path.exists(out) and out != src
    # kept, not dropped: Orca reads them, so they cross unchanged
    # kept unchanged: the exact key -> value mapping, not just the key's presence
    stated = _object_pairs(out)
    assert stated and all({k: v for k, v in row.items() if k in shape} == shape for row in stated)
    # the saved copy reopens and validates on its own
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None


def test_an_unrelated_unproven_setting_is_still_refused(tmp_path):
    src = _inject(tmp_path, {**SUPPORT_SHAPE, "ironing_type": "top surface"})
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with pytest.raises(UnsoundOutput) as ei:
        conv.convert_to_u1(src, str(out_dir))
    assert "ironing_type is not a setting Studio has proved" in ei.value.details
    assert "ironing_type" in str(ei.value) and "support_type" not in str(ei.value)
    assert "support_type is not a setting" not in ei.value.details   # the proven ones are not blamed
    assert not list(out_dir.iterdir())                            # nothing was saved


@pytest.mark.parametrize("key,value", [
    ("support_type", "tree(weird)"),
    ("support_type", ""),
    ("support_style", "Tree_Hybrid"),
    ("wall_generator", "ARACHNE"),
    ("wall_loops", "-1"),
    ("wall_loops", "3.5"),
    ("wall_loops", "1001"),
    ("wall_loops", "٣"),       # Arabic-Indic digit: Orca deletes the object on it
    ("wall_loops", "03"),
    ("sparse_infill_pattern", "zig-zag"),      # legacy spelling, not an Orca 2.4.0 value
    ("sparse_infill_pattern", "Gyroid"),
    ("sparse_infill_pattern", ""),
    ("brim_type", "Outer_Only"),
    ("brim_type", ""),
    ("brim_type", "auto_brim"),
    ("brim_type", "painted"),
    ("top_shell_layers", "-1"), ("top_shell_layers", "1001"), ("top_shell_layers", "٣"),
    ("top_shell_layers", "03"), ("top_shell_layers", "3.5"),
    ("bottom_shell_layers", "-1"), ("bottom_shell_layers", "1001"),
    ("bottom_shell_layers", "٣"), ("bottom_shell_layers", "03"),
    *[(k, v) for k in ("skeleton_infill_density", "skin_infill_density")
      for v in ("101%", "-1%", "12.5.5%", "٣٠%", "30", "1e1%", "+30%", "030%", "", "%", " 30%")],
])
def test_a_value_orca_cannot_read_is_refused(key, value):
    faults = overrides.validate_emitted({key: value})
    assert faults and "Snapmaker Orca reads" in faults[0]


@pytest.mark.parametrize("key,value", [
    ("support_type", "normal(auto)"), ("support_type", "tree(manual)"),
    ("support_style", "tree_hybrid"), ("support_style", "organic"),
    ("wall_generator", "classic"), ("wall_loops", "0"), ("wall_loops", "1000"),
    ("top_shell_layers", "0"), ("top_shell_layers", "1000"), ("bottom_shell_layers", "7"),
    ("skeleton_infill_density", "0%"), ("skeleton_infill_density", "100%"),
    ("skin_infill_density", "12.5%"),
    *[("sparse_infill_pattern", v) for v in overrides._INFILL_PATTERNS],
    *[("brim_type", v) for v in
      ("no_brim", "outer_only", "inner_only", "outer_and_inner", "brim_ears")],
])
def test_values_orca_reads_pass(key, value):
    assert overrides.validate_emitted({key: value}) == []


def test_the_infill_pattern_list_is_the_26_orca_2_4_0_values():
    assert len(overrides._INFILL_PATTERNS) == 26 == len(set(overrides._INFILL_PATTERNS))
    assert "zig-zag" not in overrides._INFILL_PATTERNS


def test_the_allowlist_is_exactly_the_measured_keys():
    assert set(overrides.NATIVE_KEPT) == {
        "wall_generator", "wall_loops", "support_type", "support_style",
        "sparse_infill_pattern", "skeleton_infill_density", "skin_infill_density",
        "top_shell_layers", "bottom_shell_layers", "brim_type",
        "sparse_infill_density", "enable_support"}
    # not a back door into the Prusa-translation table
    assert not set(overrides.NATIVE_KEPT) & set(overrides.CARRIED)


def test_fidelity_reports_a_kept_native_setting_as_preserved_not_unsupported():
    from snapstudio_core import assignments

    src = {"overrides": {"support_type": "tree(auto)", "wall_loops": "3"}}
    kept = {"overrides": {"support_type": "tree(auto)", "wall_loops": "3"}}
    rows = assignments._override_rows(src, kept, "Slide", 0)
    assert {r["status"] for r in rows} == {assignments.PRESERVED_EXACT}
    assert len(rows) == 2                                    # one row each, no "invented" echo

    changed = assignments._override_rows(src, {"overrides": {"support_type": "normal(auto)",
                                                             "wall_loops": "3"}}, "Slide", 0)
    assert any(r["status"] == assignments.CHANGED and "support_type" in r["detail"] for r in changed)
    dropped = assignments._override_rows(src, {"overrides": {}}, "Slide", 0)
    assert sum(r["status"] == assignments.CHANGED for r in dropped) == 2


@pytest.mark.parametrize("value", [3, None, 3.0, b"3"])
def test_a_non_string_value_is_refused_not_a_crash(value):
    faults = overrides.validate_emitted({"wall_loops": value, "support_type": value})
    assert len(faults) == 2


def test_fidelity_reports_the_six_added_settings_as_preserved():
    from snapstudio_core import assignments

    said = {"sparse_infill_pattern": "gyroid", "skeleton_infill_density": "30%",
            "skin_infill_density": "30%", "top_shell_layers": "0",
            "bottom_shell_layers": "0", "brim_type": "inner_only"}
    rows = assignments._override_rows({"overrides": dict(said)}, {"overrides": dict(said)},
                                      "Slide", 0)
    assert len(rows) == 6
    assert {r["status"] for r in rows} == {assignments.PRESERVED_EXACT}


def test_fidelity_reports_orca_worded_infill_density_and_support_as_preserved():
    from snapstudio_core import assignments

    said = {"sparse_infill_density": "30%", "enable_support": "1"}
    rows = assignments._override_rows({"overrides": dict(said)}, {"overrides": dict(said)},
                                      "Slide", 0)
    assert len(rows) == 2 and {r["status"] for r in rows} == {assignments.PRESERVED_EXACT}
    # a changed or dropped value is still not "preserved"
    changed = assignments._override_rows({"overrides": dict(said)},
                                         {"overrides": {**said, "sparse_infill_density": "40%"}},
                                         "Slide", 0)
    assert any(r["status"] == assignments.CHANGED for r in changed)
    dropped = assignments._override_rows({"overrides": dict(said)}, {"overrides": {}}, "Slide", 0)
    assert all(r["status"] == assignments.CHANGED for r in dropped)


@pytest.mark.parametrize("key,value", [("sparse_infill_density", "101%"), ("sparse_infill_density", "30"),
                                        ("sparse_infill_density", "٣٠%"), ("enable_support", "2"),
                                        ("enable_support", "true")])
def test_orca_worded_density_and_support_keep_their_strict_gates(key, value):
    assert overrides.validate_emitted({key: value})


def test_a_prusa_per_object_brim_type_is_still_not_carried_and_blocks_the_claim():
    from snapstudio_core import assignments

    src = {"dialect": assignments.DIALECT_PRUSA, "overrides": {"brim_type": "outer_only"}}
    rows = assignments._override_rows(src, {"overrides": {}}, "Slide", 0)
    assert [r["status"] for r in rows] == [assignments.UNSUPPORTED]
    # the same key from a Bambu/Orca source is a dropped native setting, as before
    bambu = assignments._override_rows({"overrides": {"brim_type": "outer_only"}},
                                       {"overrides": {}}, "Slide", 0)
    assert [r["status"] for r in bambu] == [assignments.CHANGED]
