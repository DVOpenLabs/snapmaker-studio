"""Local data-directory resolution.

Windows behaviour must stay byte-identical to what it was before this resolver
was centralized (it previously lived, duplicated, in service.py and
diagnostics.py). `create=False` and the atomic lock-down-at-creation behaviour
exist specifically so a read-only caller (diagnostics) and a caller-supplied
directory (SNAPSTUDIO_DATA_DIR / an explicit path) are never mutated or
permission-stripped as a side effect of merely resolving a path.

Platform BRANCH selection is tested by monkeypatching `sys.platform` directly
(paths.py reads it at call time) so every branch — Windows, Linux, and the
macOS/other fallback — is exercised on whatever OS actually runs this suite,
not only the one branch the CI host happens to be. Real filesystem calls still
go to the real OS underneath; Windows silently ignores POSIX mode bits rather
than erroring, so simulating the Linux branch's `mode=0o700` path on a Windows
CI runner is safe (it just won't assert the resulting permission bits there —
see the `sys.platform == "linux"`-gated assertions below).
"""
from __future__ import annotations
import os
import sys

import pytest

from snapstudio_core import paths


def test_explicit_argument_wins_over_env_and_platform_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(tmp_path / "from-env-should-be-ignored"))
    target = tmp_path / "explicit"
    result = paths.data_dir(str(target))
    assert result == str(target)
    assert target.is_dir()


def test_env_override_wins_over_platform_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    target = tmp_path / "from-env"
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
    assert paths.data_dir() == str(target)
    assert target.is_dir()


def test_windows_default_is_localappdata_subfolder(monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    result = paths.data_dir(create=False)
    assert result == os.path.join(r"C:\Users\someone\AppData\Local", "SnapmakerStudio")


def test_macos_default_is_unchanged_from_before_this_resolver_existed(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    result = paths.data_dir()
    assert result == os.path.join(str(tmp_path), "SnapmakerStudio")
    assert os.path.isdir(result)


def test_linux_default_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    result = paths.data_dir()
    assert result == str(tmp_path / "xdg-data" / "SnapmakerStudio")
    assert os.path.isdir(result)


def test_linux_relative_xdg_data_home_is_treated_as_unset(tmp_path, monkeypatch):
    """The XDG spec requires an absolute path; a relative value must fall back
    to the default rather than resolving against the current working directory."""
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    result = paths.data_dir(create=False)
    assert result == os.path.join(str(tmp_path), ".local", "share", "SnapmakerStudio")


def test_linux_fallback_is_local_share_when_xdg_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    result = paths.data_dir()
    assert result == os.path.join(str(tmp_path), ".local", "share", "SnapmakerStudio")


def test_create_false_does_not_create_or_touch_anything(tmp_path, monkeypatch):
    for plat in ("win32", "linux", "darwin"):
        monkeypatch.setattr(sys, "platform", plat)
        target = tmp_path / f"unresolved-{plat}"
        monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
        result = paths.data_dir(create=False)
        assert result == str(target)
        assert not target.exists()


def test_explicit_and_env_paths_are_never_chmodded_even_on_linux(tmp_path, monkeypatch):
    """A caller-supplied path must never be permission-stripped, even when the
    Linux branch is active and even on an existing directory the caller may not
    own outright (chmod/mode-on-mkdir there would raise and break every
    caller — this is the exact regression a reviewer flagged against an
    earlier version of this resolver)."""
    real_platform = sys.platform  # captured BEFORE the monkeypatch below, so the
    # permission-bit assertions only run where chmod is real, regardless of how
    # paths.py's own branch selection is being simulated for this test.
    monkeypatch.setattr(sys, "platform", "linux")
    for arg_kind in ("explicit", "env"):
        target = tmp_path / f"already-here-{arg_kind}"
        target.mkdir()
        if real_platform == "linux":
            os.chmod(target, 0o750)
            before = os.stat(target).st_mode & 0o777
        if arg_kind == "explicit":
            monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
            result = paths.data_dir(str(target))
        else:
            monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(target))
            result = paths.data_dir()
        assert result == str(target)
        if real_platform == "linux":
            after = os.stat(target).st_mode & 0o777
            assert after == before


@pytest.mark.skipif(sys.platform != "linux", reason="permission bits are only meaningful on a real POSIX filesystem")
def test_linux_default_is_created_with_locked_down_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    result = paths.data_dir()
    assert os.stat(result).st_mode & 0o777 == 0o700


@pytest.mark.skipif(sys.platform != "linux", reason="permission bits are only meaningful on a real POSIX filesystem")
def test_linux_existing_directory_permissions_are_never_touched(tmp_path, monkeypatch):
    """Atomic mode-at-creation (not a later chmod) means an already-existing
    directory — however its permissions were set, by Studio or by a user/admin —
    is never touched by a later call, and a crash between "created" and "would
    have chmodded" (the old two-step design) can no longer leave a directory
    permanently under-permissioned, because there is no such window."""
    monkeypatch.delenv("SNAPSTUDIO_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    result = paths.data_dir()
    assert os.stat(result).st_mode & 0o777 == 0o700

    os.chmod(result, 0o750)
    paths.data_dir()
    assert os.stat(result).st_mode & 0o777 == 0o750
