"""Release-governance lint.

Three documentation defects shipped in beta.22 and were only caught by reading
the files: the changelog carried the same release twice, the README's installer
hash duplicated a value the metadata file claims to own, and the trust-status
file still led with the previous release. None of those are code bugs, and all
three make a judge or a downloading user trust the wrong thing.

This test makes each of them a build failure. It reads the repository's own
documents and checks that they agree with each other; it does not hard-code a
version, so it stays true across releases.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
METADATA = ROOT / "docs" / "RELEASE_METADATA.md"
TRUST = ROOT / "docs" / "TRUST_STATUS.md"
RELEASE_NOTES = ROOT / "docs" / "RELEASE_NOTES.md"
PACKAGE_JSON = ROOT / "desktop" / "package.json"
TAURI_CONF = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
CARGO_TOML = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
PYPROJECT = ROOT / "backend" / "pyproject.toml"

# Keep-a-Changelog heading: "## [0.4.0-beta.22] - 2026-08-22". [Unreleased] and
# historical prose headings are allowed through and checked separately.
_RELEASE_HEADING = re.compile(r"^##\s*\[(?P<version>[^\]]+)\]", re.M)
_ANY_H2 = re.compile(r"^##\s+(?P<text>.+)$", re.M)
_VERSIONISH = re.compile(r"\d+\.\d+\.\d+")


def _read(path: Path) -> str:
    assert path.exists(), f"missing required document: {path}"
    return path.read_text(encoding="utf-8")


def _metadata_current() -> dict:
    """Parse the 'Current release' table out of RELEASE_METADATA.md."""
    text = _read(METADATA)
    start = text.index("## Current release")
    end = text.find("## Previous release", start)
    block = text[start:end if end != -1 else len(text)]
    fields = {}
    for row in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", block, re.M):
        key, value = row.group(1).strip(), row.group(2).strip()
        if key.lower() in ("field", "---"):
            continue
        fields[key.lower()] = value.strip("`")
    return fields


@pytest.fixture(scope="module")
def metadata() -> dict:
    fields = _metadata_current()
    for required in ("version", "installer", "size (bytes)", "sha256"):
        assert required in fields, f"RELEASE_METADATA.md is missing '{required}'"
    return fields


# --- the changelog ----------------------------------------------------------

def test_no_release_appears_twice_in_the_changelog():
    """The defect this file exists for: two headings for the same release."""
    versions = _RELEASE_HEADING.findall(_read(CHANGELOG))
    duplicates = {v for v in versions if versions.count(v) > 1}
    assert not duplicates, f"duplicate changelog entries for {sorted(duplicates)}"


def test_every_versioned_changelog_heading_uses_the_bracket_format():
    """A heading in another shape is how the duplicate slipped in unnoticed —
    it did not collide with the canonical one."""
    offenders = []
    for match in _ANY_H2.finditer(_read(CHANGELOG)):
        text = match.group("text").strip()
        if text.startswith("["):
            continue
        if _VERSIONISH.search(text):
            offenders.append(text)
    assert not offenders, (
        "changelog release headings must be '## [version] - date'; found: " + repr(offenders))


def test_the_current_release_has_a_changelog_entry(metadata):
    version = metadata["version"].lstrip("v")
    versions = [v.lstrip("v") for v in _RELEASE_HEADING.findall(_read(CHANGELOG))]
    assert version in versions, f"CHANGELOG.md has no entry for {version}"


def test_the_current_release_is_the_newest_changelog_entry(metadata):
    versions = [v for v in _RELEASE_HEADING.findall(_read(CHANGELOG))
                if v.lower() != "unreleased"]
    assert versions, "CHANGELOG.md has no release entries"
    assert versions[0].lstrip("v") == metadata["version"].lstrip("v"), (
        "the newest changelog entry is not the current release")


# --- the canonical release values -------------------------------------------
#
# RELEASE_METADATA.md is the single source of truth for version, installer name,
# size and hash. One duplication is allowed on purpose: the README's download
# block repeats the size and hash, because telling someone to open a second file
# before verifying a download is how verification stops happening. That
# duplication is safe only while it is checked, which is what these tests do.

def test_readme_repeats_the_canonical_hash_exactly(metadata):
    assert metadata["sha256"] in _read(README), (
        "README's SHA256 does not match RELEASE_METADATA.md")


def test_readme_repeats_the_canonical_size_exactly(metadata):
    size = metadata["size (bytes)"].replace(",", "")
    readme = _read(README)
    grouped = f"{int(size):,}"
    assert grouped in readme or size in readme, (
        "README's installer size does not match RELEASE_METADATA.md")


def test_readme_names_the_canonical_installer(metadata):
    assert metadata["installer"] in _read(README), (
        "README names a different installer than RELEASE_METADATA.md")


def test_readme_links_the_canonical_release_tag(metadata):
    assert metadata["version"] in _read(README), (
        "README does not reference the current release version")


def test_no_stale_release_hash_survives_anywhere_in_the_docs(metadata):
    """A previous release's hash left in a download instruction is worse than no
    hash at all. Only the metadata file may name an older one, and only in its
    'Previous release' table."""
    current = metadata["sha256"]
    old_hashes = set()
    meta_text = _read(METADATA)
    previous = meta_text.find("## Previous release")
    if previous != -1:
        old_hashes = {h for h in re.findall(r"\b[0-9a-f]{64}\b", meta_text[previous:])
                      if h != current}
    for doc in (README, RELEASE_NOTES):
        text = _read(doc)
        for stale in old_hashes:
            assert stale not in text, f"{doc.name} still carries a superseded SHA256"


# --- versions in the shipped manifests --------------------------------------

def test_app_manifests_match_the_released_version(metadata):
    version = metadata["version"].lstrip("v")
    for manifest in (PACKAGE_JSON, TAURI_CONF):
        text = _read(manifest)
        found = re.search(r'"version"\s*:\s*"([^"]+)"', text)
        assert found, f"{manifest.name} has no version field"
        assert found.group(1) == version, (
            f"{manifest.name} says {found.group(1)}, metadata says {version}")


def test_the_rust_crate_version_matches_the_released_version(metadata):
    """The Rust crate is the one manifest nothing else reads at runtime, so it
    drifted silently: it still said 0.4.0-beta.21.3 three releases later."""
    version = metadata["version"].lstrip("v")
    found = re.search(r'^version\s*=\s*"([^"]+)"', _read(CARGO_TOML), re.M)
    assert found, "Cargo.toml has no version field"
    assert found.group(1) == version, (
        f"Cargo.toml says {found.group(1)}, metadata says {version}")


def test_the_backend_package_version_matches_the_released_version(metadata):
    """backend/pyproject.toml drifted silently from beta.12 for a dozen
    releases — nothing at runtime reads it, but it is runtime-visible in
    diagnostics.py's support bundle and convert.py's settings summary, and a
    1.0 product whose engine package still claims 0.4.0b12 is a trust wart."""
    version = metadata["version"].lstrip("v")
    found = re.search(r'^version\s*=\s*"([^"]+)"', _read(PYPROJECT), re.M)
    assert found, "backend/pyproject.toml has no version field"
    assert found.group(1) == version, (
        f"backend/pyproject.toml says {found.group(1)}, metadata says {version}")


# --- trust status -----------------------------------------------------------

def test_trust_status_covers_the_current_release(metadata):
    """The defect: metadata moved to a new release while the trust file still
    led with the previous one, so the published verification state described a
    build nobody was downloading."""
    version = metadata["version"]
    text = _read(TRUST)
    assert version in text, (
        f"docs/TRUST_STATUS.md has no section for {version}")


def test_trust_status_leads_with_the_current_release(metadata):
    version = metadata["version"].lstrip("v")
    headings = [m.group("text").strip() for m in _ANY_H2.finditer(_read(TRUST))
                if _VERSIONISH.search(m.group("text"))]
    assert headings, "docs/TRUST_STATUS.md has no versioned sections"
    assert version in headings[0], (
        f"docs/TRUST_STATUS.md leads with '{headings[0]}', not {version}")


def test_release_notes_are_for_the_current_release(metadata):
    version = metadata["version"]
    first_line = _read(RELEASE_NOTES).splitlines()[0]
    assert version in first_line, (
        f"docs/RELEASE_NOTES.md leads with '{first_line}', not {version}")


# --- claims the engine has to be able to back ------------------------------

_FORBIDDEN = (
    "guaranteed to print",
    "100% success",
    "will print successfully",
    "guarantees a successful print",
    "validated for printing",
)


def test_public_copy_makes_no_print_success_promise():
    """Studio is advisory. These phrases would make it a warranty."""
    for doc in (README, RELEASE_NOTES, METADATA):
        lowered = _read(doc).lower()
        for phrase in _FORBIDDEN:
            assert phrase not in lowered, f"{doc.name} contains '{phrase}'"
