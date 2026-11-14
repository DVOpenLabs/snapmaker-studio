"""Telling Snapmaker Orca which process values this project does not inherit.

A project names a process preset in `print_settings_id` and then lists ~130 of
that preset's values inline. Studio assumed the inline values were the ones that
would be used. They are not.

Measured on Snapmaker Orca 2.3.6 by writing one value into an otherwise
byte-identical project, opening it and reading the project Orca saved back:

| project_settings said | Orca kept |
|---|---|
| `layer_height="0.28"`, deviation **declared** | **0.28** |
| `layer_height="0.28"`, deviation **not declared** | **0.2** — the preset's value |

The declaration is `different_settings_to_system`, and its shape is Orca's own.
Changing three values through Orca's own Global process panel and asking it to
Save Project As produced:

    "different_settings_to_system": [
        "initial_layer_print_height;layer_height;seam_gap", "", "", "", "", ""
    ]

So: entry 0 is the **process** preset's deviations, semicolon-joined and sorted;
the remaining entries belong to the filaments and the printer. The list Orca
wrote was six long for a four-filament project and seven long for a five-filament
one — one entry for the process, one per filament, one for the printer.

## Why this module exists rather than a comment

`u1_identity.normalize_presets` blanks every entry to clear Orca's "Customized
Preset" notice, and its comment said *"the customized values themselves stay in
the project (intent preserved)"*. That was measured to be false: blanking the
declaration is what makes Orca throw the values away. A project whose settings
were normalised for a clean import was silently getting the stock preset.

So the notice and the values are the same switch. Studio may have one or the
other, and the values are the project. What this module does is make the
declaration true: exactly the keys that deviate, and nothing else, so a project
that deviates in nothing still imports without a notice.
"""
from __future__ import annotations

#: Where in the list each preset's deviations live. Entry 0 is the process
#: preset; entries 1..N are the filaments, one each, in slot order; the **last**
#: entry is the printer.
#:
#: Measured by declaring a key in each place. `nozzle_temperature` named in entry
#: 0 was ignored and the value reset from 230 to 215; the same key named in the
#: filament entries was kept at 230. `nozzle_type` left undeclared was reset from
#: `stainless_steel` to the preset's `hardened_steel`; named in the last entry it
#: was kept, and so were sentinel comments injected into `machine_start_gcode`
#: and `machine_end_gcode` — which reached the exported G-code, so the printer
#: entry decides what the machine actually runs.
PROCESS = 0
FIRST_FILAMENT = 1
PRINTER = -1

#: How Orca joins several deviating keys in one entry.
SEPARATOR = ";"


def _entries(existing, filaments: int) -> list[str]:
    """The list to write, the length Orca writes for this many filaments.

    One entry for the process preset, one per filament, one for the printer —
    six for four filaments, seven for five, which is what Orca wrote when it was
    asked to save each of those projects.
    """
    size = max(2, int(filaments or 0) + 2)
    out = [""] * size
    if isinstance(existing, list):
        for index, value in enumerate(existing[:size]):
            out[index] = str(value or "")
    elif isinstance(existing, str) and existing:
        out[PROCESS] = existing
    return out


def declared_process_keys(cfg: dict) -> set[str]:
    """The process keys a project already declares as deviating."""
    existing = (cfg or {}).get("different_settings_to_system")
    if isinstance(existing, list) and existing:
        first = str(existing[PROCESS] or "")
    elif isinstance(existing, str):
        first = existing
    else:
        return set()
    return {part.strip() for part in first.split(SEPARATOR) if part.strip()}


#: Keys the printer preset owns, which a project must declare in the printer
#: entry or not at all. Measured: `nozzle_type` declared anywhere else was
#: ignored and the value reset. This is deliberately short — it names only what
#: Studio has measured, and a key not on it is declared in the process entry,
#: where an unrecognised name costs nothing.
PRINTER_KEYS = frozenset({
    "machine_start_gcode", "machine_end_gcode", "layer_change_gcode",
    "machine_pause_gcode", "change_filament_gcode", "template_custom_gcode",
    "nozzle_type", "nozzle_diameter", "printer_settings_id", "printer_model",
    "printer_variant", "default_print_profile", "default_filament_profile",
    "printable_area", "printable_height", "extruder_offset",
})


def _split(keys) -> tuple[set[str], set[str], set[str]]:
    """Which of these belong to the process, the filaments and the printer.

    A key declared in the wrong entry is simply ignored — measured in all three
    directions — so this split is what makes the declaration work rather than
    merely be harmless. `PER_FILAMENT_KEYS` is Studio's own list of the keys that
    are one value per filament slot.
    """
    from .filaments import PER_FILAMENT_KEYS

    filament, printer, process = set(), set(), set()
    for key in keys:
        if key in PER_FILAMENT_KEYS:
            filament.add(key)
        elif key in PRINTER_KEYS:
            printer.add(key)
        else:
            process.add(key)
    return process, filament, printer


def declare(cfg: dict, keys, filaments: int = 4) -> dict | None:
    """State that `keys` do not come from the presets the project names.

    Returns a change record, or None when there was nothing to add. Keys already
    declared are kept: a value the source deviated on and Studio did not touch is
    still a deviation.

    Nothing is invented. If `keys` is empty and the project declares nothing, the
    project keeps declaring nothing and imports without a notice — which is the
    common case, and the reason this is a declaration rather than a flag.

    A key Orca does not recognise costs nothing: handed an invented name it kept
    the real deviations and dropped the invented one from what it wrote back. So
    a key Studio changed is declared even where Studio cannot say which preset
    owns it.
    """
    wanted = {str(k) for k in (keys or []) if str(k)}
    if not wanted and not declared_process_keys(cfg):
        return None
    before = cfg.get("different_settings_to_system")
    entries = _entries(before, filaments)
    process, filament, printer = _split(wanted)

    combined = sorted(declared_process_keys(cfg) | process)
    entries[PROCESS] = SEPARATOR.join(combined)

    if filament:
        slots = range(FIRST_FILAMENT, min(len(entries) - 1,
                                          FIRST_FILAMENT + max(1, int(filaments or 0))))
        for index in slots:
            existing = {p.strip() for p in str(entries[index] or "").split(SEPARATOR) if p.strip()}
            entries[index] = SEPARATOR.join(sorted(existing | filament))

    if printer:
        existing = {p.strip() for p in str(entries[PRINTER] or "").split(SEPARATOR) if p.strip()}
        entries[PRINTER] = SEPARATOR.join(sorted(existing | printer))

    if entries == before:
        return None
    cfg["different_settings_to_system"] = entries
    return {
        "key": "different_settings_to_system",
        "old": before,
        "new": entries,
        "reason": ("declared to Snapmaker Orca, which resets an undeclared value "
                   "to the preset it names"),
        "process_keys": combined,
        "filament_keys": sorted(filament),
        "printer_keys": sorted(printer),
    }


def keys_from_changes(*change_lists) -> set[str]:
    """Every project-settings key Studio changed, from its own change records.

    Studio already writes down what it changed and why; this reads that back
    rather than diffing against a copy of Orca's preset files, which would be a
    second thing to keep in step with Orca's releases.
    """
    out: set[str] = set()
    for changes in change_lists:
        for entry in changes or ():
            if isinstance(entry, dict):
                key = entry.get("key")
                if entry.get("removed"):
                    continue          # a key taken out of the project has nothing left to declare
                if key and key != "different_settings_to_system":
                    out.add(str(key))
    return out
