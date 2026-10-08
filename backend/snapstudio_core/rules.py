from __future__ import annotations
import json
from importlib.resources import files

def load_rules() -> dict:
    return json.loads((files("snapstudio_core.data") / "u1_rules.json").read_text("utf-8"))

def apply_clamps(cfg: dict, rules: dict) -> list[dict]:
    findings = []
    for c in rules["clamps"]:
        k = c["key"]
        if k in cfg and str(cfg[k]) == c["bad"]:
            findings.append({"key": k, "old": cfg[k], "new": c["good"]})
            cfg[k] = c["good"]
    return findings


def clamp_explanation(change: dict) -> str:
    """Why a clamp changed this value, in words that rest on evidence Studio already has.

    The raft expansion keeps the wording its other owner (orca_import) uses. Every other clamped setting has a valid range in
    the Compatibility check, which flags a value outside it as invalid; the explanation says exactly that and names the value
    Studio used instead. Nothing is said about what the setting does to a print, because nothing here measures that.
    """
    from . import compatibility, orca_import
    key, old, new = change["key"], change["old"], change["new"]
    if key == "raft_first_layer_expansion":
        return orca_import.RAFT_EXPANSION_WHY
    span = compatibility.valid_range(key)
    if span is None:
        return f"{old} is not a value Studio accepts for this setting; Studio used {new}, the U1 profile's value."
    lo, hi = span
    allowed = f"{lo} or more" if hi >= 2147483647 else f"{lo} to {hi}"
    return (f"{old} is outside the valid range for this setting ({allowed}), which the Compatibility check flags as an "
            f"invalid value. Studio used {new}, the U1 profile's value.")
