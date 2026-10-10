"""Doctor and Prepare agree; refusals read as plain language; Prepare writes no backup.

Fixtures are built at test time from the committed Bambu-authored base; no
third-party model is committed.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from snapstudio_api import service
from snapstudio_api.server import build_server
from snapstudio_core import convert as conv
from snapstudio_core import doctor
from snapstudio_core.container import ThreeMF
from snapstudio_core.errors import UnsoundOutput, plain_refusal
from tests.test_api import _request
from tests.test_native_object_settings import SUPPORT_SHAPE, _inject
from tests.test_repeated_component import _repeated

UNPROVEN = {**SUPPORT_SHAPE, "ironing_type": "top surface"}
PREPARE_ACTION = "Prepare a U1 profile copy"


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _orig(src) -> Path:
    return Path(src).with_suffix(".orig.3mf")


# --- Doctor and Prepare agree --------------------------------------------------

def test_doctor_does_not_send_a_file_prepare_would_refuse_to_prepare(tmp_path):
    src = _inject(tmp_path, UNPROVEN)
    problems = conv.structure_problems(ThreeMF.open(src))
    assert any("ironing_type is not a setting Studio has proved" in p for p in problems)
    d = doctor.diagnose_path(src)
    assert d.verdict == doctor.HIGH_RISK
    assert PREPARE_ACTION not in d.recommended_action
    assert any("ironing_type" in i for i in d.validation_issues)
    assert d.to_dict()["schema_version"] == "doctor/1"
    with pytest.raises(UnsoundOutput):                      # the same engine does refuse
        conv.convert_to_u1(src, str(tmp_path / "out"))


def test_doctor_still_recommends_prepare_when_prepare_will_work(tmp_path):
    src = _inject(tmp_path, SUPPORT_SHAPE)
    d = doctor.diagnose_path(src)
    assert d.verdict == doctor.REPAIRABLE and PREPARE_ACTION in d.recommended_action
    assert conv.convert_to_u1(src, str(tmp_path / "out")).validated_ok


def test_doctor_accepts_a_repeated_component_that_prepare_accepts(tmp_path):
    src = _repeated(tmp_path)
    d = doctor.diagnose_path(src)
    assert d.verdict == doctor.REPAIRABLE and not d.validation_issues
    assert conv.convert_to_u1(src, str(tmp_path / "out")).validated_ok


def test_check_structure_behaviour_is_unchanged(tmp_path):
    bad = ThreeMF.open(_inject(tmp_path, UNPROVEN))
    with pytest.raises(UnsoundOutput) as ei:
        conv.check_structure(bad)
    assert ei.value.problems == conv.structure_problems(bad)
    conv.check_structure(ThreeMF.open(_inject(tmp_path, SUPPORT_SHAPE, "ok.3mf")))


# --- the refusal is a sentence, the technical text is secondary ---------------

def test_the_refusal_names_the_settings_the_object_and_the_next_step():
    text = plain_refusal([
        'object 4 ("Lid"): skin_infill_density is not a setting Studio has proved Snapmaker '
        "Orca acts on, so it must not be written into a prepared copy",
        'object 4 ("Lid"): ironing_type is not a setting Studio has proved Snapmaker Orca '
        "acts on, so it must not be written into a prepared copy",
    ])
    assert "Studio only keeps per-object settings it has verified Snapmaker Orca reads" in text
    assert "2 setting(s)" in text and 'object 4 ("Lid")' in text
    assert "ironing_type, skin_infill_density" in text
    assert "Open the original in Snapmaker Orca" in text
    assert "your original file was not changed" in text
    for jargon in ("UnsoundOutput", "cannot vouch for", "written into a prepared copy"):
        assert jargon not in text


def test_a_structural_refusal_is_plain_too():
    text = plain_refusal(["object 3 lists 4 part(s) and has 3 component(s)"])
    assert "internal structure" in text and "lists 4 part(s)" not in text


def test_the_exception_keeps_the_technical_text_separately(tmp_path):
    with pytest.raises(UnsoundOutput) as ei:
        conv.convert_to_u1(_inject(tmp_path, UNPROVEN), str(tmp_path / "out"))
    assert str(ei.value) != ei.value.details
    assert ei.value.details.startswith("Studio built a prepared copy it cannot vouch for")
    assert "ironing_type" in str(ei.value) and "UnsoundOutput" not in str(ei.value)


def test_the_api_422_body_has_a_plain_error_and_separate_details(tmp_path):
    src = _inject(tmp_path, UNPROVEN)
    httpd, token = build_server(port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, body = _request(port, "/convert", {"path": src, "out_dir": str(tmp_path / "out")}, token)
    finally:
        httpd.shutdown()
    assert status == 422 and body["refusal"] == "UnsoundOutput"
    assert "ironing_type" in body["error"] and "Snapmaker Orca" in body["error"]
    assert "cannot vouch for" not in body["error"]
    assert "cannot vouch for" in body["details"] and "ironing_type is not a setting" in body["details"]


# --- no .orig.3mf from Prepare -------------------------------------------------

def test_prepare_writes_no_backup_and_leaves_the_original_alone(tmp_path):
    src = Path(_inject(tmp_path, SUPPORT_SHAPE))
    before = _sha(src)
    result = conv.convert_to_u1(str(src), str(tmp_path / "out"))
    assert result.validated_ok and not _orig(src).exists()
    assert _sha(src) == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == [src.name]


def test_the_api_service_writes_no_backup_on_success_or_refusal(tmp_path):
    ok = Path(_inject(tmp_path, SUPPORT_SHAPE, "ok.3mf"))
    bad = Path(_inject(tmp_path, UNPROVEN, "bad.3mf"))
    hashes = {ok: _sha(ok), bad: _sha(bad)}
    assert service.convert(str(ok), str(tmp_path / "out"))["validated_ok"]
    with pytest.raises(UnsoundOutput):
        service.convert(str(bad), str(tmp_path / "out"))
    assert not _orig(ok).exists() and not _orig(bad).exists()
    assert {p: _sha(p) for p in hashes} == hashes


def test_keep_backup_is_opt_in_and_only_after_the_copy_is_saved(tmp_path):
    src = Path(_inject(tmp_path, SUPPORT_SHAPE))
    conv.convert_to_u1(str(src), str(tmp_path / "out"), keep_backup=True)
    assert _orig(src).exists() and _sha(_orig(src)) == _sha(src)
    bad = Path(_inject(tmp_path, UNPROVEN, "bad.3mf"))
    with pytest.raises(UnsoundOutput):
        conv.convert_to_u1(str(bad), str(tmp_path / "out"), keep_backup=True)
    assert not _orig(bad).exists()


# --- the CLI keeps its in-place contract ---------------------------------------

def _cli(*args):
    from u1convert.cli import cli
    return CliRunner().invoke(cli, list(args))


def test_cli_repair_still_writes_the_backup_and_never_changes_the_input(tmp_path):
    src = Path(_inject(tmp_path, SUPPORT_SHAPE))
    before = _sha(src)
    result = _cli("repair", str(src), "-o", str(tmp_path / "fixed.3mf"))
    assert result.exit_code == 0, result.output
    assert _orig(src).exists() and _sha(_orig(src)) == before
    assert (tmp_path / "fixed.3mf").exists() and _sha(src) == before


def test_cli_repair_failure_after_the_backup_leaves_none_behind(tmp_path, monkeypatch):
    src = Path(_inject(tmp_path, SUPPORT_SHAPE))

    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ThreeMF, "save", boom)
    result = _cli("repair", str(src), "-o", str(tmp_path / "fixed.3mf"))
    assert result.exit_code != 0
    assert not _orig(src).exists()


def test_cli_dry_run_writes_no_backup(tmp_path):
    src = Path(_inject(tmp_path, SUPPORT_SHAPE))
    assert _cli("repair", str(src), "--dry-run").exit_code == 0
    assert not _orig(src).exists()


# --- part-level nil in options Snapmaker Orca 2.4.0 cannot read ---------------

NIL_SPEEDS = {"inner_wall_speed": "50,nil", "small_perimeter_speed": "50%,nil",
              "internal_solid_infill_speed": "50,nil", "sparse_infill_speed": "50,nil",
              "top_surface_speed": "50,nil"}


def _with_part_metadata(tmp_path, extra: dict, name="nil.3mf") -> str:
    import re
    import zipfile
    from tests.test_native_object_settings import BASE, CONFIG
    out = tmp_path / name
    add = "".join(f'      <metadata key="{k}" value="{v}"/>\n' for k, v in extra.items())
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == CONFIG:
                text, n = re.subn(r'(<part id="1"[^>]*>\n)', lambda m: m.group(1) + add,
                                  data.decode("utf-8"), count=1)
                assert n
                data = text.encode("utf-8")
            dst.writestr(item, data)
    return str(out)


def test_a_nil_in_a_non_nullable_part_speed_is_refused_plainly_and_the_doctor_agrees(tmp_path):
    src = _with_part_metadata(tmp_path, {**NIL_SPEEDS, "vertical_shell_speed": "80%,nil"})
    problems = conv.structure_problems(ThreeMF.open(src))
    assert len(problems) == 1 and "part 1 of object 2" in problems[0]
    assert "vertical_shell_speed" not in problems[0]        # not an Orca 2.4.0 option
    assert doctor.diagnose_path(src).verdict == doctor.HIGH_RISK
    with pytest.raises(UnsoundOutput) as ei:
        conv.convert_to_u1(src, str(tmp_path / "out"))
    text = str(ei.value)
    assert text.startswith("Snapmaker Orca 2.4.0 cannot load this project: part 1 of object 2")
    assert "inner_wall_speed" in text and "Studio does not edit" in text
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_a_nil_in_a_nullable_or_unlisted_option_is_not_refused(tmp_path):
    src = _with_part_metadata(tmp_path, {"filament_retraction_length": "nil", "outer_wall_speed": "60"})
    assert conv.structure_problems(ThreeMF.open(src)) == []
