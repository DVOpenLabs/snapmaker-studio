"""Core level checks for the prepare comparison used by the creative journey (no HTTP layer).

Evidence label: fixture-tested; archives are SYNTHETIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "creative"))
from zip_factory import make_3mf  # noqa: E402

from snapstudio_api import routes_creative  # noqa: E402
from snapstudio_core.creative.container import read_3mf  # noqa: E402


def test_compare_members_sorts_members_into_four_groups():
    original = read_3mf(make_3mf(settings={"a": 1}, members={"Metadata/keep.bin": b"1", "Metadata/change.bin": b"1",
                                                             "Metadata/drop.bin": b"1"}))
    exported = read_3mf(make_3mf(settings={"a": 1}, members={"Metadata/keep.bin": b"1", "Metadata/change.bin": b"2",
                                                             "Metadata/new.bin": b"3"}))
    diff = routes_creative.compare_members(original, exported)
    assert diff == {"preserved": ["3D/3dmodel.model", "Metadata/keep.bin", "Metadata/project_settings.config"],
                    "modified": ["Metadata/change.bin"], "dropped": ["Metadata/drop.bin"],
                    "added": ["Metadata/new.bin"]}


def test_settings_delta_names_removed_changed_and_counts_added():
    delta = routes_creative._settings_delta({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 9, "d": 4, "e": 5})
    assert delta == {"removed_keys": ["c"], "changed_keys": ["b"], "added_key_count": 2}
    assert routes_creative._settings_delta(None, None) == {"removed_keys": [], "changed_keys": [], "added_key_count": 0}


def test_loss_notes_state_drops_and_paint_loss_in_words():
    verify = {"counts": {"dropped": 1, "modified": 0, "added": 0, "preserved": 2},
              "comparison": {"dropped": ["Metadata/drop.bin"], "modified": [], "added": [], "preserved": []},
              "per_face_paint": {"original_triangles": 4, "exported_triangles": 0, "kept": False},
              "settings": {"removed_keys": ["x"], "changed_keys": [], "added_key_count": 0}}
    notes = routes_creative._loss_notes(verify)
    assert any("Metadata/drop.bin" in n for n in notes)
    assert any("4 painted triangle(s)" in n and "the copy has 0" in n for n in notes)
    assert any("1 project setting(s)" in n for n in notes)


def test_a_missing_or_broken_export_is_reported_not_raised(tmp_path):
    original = read_3mf(make_3mf(settings={"a": 1}))
    assert routes_creative._verify(original, str(tmp_path / "absent.3mf"))["opens_as_zip"] is False
    broken = tmp_path / "broken.3mf"
    broken.write_bytes(b"not a zip")
    result = routes_creative._verify(original, str(broken))
    assert result["opens_as_zip"] is False and "not a readable 3MF" in result["problem"]
