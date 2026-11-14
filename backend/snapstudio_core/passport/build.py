"""Build a passport from files the user names. Files are only read, never written.

`entries` are ordered. Each is `{path, role, parents?, producer?}`: `parents` are indices of
EARLIER entries this one was made from (default: the entry before it, except for an original,
which has none). Because a parent must come earlier the chain cannot loop.

The chain is stated by the caller, so it is recorded `declared` (by "user") unless a Studio
step that actually ran the transformation passes `witness="local"`. The routes and the CLI
never do: this version does not observe a prepare or a slice happening.
"""
from __future__ import annotations

import os
from snapstudio_core import localpath
from dataclasses import dataclass, field
from typing import Any

from snapstudio_core.foundation.artifacts import ArtifactRef, Derivation
from snapstudio_core.foundation.decode import ERROR, NOTE, WARNING, Diagnostic, diag

from .model import (
    CHAIN_ROLES, MAX_ARTIFACTS, Passport, compute_passport_id, hash_file, retain_mappings, retain_recipes,
    utc_now_iso,
)

DECLARED_BY = "user"
DEFAULT_PRODUCER = {"tool": "unspecified", "version": None}


@dataclass
class BuildResult:
    passport: Passport | None
    diagnostics: list = field(default_factory=list)
    #: artifact_id -> the path it was read from. Local only: never part of the passport.
    paths: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"passport": self.passport.to_dict() if self.passport else None,
                "diagnostics": [d.to_dict() for d in self.diagnostics],
                "losses": list(self.passport.losses) if self.passport else []}


def _fail(code: str, where: str) -> BuildResult:
    return BuildResult(None, [diag(code, where, ERROR)])


def build_passport(entries: Any, *, recipes: Any = None, material_mappings: Any = None,
                   witness: str = "declared", created_at: str | None = None) -> BuildResult:
    """Never raises on bad input; `passport` is None when an error diagnostic says why."""
    if witness not in ("declared", "local"):
        raise ValueError(f"unknown witness {witness!r}")
    if not isinstance(entries, list) or not entries:
        return _fail("no_entries", "entries")
    if len(entries) > MAX_ARTIFACTS:
        return _fail("too_many_entries", "entries")
    diagnostics: list[Diagnostic] = []
    refs: list = []           # one ArtifactRef per entry (entries with identical bytes share the first)
    paths: dict = {}
    for i, entry in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"].strip():
            return _fail("bad_entry", where)
        role = entry.get("role")
        if role not in CHAIN_ROLES:
            return _fail("bad_role", f"{where}.role")
        path = entry["path"]
        try:
            if localpath.is_network_or_device_path(path) or localpath.usable_path(path) is None:
                return _fail("file_unreadable", f"{where}.path")
            if not os.path.isfile(path):
                return _fail("file_missing", f"{where}.path")
            sha, size = hash_file(path)
            ref = ArtifactRef.create(sha, size, role, os.path.basename(path))
        except OSError:
            return _fail("file_unreadable", f"{where}.path")
        refs.append(ref)
        paths.setdefault(ref.artifact_id, os.path.abspath(path))
    artifacts: list = []
    for i, ref in enumerate(refs):
        if any(a.artifact_id == ref.artifact_id for a in artifacts):
            diagnostics.append(diag("identical_bytes", f"entries[{i}]", NOTE))
        else:
            artifacts.append(ref)
    derivations: list = []
    for i, entry in enumerate(entries):
        where = f"entries[{i}]"
        parents = entry.get("parents")
        if parents is None:
            parents = [] if entry["role"] == "original" or i == 0 else [i - 1]
        if (not isinstance(parents, list) or not all(isinstance(p, int) and not isinstance(p, bool)
                                                       and 0 <= p < i for p in parents)
                or len(set(parents)) != len(parents)):
            return _fail("bad_parents", f"{where}.parents")
        if not parents:
            continue
        inputs = [{"kind": "settings" if entries[p]["role"] == "settings" else "artifact",
                   "ref": refs[p].artifact_id} for p in parents]
        if any(inp["ref"] == refs[i].artifact_id for inp in inputs):
            diagnostics.append(diag("identical_to_parent", where, WARNING))   # same bytes: nothing was derived
            continue
        producer = entry.get("producer") if isinstance(entry.get("producer"), dict) else DEFAULT_PRODUCER
        tool = producer.get("tool")
        version = producer.get("version")
        if not isinstance(tool, str) or not tool.strip() or len(tool) > 64 \
                or (version is not None and (not isinstance(version, str) or len(version) > 64)):
            return _fail("bad_producer", f"{where}.producer")
        derivation = Derivation.create(
            refs[i].artifact_id, inputs, {"tool": tool, "version": version}, witness=witness,
            declared_by=DECLARED_BY if witness == "declared" else None)
        if all(d.derivation_id != derivation.derivation_id for d in derivations):
            derivations.append(derivation)
    kept_recipes, recipe_losses, recipe_diags = retain_recipes(recipes)
    kept_mappings, mapping_losses = retain_mappings(material_mappings)
    diagnostics.extend(recipe_diags)
    passport = Passport(compute_passport_id(artifacts, derivations, kept_recipes, kept_mappings),
                        created_at or utc_now_iso(), artifacts, derivations, kept_recipes, kept_mappings,
                        recipe_losses + mapping_losses)
    return BuildResult(passport, diagnostics, paths)
