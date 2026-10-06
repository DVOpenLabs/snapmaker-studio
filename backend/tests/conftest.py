"""Test-wide isolation.

Studio reads the presets a person made in Snapmaker Orca (read-only). A test must never see the real
ones on the machine running it, so every test starts with Orca's data folder pointed at an empty,
throwaway location. A test that wants user presets sets SNAPSTUDIO_ORCA_DATA_DIR itself.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_orca_user_data(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("SNAPSTUDIO_ORCA_DATA_DIR", str(tmp_path_factory.mktemp("no-orca-data")))
