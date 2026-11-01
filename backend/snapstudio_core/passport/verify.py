"""Check a passport against the files that exist now. Files are only read.

For each artifact: do the bytes on disk still match (`same_bytes`)? Then the chain: a changed
file invalidates itself and everything derived from it, because the record "B was made from A"
no longer describes the A that exists. A file that cannot be found or read makes its lineage
`unverified`, never `intact`. `intact` means the bytes match what the passport recorded; for a
`declared` link it is still the declarer's word, which the output says.

A declared derivation whose input exists locally with different bytes is flagged
`declared_mismatch`. It is never promoted to `local`.
"""
from __future__ import annotations

import os
from snapstudio_core import localpath
from typing import Any

from snapstudio_core.foundation.artifacts import CHANGED, MISSING, SAME, UNREADABLE, UNVERIFIED, same_bytes

from .model import Passport

INTACT, INVALIDATED = "intact", "invalidated"
_BAD = (MISSING, UNREADABLE, UNVERIFIED)


def _resolve(artifact: Any, names: dict, paths: dict, base_dir: str | None) -> str | None:
    """The local file for an artifact: an explicit path, else a unique file name inside `base_dir`."""
    explicit = paths.get(artifact.artifact_id) or (paths.get(artifact.name) if names[artifact.name] == 1 else None)
    if explicit:
        return localpath.usable_path(explicit)
    if base_dir and names[artifact.name] == 1 and _is_bare_file_name(artifact.name):
        return localpath.usable_path(os.path.join(base_dir, artifact.name))
    return None


def _is_bare_file_name(name: str) -> bool:
    """A single file name, whichever OS wrote the passport: no separator of either style, no drive, no dot-dot."""
    return bool(name) and name not in (".", "..") and not any(ch in name for ch in ("/", "\\", ":", "\x00"))


def _ancestors(artifact_id: str, parents: dict) -> list:
    """Every artifact the given one was derived from, nearest first. Cycle-safe (declared data may loop)."""
    seen: list = []
    queue = list(parents.get(artifact_id, []))
    while queue:
        current = queue.pop(0)
        if current == artifact_id or current in seen:
            continue
        seen.append(current)
        queue.extend(parents.get(current, []))
    return seen


def verify_passport(passport: Passport, *, base_dir: str | None = None, paths: dict | None = None) -> dict:
    paths = paths or {}
    by_id = {a.artifact_id: a for a in passport.artifacts}
    names: dict = {}
    for artifact in passport.artifacts:
        names[artifact.name] = names.get(artifact.name, 0) + 1
    state = {a.artifact_id: same_bytes(a, _resolve(a, names, paths, base_dir)) for a in passport.artifacts}
    parents: dict = {}
    for drv in passport.derivations:
        parents.setdefault(drv.output, []).extend(i["ref"] for i in drv.inputs)

    artifact_rows = []
    for artifact in passport.artifacts:
        aid = artifact.artifact_id
        reasons: list = []
        if state[aid] == CHANGED:
            reasons.append({"code": "bytes_changed", "artifact": artifact.name})
        for anc in _ancestors(aid, parents):
            if state[anc] == CHANGED:
                reasons.append({"code": "ancestor_changed", "artifact": by_id[anc].name})
        if reasons:
            chain = INVALIDATED
        else:
            if state[aid] in _BAD:
                reasons.append({"code": f"bytes_{state[aid]}", "artifact": artifact.name})
            for anc in _ancestors(aid, parents):
                if state[anc] in _BAD:
                    reasons.append({"code": f"ancestor_{state[anc]}", "artifact": by_id[anc].name})
            chain = UNVERIFIED if reasons else INTACT
        artifact_rows.append({"artifact_id": aid, "name": artifact.name, "role": artifact.role,
                              "size_bytes": artifact.bytes.size_bytes, "sha256": artifact.bytes.sha256,
                              "bytes": state[aid], "chain": chain, "reasons": reasons})

    derivation_rows = []
    for drv in passport.derivations:
        involved = [drv.output] + [i["ref"] for i in drv.inputs]
        if any(state[x] == CHANGED for x in involved):
            status = INVALIDATED
        elif any(state[x] != SAME for x in involved):
            status = UNVERIFIED
        else:
            status = INTACT
        input_states = [state[i["ref"]] for i in drv.inputs]
        if drv.witness == "declared":
            mismatch: bool | None = True if CHANGED in input_states else (False if all(
                s == SAME for s in input_states) else None)
        else:
            mismatch = False
        derivation_rows.append({
            "derivation_id": drv.derivation_id, "output": by_id[drv.output].name,
            "inputs": [{"kind": i["kind"], "name": by_id[i["ref"]].name} for i in drv.inputs],
            "producer": dict(drv.producer), "witness": drv.witness, "declared_by": drv.declared_by,
            "declared_mismatch": mismatch, "status": status})

    def names_of(chain: str) -> list:
        return [r["name"] for r in artifact_rows if r["chain"] == chain]

    summary = {"all_intact": bool(artifact_rows) and all(r["chain"] == INTACT for r in artifact_rows),
               "intact": names_of(INTACT), "invalidated": names_of(INVALIDATED),
               "unverified": names_of(UNVERIFIED),
               "declared_mismatch": [d["output"] for d in derivation_rows if d["declared_mismatch"]]}
    return {"passport_id": passport.passport_id, "artifacts": artifact_rows, "derivations": derivation_rows,
            "recipes_retained": [r.recipe_id for r in passport.recipes],
            "material_mappings_retained": [m["slot_ref"] for m in passport.material_mappings],
            "losses": list(passport.losses), "summary": summary,
            "note": ("A match means the bytes are the same as the passport recorded. A declared link is the "
                     "declarer's statement; Studio did not watch the file being made.")}
