"""A Microsoft Store Python launcher cannot be resolved strictly (WinError 1920) although it runs.

The generic runner is not used by the Lumina HTTP journey; these tests cover only how it admits its own interpreter.
They simulate the alias on every platform, so they do not depend on which Python runs the suite.
"""
import sys
from pathlib import Path

import pytest

from snapstudio_core.engines.cli_runner import CliRunner

_REAL_RESOLVE = Path.resolve


def _alias_like(monkeypatch, target: Path):
    def resolve(self, strict=False):
        if strict and self == target:
            raise OSError(22, "The file cannot be accessed by the system")   # what the alias raises
        return _REAL_RESOLVE(self, strict=strict)
    monkeypatch.setattr(Path, "resolve", resolve)


def test_own_interpreter_is_admitted_when_strict_resolution_fails_but_it_stats_and_runs(monkeypatch, tmp_path):
    _alias_like(monkeypatch, Path(sys.executable))
    root = tmp_path / "jobs"
    root.mkdir()
    runner = CliRunner(sys.executable, root, ("-c", "print('ok')"), timeout_s=30)   # admitted: no RunnerError
    result = runner.run()
    assert result.returncode == 0


def test_a_missing_executable_still_fails_with_file_not_found(tmp_path):
    from snapstudio_core.engines.cli_runner import _resolve_existing
    with pytest.raises(FileNotFoundError):
        _resolve_existing(tmp_path / "no-such-interpreter.exe")


def test_a_dangling_alias_is_not_admitted(monkeypatch, tmp_path):
    from snapstudio_core.engines.cli_runner import _resolve_existing
    ghost = tmp_path / "python.exe"
    _alias_like(monkeypatch, ghost)
    with pytest.raises(OSError):
        _resolve_existing(ghost)   # strict fails with OSError and nothing stats behind it
