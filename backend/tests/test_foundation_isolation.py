"""The test run never touches the real Studio data folder."""
import os
import subprocess
import sys

import pytest

from snapstudio_core import paths


def test_data_dir_is_a_throwaway_folder(real_data_dir):
    resolved = paths.data_dir()
    assert os.path.normcase(os.path.realpath(resolved)) != os.path.normcase(os.path.realpath(real_data_dir))
    assert os.environ["SNAPSTUDIO_DATA_DIR"] == resolved
    assert not resolved.startswith(real_data_dir)


def test_home_variables_are_redirected(real_data_dir):
    for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_DATA_HOME"):
        value = os.environ[name]
        assert not os.path.normcase(os.path.abspath(value)).startswith(os.path.normcase(real_data_dir))
    assert os.path.expanduser("~") == os.environ["HOME"] or os.path.expanduser("~") == os.environ["USERPROFILE"]


def test_override_removed_still_does_not_reach_real_folder(monkeypatch, real_data_dir):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR")
    resolved = paths.data_dir(create=False)
    assert os.path.normcase(os.path.realpath(resolved)) != os.path.normcase(os.path.realpath(real_data_dir))


def test_subprocess_inherits_the_override():
    code = "from snapstudio_core import paths; print(paths.data_dir(create=False))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env=os.environ.copy(), cwd=os.path.dirname(os.path.dirname(__file__)))
    assert out.stdout.strip() == os.environ["SNAPSTUDIO_DATA_DIR"]


def test_real_folder_access_is_refused(real_data_dir, real_data_dir_guard):
    from conftest import RealDataDirRefused  # noqa: PLC0415 - shared helper class
    with pytest.raises(RealDataDirRefused):
        real_data_dir_guard(real_data_dir)
    with pytest.raises(RealDataDirRefused):
        real_data_dir_guard(os.path.join(real_data_dir, "library", "x.db"))
    safe = os.path.join(os.environ["SNAPSTUDIO_DATA_DIR"], "x.db")
    assert real_data_dir_guard(safe) == safe


def test_guard_does_not_confuse_a_sibling_folder(real_data_dir, real_data_dir_guard):
    sibling = real_data_dir + "-other"
    assert real_data_dir_guard(sibling) == sibling


def test_signature_detects_a_change(tmp_path, folder_signature):
    assert folder_signature(str(tmp_path / "missing")) == "absent"
    base = folder_signature(str(tmp_path))
    assert folder_signature(str(tmp_path)) == base
    (tmp_path / "a.txt").write_text("one")
    with_file = folder_signature(str(tmp_path))
    assert with_file != base
    (tmp_path / "a.txt").write_text("longer")
    assert folder_signature(str(tmp_path)) != with_file
    (tmp_path / "sub").mkdir()
    assert folder_signature(str(tmp_path)) != with_file


def test_signature_of_real_folder_is_stable_without_writes(real_data_dir, folder_signature):
    assert folder_signature(real_data_dir) == folder_signature(real_data_dir)
