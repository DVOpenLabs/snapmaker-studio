"""Job passport: the derivation chain of a job and what travelled with it.

    build_passport(entries)        files -> passport (declared chain by default)
    import_passport(raw)           passport JSON -> normalised passport, always declared
    verify_passport(passport)      are the files still the bytes the passport recorded?

Evidence: fixture-tested only. Studio does not watch a prepare or a slice happen, so a chain
is declared by whoever states it; verification checks bytes, not who made them.
"""
from __future__ import annotations

from typing import Any

from .build import BuildResult, build_passport
from .model import SCHEMA_VERSION, Passport, decode_passport
from .verify import verify_passport

__all__ = ["BuildResult", "Passport", "SCHEMA_VERSION", "build_passport", "decode_passport",
           "import_passport", "verify_passport"]


def import_passport(raw: Any, *, base_dir: str | None = None, paths: dict | None = None) -> dict:
    """Decode `raw` and, when `base_dir` or `paths` say where the files are, verify it.

    Never raises. `passport` is None when the document cannot be used (see `diagnostics`).
    """
    decoded = decode_passport(raw)
    out: dict = {"passport": None, "diagnostics": [d.to_dict() for d in decoded.diagnostics],
                 "losses": [], "parentage": [], "verification": None}
    passport = decoded.value
    if passport is None:
        return out
    out["passport"] = passport.to_dict()
    out["losses"] = list(passport.losses)
    if base_dir or paths:
        report = verify_passport(passport, base_dir=base_dir, paths=paths)
        out["verification"] = report
        out["parentage"] = report["derivations"]
    else:
        by_id = {a.artifact_id: a.name for a in passport.artifacts}
        out["parentage"] = [{"output": by_id[d.output], "inputs": [{"kind": i["kind"], "name": by_id[i["ref"]]}
                                                                    for i in d.inputs],
                             "producer": dict(d.producer), "witness": d.witness, "declared_by": d.declared_by,
                             "declared_mismatch": None, "status": "unverified"} for d in passport.derivations]
    return out
