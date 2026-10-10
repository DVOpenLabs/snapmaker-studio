"""Object-spacing / collision honesty: Studio reports 'unknown' for multi-object
3MF layouts (it does not verify spacing yet) and that must block any
'ready / no major blockers' wording."""
from snapstudio_core.collision import assess_spacing, SPACING_MESSAGE
from snapstudio_core import intelligence_report as ir


def test_multi_object_3mf_is_unknown():
    s = assess_spacing(5, is_stl=False)
    assert s["status"] == "unknown"
    assert s["messages"] and "Orca" in s["messages"][0]


def test_single_object_3mf_passes():
    # one object can't collide with others
    assert assess_spacing(1, is_stl=False)["status"] == "pass"


def test_unknown_object_count_is_not_assumed_single():
    # None or 0 means Studio could not count the objects: spacing stays unknown.
    assert assess_spacing(0, is_stl=False)["status"] == "unknown"
    assert assess_spacing(None, is_stl=False)["status"] == "unknown"


def test_stl_passes():
    # STL is wrapped into a fresh single-object project
    assert assess_spacing(99, is_stl=True)["status"] == "pass"


def test_unknown_spacing_blocks_no_blockers_verdict():
    # A report that would otherwise have no risks must NOT say "no major blockers"
    # when object spacing is unknown.
    cost = {"available": True, "true_cost": 1.0, "currency": "$"}
    clean = ir.build(cost=cost, spacing={"status": "unknown"})
    assert "no major blockers" not in clean["verdict"]
    assert any("spacing" in r["text"].lower() or "collision" in r["text"].lower()
               for r in clean["risks"])


def test_pass_spacing_does_not_inject_risk():
    cost = {"available": True, "true_cost": 1.0, "currency": "$"}
    rep = ir.build(cost=cost, spacing={"status": "pass"})
    assert not any("spacing" in r["text"].lower() for r in rep["risks"])


def _mini_3mf(tmp_path, enable_support, with_enforcer):
    import json, zipfile
    p = tmp_path / "mini.3mf"
    settings = {"printer_model": "Snapmaker U1", "enable_support": enable_support}
    ms = ('<?xml version="1.0"?><config><object id="1">'
          + ('<part id="2" subtype="support_enforcer"/>' if with_enforcer else "")
          + "</object></config>")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr("Metadata/model_settings.config", ms)
    return str(p)


def test_support_enforcer_without_support_is_flagged(tmp_path):
    from snapstudio_core import compatibility
    c = compatibility.check(_mini_3mf(tmp_path, enable_support="0", with_enforcer=True))
    assert any(f["id"] == "support.enforcer_without_support" for f in c["findings"])


def test_no_enforcer_warning_when_support_enabled(tmp_path):
    from snapstudio_core import compatibility
    c = compatibility.check(_mini_3mf(tmp_path, enable_support="1", with_enforcer=True))
    assert not any(f["id"] == "support.enforcer_without_support" for f in c["findings"])


def test_no_enforcer_warning_without_enforcers(tmp_path):
    from snapstudio_core import compatibility
    c = compatibility.check(_mini_3mf(tmp_path, enable_support="0", with_enforcer=False))
    assert not any(f["id"] == "support.enforcer_without_support" for f in c["findings"])
