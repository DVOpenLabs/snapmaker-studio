"""Test-wide isolation.

Studio reads the presets a person made in Snapmaker Orca (read-only). A test must never see the real
ones on the machine running it, so every test starts with Orca's data folder pointed at an empty,
throwaway location. A test that wants user presets sets SNAPSTUDIO_ORCA_DATA_DIR itself.

Studio's own data folder gets the same treatment: every test (and every subprocess it starts) sees
SNAPSTUDIO_DATA_DIR and the per-user home variables pointed at a throwaway folder. The real data
folder is resolved once, before anything is patched, and a signature of it is compared at start and
teardown of every test: a test that touched the real folder fails.
"""
import hashlib
import os

import pytest

from snapstudio_core import paths as _paths

_SIGNATURE_LIMIT = 5000


def real_data_dir_path() -> str:
    """The real data folder, resolved from the environment as it was when this file was imported."""
    return _REAL_DATA_DIR


def data_dir_signature(path: str) -> str:
    """A cheap fingerprint of a folder: relative names, sizes and mtimes (not contents).

    'absent' for a missing folder. Entries beyond a fixed limit are counted, not listed, so a huge
    library cannot make every test slow.
    """
    if not os.path.isdir(path):
        return "absent"
    digest = hashlib.sha256()
    seen = 0
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files) + list(dirs):
            seen += 1
            if seen > _SIGNATURE_LIMIT:
                break
            full = os.path.join(root, name)
            try:
                stat = os.stat(full)
                record = f"{os.path.relpath(full, path)}|{stat.st_size}|{stat.st_mtime_ns}"
            except OSError:
                record = f"{os.path.relpath(full, path)}|gone"
            digest.update(record.encode("utf-8", "replace"))
        if seen > _SIGNATURE_LIMIT:
            break
    digest.update(f"count={seen}".encode())
    return digest.hexdigest()


def is_inside(path: str, folder: str) -> bool:
    """True if `path` is `folder` or lies inside it (case-insensitive on Windows)."""
    a = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    b = os.path.normcase(os.path.realpath(os.path.abspath(folder)))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


class RealDataDirRefused(AssertionError):
    pass


def refuse_real_data_dir(path: str) -> str:
    """Return `path` unchanged, or raise before anything is written if it is inside the real data folder."""
    if is_inside(path, _REAL_DATA_DIR):
        raise RealDataDirRefused(f"refusing to use the real Studio data folder: {path}")
    return path


# Resolved at import, before any fixture patches the environment. create=False: never makes the folder.
_REAL_DATA_DIR = _paths.data_dir(create=False)


@pytest.fixture(autouse=True)
def _no_real_orca_user_data(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("SNAPSTUDIO_ORCA_DATA_DIR", str(tmp_path_factory.mktemp("no-orca-data")))


@pytest.fixture(autouse=True)
def _isolated_studio_data(monkeypatch, tmp_path_factory):
    before = data_dir_signature(_REAL_DATA_DIR)
    home = tmp_path_factory.mktemp("studio-home")
    data = home / "data"
    data.mkdir()
    monkeypatch.setenv("SNAPSTUDIO_DATA_DIR", str(data))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "localappdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "xdg"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    yield data
    after = data_dir_signature(_REAL_DATA_DIR)
    if after != before:
        pytest.fail(f"a test changed the real Studio data folder: {_REAL_DATA_DIR}", pytrace=False)


@pytest.fixture
def real_data_dir() -> str:
    return _REAL_DATA_DIR


@pytest.fixture
def real_data_dir_guard():
    """Callable: refuse_real_data_dir. Raises RealDataDirRefused for a path inside the real folder."""
    return refuse_real_data_dir


@pytest.fixture
def folder_signature():
    """Callable: data_dir_signature."""
    return data_dir_signature
