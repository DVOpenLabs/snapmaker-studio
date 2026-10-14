"""beta.18.3 readiness-truth: profile-compatible != print-ready when setup risks remain."""
import zipfile, json, os
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
from snapstudio_core.validation_report import readiness_report, U1_TOOLHEADS


def _make_3mf(tmp, colors, printer="Snapmaker U1"):
    """Minimal 3MF with N filament colours, off a real sample if present."""
    base = str(_ROOT / "examples" / "sample_cube_U1.3mf")
    dst = os.path.join(tmp, f"c{colors}.3mf")
    zin = zipfile.ZipFile(base)
    cfg = json.loads(zin.read("Metadata/project_settings.config"))
    cfg["filament_colour"] = [f"#{i:06X}" for i in range(colors)]
    cfg["printer_model"] = printer
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            data = json.dumps(cfg).encode() if it.filename == "Metadata/project_settings.config" else zin.read(it.filename)
            zo.writestr(it, data)
    return dst


def test_more_colours_than_toolheads_blocks_ready(tmp_path):
    f = _make_3mf(str(tmp_path), 13)
    r = readiness_report(f)
    assert r["ready"] is False, "13 colours on 4 toolheads must NOT be ready"
    # the Doctor's verdict is unchanged by a setup warning: the warning is `ready: false`
    assert r["verdict"] == r["profile_verdict"] == "REPAIRABLE"
    assert r["readiness_score"] <= 70, "no perfect score while setup review remains"
    assert any("toolhead" in a.lower() for a in r["at_risk"])


def test_within_toolheads_can_pass_colours_check(tmp_path):
    f = _make_3mf(str(tmp_path), U1_TOOLHEADS)
    r = readiness_report(f)
    col = next((c for c in r["checks"] if c["name"] == "Colours vs toolheads"), None)
    assert col and col["status"] == "pass"


def test_profile_verdict_preserved(tmp_path):
    f = _make_3mf(str(tmp_path), 13)
    r = readiness_report(f)
    # underlying profile compatibility is still surfaced separately, not as the headline.
    assert r.get("profile_verdict") is not None


def test_a_setup_warning_does_not_rewrite_the_doctors_verdict(tmp_path):
    """HIGH_RISK means "not a usable project" and nothing else. A READY project with a setup
    warning stays READY (the warning is `ready: false`); an unusable file is HIGH_RISK."""
    from snapstudio_core.doctor import diagnose_path
    f = _make_3mf(str(tmp_path), U1_TOOLHEADS)            # profile READY, spacing/layout unverified
    r = readiness_report(f)
    assert diagnose_path(f).verdict == "READY"
    assert r["verdict"] == "READY" and r["profile_verdict"] == "READY"
    assert r["ready"] is False and r["at_risk"] or not r["ready"]
    junk = tmp_path / "junk.3mf"
    junk.write_bytes(b"not a zip")
    assert readiness_report(str(junk))["verdict"] == "HIGH_RISK"
