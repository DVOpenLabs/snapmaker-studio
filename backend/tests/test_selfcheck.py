"""The judge self-check.

A self-check that cannot fail is worthless, so the important test here is the one
that breaks a feature and asserts the check notices. The rest guard the promises
the command makes: it touches nothing outside a temp directory, it leaves the
input file alone, and it reports rather than crashes.
"""
from __future__ import annotations

import json
import zipfile

from snapstudio_core import selfcheck as sc


def test_the_whole_pipeline_passes():
    report = sc.run()
    assert report["ok"] is True, [c for c in report["checks"] if c["status"] != sc.PASS]
    assert report["passed"] == report["total"]
    assert report["total"] >= 12


def test_every_check_is_named_and_most_carry_evidence():
    report = sc.run()
    for check in report["checks"]:
        assert check["name"]
        assert check["status"] in (sc.PASS, sc.FAIL, sc.SKIP)
    detailed = [c for c in report["checks"] if c["detail"]]
    assert len(detailed) >= len(report["checks"]) - 2


def test_a_broken_feature_is_reported_as_a_failure(monkeypatch):
    """The check has to be able to fail. Break placement detection and confirm the
    report says so instead of passing anyway."""
    from snapstudio_core import plate_placement

    monkeypatch.setattr(plate_placement, "assess",
                        lambda *a, **k: {"available": False, "reason": "broken", "off_plate": []})
    report = sc.run()
    assert report["ok"] is False
    failed = [c for c in report["checks"] if c["status"] == sc.FAIL]
    assert any("Placement" in c["name"] for c in failed)


def test_a_raising_feature_is_reported_not_crashed(monkeypatch):
    from snapstudio_core import color_plan

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(color_plan, "analyse", boom)
    report = sc.run()          # must not raise
    assert report["ok"] is False
    colour = next(c for c in report["checks"] if "Colour" in c["name"])
    assert colour["status"] == sc.FAIL
    assert "kaboom" in colour["detail"]


def test_the_fixture_is_a_real_project_with_a_real_problem(tmp_path):
    path = sc.build_fixture(tmp_path)
    with zipfile.ZipFile(path) as z:
        cfg = json.loads(z.read("Metadata/project_settings.config"))
        names = z.namelist()
    assert cfg["printer_model"] != "Snapmaker U1"           # authored elsewhere
    assert cfg["exclude_object"] == "0"                     # needs the import fix
    assert cfg["brim_type"] == "auto_brim"
    assert len(cfg["filament_colour"]) > 4                  # more colours than toolheads
    assert "Metadata/plate_1.gcode" in names                # stale toolpaths to strip
    assert "3D/3dmodel.model" in names


def test_running_against_a_supplied_sample_is_reported(tmp_path):
    sample = sc.build_fixture(tmp_path)
    report = sc.run(str(sample))
    assert report["sample"] == sample.name


def test_a_supplied_sample_is_never_modified(tmp_path):
    sample = sc.build_fixture(tmp_path)
    before = sample.read_bytes()
    sc.run(str(sample))
    assert sample.read_bytes() == before


def test_nothing_is_written_beside_a_supplied_sample(tmp_path):
    sample = sc.build_fixture(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    sc.run(str(sample))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_the_table_is_plain_enough_to_paste_into_an_issue():
    text = sc.format_table(sc.run())
    assert "Snapmaker Studio self-check" in text
    assert "PASS" in text
    assert "checks passed" in text


def test_the_fixtures_carry_real_package_parts_so_orca_will_open_them(tmp_path):
    """Snapmaker Orca 2.4.1 refuses a 3MF whose [Content_Types].xml and _rels/.rels are
    empty stubs ("Loading of model file failed"): nothing points the reader at the
    model. Isolated testing on 2026-10-25 (docs/internal/orca-sample-isolation-2026-10-25.json)
    showed real parts get past that error. This parses the parts rather than matching text."""
    import zipfile
    from pathlib import Path
    from xml.etree import ElementTree as ET

    from snapstudio_core import selfcheck as sc

    root = Path(__file__).resolve().parents[2]
    paths = [sc.build_fixture(tmp_path), sc._painted_fixture(tmp_path),
             root / "examples" / "demo_u1_showcase.3mf"]
    ct_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    for path in paths:
        with zipfile.ZipFile(path) as z:
            types = ET.fromstring(z.read("[Content_Types].xml"))
            rels = ET.fromstring(z.read("_rels/.rels"))
        defaults = {d.get("Extension"): d.get("ContentType") for d in types.iter(ct_ns + "Default")}
        assert defaults.get("rels") == "application/vnd.openxmlformats-package.relationships+xml", path.name
        assert defaults.get("model") == "application/vnd.ms-package.3dmanufacturing-3dmodel+xml", path.name
        found = [(r.get("Type"), r.get("Target")) for r in rels.iter(rel_ns + "Relationship")]
        assert ("http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
                "/3D/3dmodel.model") in found, path.name
