"""Every manifest carrying Studio's own version agrees with desktop/package.json.

desktop/package-lock.json's root version said 1.0.0 through the v1.1.0 and
v1.2.0 releases because the release guards compared each manifest to the
release metadata, and nothing compared the lockfile to anything. The check in
tools/release/version_consistency.py compares the manifests with each other.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import version_consistency as vc  # noqa: E402

FILES = [
    "desktop/package.json",
    "desktop/package-lock.json",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/Cargo.lock",
    "backend/pyproject.toml",
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the real version surfaces, free to break."""
    for rel in FILES:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    return tmp_path


def _canonical() -> str:
    return json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))["version"]


def _edit_json(repo: Path, rel: str, change) -> None:
    path = repo / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _sub(repo: Path, rel: str, pattern: str, repl: str) -> None:
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    assert n == 1, f"fixture edit did not apply to {rel}"
    path.write_text(new, encoding="utf-8")


def test_the_repository_itself_is_consistent():
    assert vc.mismatches(ROOT) == []


def test_every_surface_is_read(repo):
    found = vc.surfaces(repo)
    assert len(found) == 7
    assert all(s.version == _canonical() for s in found), found


def test_the_stale_lockfile_that_shipped_in_v1_2_0_is_caught(repo):
    """The exact drift this guard exists for: both lockfile root fields at 1.0.0."""
    def stale(data):
        data["version"] = "1.0.0"
        data["packages"][""]["version"] = "1.0.0"
    _edit_json(repo, "desktop/package-lock.json", stale)

    problems = [str(p) for p in vc.mismatches(repo)]
    v = _canonical()
    assert problems == [
        f"desktop/package-lock.json (version): expected {v}, found 1.0.0",
        f'desktop/package-lock.json (packages[""].version): expected {v}, found 1.0.0',
    ]


def test_only_the_packages_root_entry_drifting_is_caught(repo):
    _edit_json(repo, "desktop/package-lock.json",
               lambda d: d["packages"][""].__setitem__("version", "1.0.0"))
    assert [(p.file, p.field) for p in vc.mismatches(repo)] == [
        ("desktop/package-lock.json", 'packages[""].version')]


@pytest.mark.parametrize("rel, pattern, repl, field", [
    ("desktop/src-tauri/tauri.conf.json", r'"version":\s*"[^"]+"', '"version": "9.9.9"', "version"),
    ("desktop/src-tauri/Cargo.toml", r'^version = "[^"]+"', 'version = "9.9.9"', "[package] version"),
    ("desktop/src-tauri/Cargo.lock",
     r'(name = "snapmaker-studio-desktop"\r?\nversion = )"[^"]+"', r'\1"9.9.9"',
     "snapmaker-studio-desktop version"),
    ("backend/pyproject.toml", r'^version = "[^"]+"', 'version = "9.9.9"', "[project] version"),
])
def test_each_other_manifest_drifting_is_caught(repo, rel, pattern, repl, field):
    _sub(repo, rel, pattern, repl)
    problems = vc.mismatches(repo)
    assert len(problems) == 1
    p = problems[0]
    assert (p.file, p.field, p.expected, p.actual) == (rel, field, _canonical(), "9.9.9")
    assert str(p) == f"{rel} ({field}): expected {_canonical()}, found 9.9.9"


def test_package_json_is_the_source_of_truth(repo):
    """Bumping only package.json flags every other surface, not package.json."""
    _edit_json(repo, "desktop/package.json", lambda d: d.__setitem__("version", "9.9.9"))
    problems = vc.mismatches(repo)
    assert len(problems) == 6
    assert all(p.expected == "9.9.9" and p.file != "desktop/package.json" for p in problems)


def test_a_missing_field_is_reported_as_missing(repo):
    _edit_json(repo, "desktop/package-lock.json", lambda d: d.pop("version"))
    [p] = vc.mismatches(repo)
    assert p.actual is None
    assert str(p).endswith(f"expected {_canonical()}, found missing")


def test_an_ambiguous_cargo_lock_entry_is_not_guessed(repo):
    path = repo / "desktop/src-tauri/Cargo.lock"
    path.write_text(path.read_text(encoding="utf-8")
                    + f'\n[[package]]\nname = "snapmaker-studio-desktop"\nversion = "{_canonical()}"\n',
                    encoding="utf-8")
    [p] = vc.mismatches(repo)
    assert p.file == "desktop/src-tauri/Cargo.lock" and p.actual is None


def test_the_command_line_fails_and_names_the_file(repo, capsys):
    _edit_json(repo, "desktop/package-lock.json",
               lambda d: d.__setitem__("version", "1.0.0"))
    assert vc.main(["version_consistency.py", str(repo)]) == 1
    err = capsys.readouterr().err
    assert f"desktop/package-lock.json (version): expected {_canonical()}, found 1.0.0" in err


def test_the_command_line_passes_on_the_repository(capsys):
    assert vc.main(["version_consistency.py", str(ROOT)]) == 0
    assert "All 7 version surfaces agree" in capsys.readouterr().out
