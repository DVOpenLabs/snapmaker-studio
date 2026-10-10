"""Snapmaker Orca import compatibility — the fixes a foreign project needs to open cleanly.

A project authored in Bambu Studio for a Bambu printer usually *opens* in Snapmaker
Orca. What it does not do is open cleanly: features silently switch off, warnings
appear that name a setting rather than a cause, and in a few cases the slicer
refuses the file outright. Every rule in this module addresses one of those, and
each one records what it changed, what it was before, and why.

The dividing line, which matters more than any individual rule:

  **Compatibility is not intent.** Layer heights, speeds, temperatures, filament
  choices and support strategy are the creator's decisions and are carried through
  untouched — including in Preserve mode. What is corrected here is only the set of
  values that make Snapmaker Orca misbehave on a U1, regardless of what the creator
  wanted. A setting is only touched when leaving it alone produces a worse print or
  a broken import.

These behaviours are implemented independently from the publicly documented symptoms
they address (Snapmaker Orca / OrcaSlicer release notes, the U1 profile schema, and
the published behaviour of community converters). No third-party code or profile
data is used.
"""
from __future__ import annotations

import json
from importlib.resources import files

SCHEMA_VERSION = "orcaimport/1"

# Sliced output the authoring slicer left inside the project. It was produced by a
# different machine's kinematics and firmware, so it is wrong for the U1 in every
# case — and leaving it in lets Orca show a preview that is not what will print.
SLICE_CACHE_PREFIXES = ("Metadata/plate_",)
SLICE_CACHE_SUFFIXES = (".gcode", ".json")

_template_cache: dict | None = None


def u1_template() -> dict:
    """Studio's own U1 base project settings, used as the source of truth for
    "what should this value be on a U1" rather than any hard-coded constant."""
    global _template_cache
    if _template_cache is None:
        _template_cache = json.loads(
            (files("snapstudio_core.data") / "templates" / "u1_base_project_settings.json")
            .read_text("utf-8"))
    return _template_cache


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _text(cfg: dict, key: str) -> str:
    raw = _first(cfg.get(key))
    return "" if raw is None else str(raw).strip()


def _truthy(cfg: dict, key: str) -> bool:
    return _text(cfg, key).lower() in {"1", "true", "yes", "on"}


def _num(cfg: dict, key: str):
    try:
        return float(_text(cfg, key))
    except (TypeError, ValueError):
        return None


def _change(changes: list, key: str, old, new, reason: str, why: str) -> None:
    changes.append({"key": key, "old": old, "new": new, "reason": reason,
                    "explanation": why, "category": "orca-compatibility"})


# --- individual rules -------------------------------------------------------

def _enable_exclude_object(cfg: dict, changes: list) -> None:
    """The U1's per-object features are gated on Exclude Object being on.

    With it off, the printer cannot skip a single failed object mid-print, and
    adaptive bed mesh has no object outlines to probe against — so it falls back
    to probing the whole plate. Bambu projects frequently ship with it off
    because that printer does not need it. This costs the creator nothing.
    """
    if not _truthy(cfg, "exclude_object"):
        old = cfg.get("exclude_object")
        cfg["exclude_object"] = "1"
        _change(changes, "exclude_object", old, "1",
                "enabled so the U1 can skip a failed object and probe adaptively",
                "With Exclude Object off, the U1 cannot cancel one failed object "
                "without losing the whole plate, and adaptive bed mesh has no object "
                "outlines to work from.")


def _fix_auto_brim(cfg: dict, changes: list) -> None:
    """Only overrides a brim the creator did not deliberately choose.

    ``auto_brim`` means "let the slicer decide". Snapmaker Orca decides
    differently from the slicer this project was authored in, so a project that
    printed with no brim can come out with one — changing the footprint, the
    finish and the removal work. A brim the creator explicitly asked for
    (outer/inner/ears/a fixed width) is intent and is left alone.
    """
    brim = _text(cfg, "brim_type")
    if brim == "auto_brim":
        cfg["brim_type"] = "no_brim"
        _change(changes, "brim_type", brim, "no_brim",
                "the creator left the brim on automatic, and Snapmaker Orca decides "
                "differently from the slicer this was made in",
                "Automatic means the slicer chooses. Snapmaker Orca's choice can add "
                "a brim this project never had. A brim you asked for yourself is kept.")


def _fix_tree_support_with_adaptive_layers(cfg: dict, changes: list) -> None:
    """Variable layer height plus tree/organic support is a combination the
    authoring slicer quietly corrects when it loads a project, and never writes
    back into the file. Snapmaker Orca does not correct it, so the raw stored
    combination reaches the slicer and the supports come out wrong. Applying the
    same correction on the way in keeps the creator's support choice working.
    """
    adaptive = _truthy(cfg, "adaptive_layer_height")
    support_type = _text(cfg, "support_type").lower()
    style = _text(cfg, "support_style").lower()
    if not adaptive or "tree" not in support_type:
        return
    if style in ("organic", "tree_slim", "tree_strong"):
        cfg["support_style"] = "tree_hybrid"
        _change(changes, "support_style", style, "tree_hybrid",
                "tree support with variable layer height needs the hybrid style on the U1",
                "This project uses variable layer height with tree supports. The "
                "slicer it was made in silently switches that combination to hybrid "
                "when it opens the file; Snapmaker Orca does not, so Studio applies "
                "the same correction.")


def _fix_filament_array_validity(cfg: dict, changes: list, count: int) -> None:
    """Per-filament arrays that are the wrong shape are the difference between a
    project that opens and one that throws a warning or takes the slicer down.

    Three arrays matter: an empty entry in the adaptive volumetric-speed array is
    not tolerated by OrcaSlicer, the self-index array has to name every slot, and
    the flush-temperature array has to cover every slot. All three are repaired by
    filling from the value already in the array, never by inventing a number.
    """
    if count <= 0:
        return

    def pad_from_self(key: str, why: str, reason: str) -> None:
        value = cfg.get(key)
        if not isinstance(value, list) or not value:
            return
        filled = [v for v in value if str(v).strip() != ""]
        if not filled:
            return
        new = [(str(v).strip() or str(filled[-1])) for v in value]
        if len(new) < count:
            new = new + [new[-1]] * (count - len(new))
        elif len(new) > count:
            new = new[:count]
        if new != value:
            cfg[key] = new
            _change(changes, key, value, new, reason, why)

    pad_from_self(
        "filament_adaptive_volumetric_speed",
        "An empty entry in this list is rejected by OrcaSlicer when the project "
        "is opened, so every slot is given the value already present for its "
        "neighbours.",
        "filled empty per-filament entries so the project opens")
    pad_from_self(
        "filament_flush_temp",
        "This list has to cover every filament slot, or the slicer warns that the "
        "project configuration is invalid.",
        "resized to cover every filament slot")

    # self-index is positional by definition: slot N must say N. Repairing it by
    # copying a neighbour would be wrong, so it is rebuilt from the slot numbers.
    self_index = cfg.get("filament_self_index")
    if isinstance(self_index, list) and self_index:
        expected = [str(i + 1) for i in range(count)]
        if [str(v).strip() for v in self_index] != expected:
            cfg["filament_self_index"] = expected
            _change(changes, "filament_self_index", self_index, expected,
                    "renumbered so every filament slot identifies itself correctly",
                    "Each filament slot has to carry its own position. When the "
                    "numbering is missing or out of step the slicer reports an "
                    "invalid project configuration.")


# The raft expansion has two owners: the U1 clamp table (data/u1_rules.json), which runs in every mode and fixes -1, and
# the rule below, which runs in Preserve/U1/Optimize and fixes any negative value. They must agree on the value (the clamp's
# "good" is the U1 template default, checked by a test) and say the same thing about why, so the reason shown to the person
# does not depend on which of them acted.
RAFT_EXPANSION_REASON = "restored to the U1 default (a negative value is out of range)"
RAFT_EXPANSION_WHY = ("Snapmaker Orca and OrcaSlicer both reject a negative raft expansion "
                      "and warn when the project is opened.")


def _fix_negative_raft_expansion(cfg: dict, changes: list) -> None:
    """A negative raft expansion is out of range for both Snapmaker Orca and
    OrcaSlicer and produces a compatibility warning on open. The replacement
    comes from Studio's U1 base profile rather than a constant, so it stays
    correct if the profile changes."""
    value = _num(cfg, "raft_first_layer_expansion")
    if value is None or value >= 0:
        return
    default = u1_template().get("raft_first_layer_expansion")
    if default is None:
        return
    old = cfg.get("raft_first_layer_expansion")
    cfg["raft_first_layer_expansion"] = default
    _change(changes, "raft_first_layer_expansion", old, default,
            RAFT_EXPANSION_REASON, RAFT_EXPANSION_WHY)


NOZZLE_VOLUME_TYPE_REASON = "left out: Snapmaker Orca does not write this setting"
NOZZLE_VOLUME_TYPE_WHY = (
    "The projects Snapmaker Orca saves for the U1 do not contain a nozzle volume type; Bambu Studio and OrcaSlicer "
    "write one (for example Standard). A copy that carried it was reported to show a 'newer version, values replaced' "
    "notice naming it. Whether leaving it out removes that notice has not been confirmed in Snapmaker Orca, so check "
    "the opened copy in Orca. The original file is not changed.")
NOZZLE_VOLUME_TYPE_DECLARATION_REASON = "no longer declared: the setting it named was left out of the copy"


def _withdraw_declaration(cfg: dict, key: str, changes: list) -> None:
    """Take `key` out of every entry of `different_settings_to_system`, so a value that is gone is not still declared."""
    entries = cfg.get("different_settings_to_system")
    if not isinstance(entries, list):
        return
    new, touched = [], False
    for entry in entries:
        parts = [p.strip() for p in str(entry).split(";") if p.strip()]
        if key in parts:
            touched = True
            entry = ";".join(p for p in parts if p != key)
        new.append(entry)
    if touched:
        old = cfg["different_settings_to_system"]
        cfg["different_settings_to_system"] = new
        _change(changes, "different_settings_to_system", old, new, NOZZLE_VOLUME_TYPE_DECLARATION_REASON,
                f"The project declared {key} as a deviation from its presets. With the setting left out of the copy "
                "there is nothing left to declare.")


def _drop_foreign_nozzle_volume_type(cfg: dict, changes: list) -> None:
    """Leave out `nozzle_volume_type`, which Snapmaker Orca does not write.

    Measured on the committed fixtures: the Snapmaker Orca 2.3.5 and 2.3.6 projects have no such key; Bambu Studio
    2.08 and OrcaSlicer 2.4.2 projects carry it (also OrcaSlicer ones that name a U1), so it is not Bambu-only.
    Removing it makes the copy read like one Snapmaker Orca saved. OrcaSlicer-authored U1 files lose it too: nothing
    here shows Orca needs it, and the 'not confirmed in Snapmaker Orca' label stays on the change. A project without
    the key is left exactly as it was. Any declaration of the key is withdrawn with it."""
    if "nozzle_volume_type" not in cfg:
        return
    old = cfg.pop("nozzle_volume_type")
    _change(changes, "nozzle_volume_type", old, None, NOZZLE_VOLUME_TYPE_REASON, NOZZLE_VOLUME_TYPE_WHY)
    changes[-1]["removed"] = True
    _withdraw_declaration(cfg, "nozzle_volume_type", changes)


# --- entry points -----------------------------------------------------------

def apply_compatibility(cfg: dict, filament_count: int = 0) -> list[dict]:
    """Apply every Snapmaker Orca import fix to a project settings dict in place.

    Returns the list of changes, each with the old value, the new value, a short
    reason and a plain-language explanation. Runs in every prepare mode: these
    are compatibility corrections, not settings choices, so Preserve mode gets
    them too.
    """
    changes: list[dict] = []
    _enable_exclude_object(cfg, changes)
    _fix_auto_brim(cfg, changes)
    _fix_tree_support_with_adaptive_layers(cfg, changes)
    _fix_filament_array_validity(cfg, changes, filament_count)
    _fix_negative_raft_expansion(cfg, changes)
    _drop_foreign_nozzle_volume_type(cfg, changes)
    return changes


def is_slice_cache(part: str) -> bool:
    return (part.startswith(SLICE_CACHE_PREFIXES)
            and part.endswith(SLICE_CACHE_SUFFIXES)
            and not part.endswith(".png"))


def strip_slice_cache(tm) -> list[dict]:
    """Remove the authoring slicer's own sliced output from the project.

    Those toolpaths were generated for a different machine's kinematics, motion
    limits and tool changer. Left in place, Snapmaker Orca can show a preview
    built from them — a preview of a print that will never happen on this
    printer. Removing them forces an honest re-slice. Plate *images* are kept:
    they are how a person recognises their own project.
    """
    removed = []
    for part in list(tm.list_parts()):
        if is_slice_cache(part):
            tm.remove_part(part)
            removed.append({"part": part,
                            "reason": "sliced output from the original printer, "
                                      "removed so Snapmaker Orca re-slices for the U1"})
    return removed
