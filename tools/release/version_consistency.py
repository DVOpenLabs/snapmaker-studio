"""Every manifest that carries Snapmaker Studio's own version must agree.

The release guards in backend/tests/test_release_docs.py compare the manifests
to docs/RELEASE_METADATA.md, which only changes when a release is prepared. That
left desktop/package-lock.json's root version at 1.0.0 through two releases:
nothing compared it to anything. This check compares the manifests with each
other, so drift fails the moment it is introduced, release or not.

The canonical version is desktop/package.json's. Every other surface must equal
it:
  - desktop/package-lock.json, top-level "version"
  - desktop/package-lock.json, packages[""].version
  - desktop/src-tauri/tauri.conf.json, "version"
  - desktop/src-tauri/Cargo.toml, [package] version
  - desktop/src-tauri/Cargo.lock, the snapmaker-studio-desktop package entry
  - backend/pyproject.toml, [project] version

Usage:
  python tools/release/version_consistency.py [repo-root]
Exits 0 when every surface agrees, 1 otherwise, naming each file, the expected
version and the version actually found.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CANONICAL = "desktop/package.json"
CRATE_NAME = "snapmaker-studio-desktop"


@dataclass(frozen=True)
class Surface:
    file: str
    field: str
    version: str | None  # None: the field is missing


@dataclass(frozen=True)
class Mismatch:
    file: str
    field: str
    expected: str
    actual: str | None

    def __str__(self) -> str:
        found = "missing" if self.actual is None else self.actual
        return f"{self.file} ({self.field}): expected {self.expected}, found {found}"


def _json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _toml(root: Path, rel: str) -> dict:
    return tomllib.loads((root / rel).read_text(encoding="utf-8"))


def _cargo_lock_version(root: Path) -> str | None:
    lock = _toml(root, "desktop/src-tauri/Cargo.lock")
    entries = [p for p in lock.get("package", []) if p.get("name") == CRATE_NAME]
    # A second entry with the same name would be ambiguous; treat it as missing
    # rather than guess which one is ours.
    return entries[0].get("version") if len(entries) == 1 else None


def surfaces(root: Path) -> list[Surface]:
    """Every version-carrying surface, canonical first."""
    lock = _json(root, "desktop/package-lock.json")
    return [
        Surface(CANONICAL, "version", _json(root, CANONICAL).get("version")),
        Surface("desktop/package-lock.json", "version", lock.get("version")),
        Surface("desktop/package-lock.json", 'packages[""].version',
                lock.get("packages", {}).get("", {}).get("version")),
        Surface("desktop/src-tauri/tauri.conf.json", "version",
                _json(root, "desktop/src-tauri/tauri.conf.json").get("version")),
        Surface("desktop/src-tauri/Cargo.toml", "[package] version",
                _toml(root, "desktop/src-tauri/Cargo.toml").get("package", {}).get("version")),
        Surface("desktop/src-tauri/Cargo.lock", f"{CRATE_NAME} version",
                _cargo_lock_version(root)),
        Surface("backend/pyproject.toml", "[project] version",
                _toml(root, "backend/pyproject.toml").get("project", {}).get("version")),
    ]


def mismatches(root: Path) -> list[Mismatch]:
    found = surfaces(root)
    canonical = found[0]
    if canonical.version is None:
        return [Mismatch(canonical.file, canonical.field, "a version", None)]
    return [
        Mismatch(s.file, s.field, canonical.version, s.version)
        for s in found[1:]
        if s.version != canonical.version
    ]


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[2]
    problems = mismatches(root)
    if problems:
        print(f"Version drift against {CANONICAL}:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"All {len(surfaces(root))} version surfaces agree: {surfaces(root)[0].version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
