"""The settings receipt: what the project asked for, what Studio prepared, what the slice recorded.

Three files carry the same few settings: the project that came in (original), the
copy Studio prepared from it (prepared), and the G-code the slicer produced
(sliced). This reads the declared value of each setting from each file and compares
them step by step, so a slice that quietly used other nozzles, another layer height
or no supports is visible without a printer connected.

What it is, and is not:

* **Settings only.** It does not say the G-code is the project's slice (that is
  provenance), that the profile fits the printer, or that the print will work.
* **Declared values.** A G-code config block is what the slicer recorded; the
  project and prepared copy hold what they declare. Nothing is measured.
* **Unknown stays unknown.** A field a file does not state is `missing`, never
  "off", never "equal". A file that could not be read is `not_checked`.
* **Per-tool order matters.** Nozzle diameters are compared tool by tool, never as
  a set.
* **Whole project.** Settings are compared as the project's own, not plate by plate;
  the scope note says so rather than pretending otherwise.
* **Prime tower: the declared on/off flag only.** Where a tower sits, how big it is,
  and whether it fits are not inferred here.

Read-only. It never prepares, slices, sends or writes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA_VERSION = "settings-receipt/1"

STAGES = ("original", "prepared", "sliced")

SETTINGS_PART = "Metadata/project_settings.config"
MODEL_SETTINGS_PART = "Metadata/model_settings.config"

_TOLERANCE = 1e-6

SEPARATE_FROM = (
    "This compares settings only. It does not say the G-code is your project (see "
    "“Is this your project?”), that the slicer profile fits your printer, or that "
    "the print will succeed.")

#: The facts compared, in the order they are shown.
FACTS = (
    ("nozzles", "Nozzle diameter per tool"),
    ("layer_height", "Layer height"),
    ("supports", "Supports"),
    ("prime_tower", "Prime tower (declared on/off only)"),
)


# --- reading declared values ---------------------------------------------------

def _floats(raw) -> list[float] | None:
    """A list of numbers from a declared value, or None if any entry is not a number."""
    if raw is None:
        return None
    items = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
    out = []
    for item in items:
        try:
            out.append(float(str(item).strip()))
        except ValueError:
            return None
    return out or None


def _one_float(raw) -> float | None:
    if isinstance(raw, list):
        if len(raw) != 1:
            return None
        raw = raw[0]
    values = _floats(raw)
    return values[0] if values and len(values) == 1 else None


def _flag(raw) -> bool | None:
    if isinstance(raw, list):
        if len(raw) != 1:
            return None
        raw = raw[0]
    text = str(raw).strip().lower() if raw is not None else ""
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    return None


def _declared(config: dict) -> dict:
    return {
        "nozzles": _floats(config.get("nozzle_diameter")),
        "layer_height": _one_float(config.get("layer_height")),
        "supports": _flag(config.get("enable_support")),
        "prime_tower": _flag(config.get("enable_prime_tower")),
    }


def _read_project(path: str) -> dict:
    """The declared settings of a project file, or why they could not be read."""
    low = path.lower()
    if low.endswith(".stl"):
        if not Path(path).is_file():
            return {"state": "unreadable", "reason": "that file does not exist"}
        return {"state": "read", "values": _declared({}), "note": "An STL carries no print settings."}
    try:
        from .container import ThreeMF
        tm = ThreeMF.open(path)
        parts = set(tm.list_parts())
        config: dict = {}
        if SETTINGS_PART in parts:
            loaded = json.loads(tm.read_part(SETTINGS_PART).decode("utf-8", "ignore"))
            config = loaded if isinstance(loaded, dict) else {}
        plates = 0
        if MODEL_SETTINGS_PART in parts:
            plates = len(re.findall(r"<plate\b", tm.read_part(MODEL_SETTINGS_PART).decode("utf-8", "ignore")))
    except Exception as exc:  # any unreadable archive is "not checked", never a crash
        return {"state": "unreadable", "reason": exc.__class__.__name__}
    return {"state": "read", "values": _declared(config), "plates": plates}


def _read_gcode(path: str) -> dict:
    from . import gcode
    facts = gcode.read_facts(path)
    if not facts.get("available"):
        return {"state": "unreadable", "reason": facts.get("error") or "not a readable G-code file"}
    config = facts.get("config") or {}
    values = _declared(config)
    # The reader already parsed these two; prefer its numbers over re-parsing text.
    values["nozzles"] = facts.get("nozzle_diameter_mm") or values["nozzles"]
    if facts.get("layer_height_mm") is not None:
        values["layer_height"] = facts["layer_height_mm"]
    return {"state": "read", "values": values}


# --- comparing -----------------------------------------------------------------

def _mm(v: float) -> str:
    return f"{v:g} mm"


def _show(fact_id: str, value) -> str:
    if value is None:
        return "not stated"
    if fact_id == "nozzles":
        return ", ".join(_mm(v) for v in value)
    if fact_id == "layer_height":
        return _mm(value)
    return "on" if value else "off"


def _equal(fact_id: str, a, b) -> bool:
    if fact_id == "nozzles":
        return len(a) == len(b) and all(abs(x - y) <= _TOLERANCE for x, y in zip(a, b))
    if fact_id == "layer_height":
        return abs(a - b) <= _TOLERANCE
    return a == b


def _difference(fact_id: str, a, b) -> str:
    if fact_id == "nozzles":
        if len(a) != len(b):
            return f"{len(a)} tools became {len(b)} tools ({_show(fact_id, a)} → {_show(fact_id, b)})"
        return "; ".join(f"Tool {i + 1}: {_mm(x)} → {_mm(y)}"
                         for i, (x, y) in enumerate(zip(a, b)) if abs(x - y) > _TOLERANCE)
    return f"{_show(fact_id, a)} → {_show(fact_id, b)}"


_LABEL = {"original": "the project", "prepared": "the prepared copy", "sliced": "the slice"}

_WHAT = {
    "nozzles": "nozzle diameter",
    "layer_height": "layer height",
    "supports": "supports setting",
    "prime_tower": "prime tower setting",
}


def _advice(fact_id: str, a, b, frm: str, to: str) -> tuple[str, str]:
    """(consequence, next action) for a real change between two stages."""
    slicer = to == "sliced"
    if fact_id == "nozzles":
        why = ("Extrusion widths and flow are worked out from the nozzle, so the result no longer matches what the "
               "project was set up for.")
        act = ("Check the printer profile in Snapmaker Orca lists the nozzles your U1 actually has, then slice the "
               "prepared copy again and open the new G-code here." if slicer else
               "Open the prepared copy in Snapmaker Orca and confirm the nozzles are the ones you intend.")
    elif fact_id == "layer_height":
        why = "Layer count, print time and surface detail all follow from layer height."
        act = ("In Snapmaker Orca, set the layer height in the process profile to the value you want, slice again and "
               "open the new G-code here." if slicer else
               "Open the prepared copy in Snapmaker Orca and confirm the layer height before slicing.")
    elif fact_id == "supports":
        turned_off = bool(a) and not b
        why = ("Overhangs the project expected to be supported are not supported in the slice." if turned_off else
               "The slice adds support material the project did not ask for, which changes material use and time.")
        act = (f"In Snapmaker Orca, turn supports {'on' if turned_off else 'off'} in the process profile, slice again "
               "and open the new G-code here." if slicer else
               "Open the prepared copy in Snapmaker Orca and confirm the supports setting before slicing.")
    else:
        why = "Whether a prime tower is built changes how colour changes are handled and how much material is used."
        act = ("In Snapmaker Orca, check the prime tower setting in the process profile, slice again and open the new "
               "G-code here." if slicer else
               "Open the prepared copy in Snapmaker Orca and confirm the prime tower setting before slicing.")
    return why, act


def _step(fact_id: str, frm: str, to: str, stages: dict) -> dict:
    sa, sb = stages[frm], stages[to]
    out = {"from": frm, "to": to, "from_value": None, "to_value": None, "status": "not_checked",
           "detail": "", "next_action": None}
    for name, stage in ((frm, sa), (to, sb)):
        if stage["state"] != "read":
            out["detail"] = f"Studio could not read {_LABEL[name]}, so this step was not checked."
            out["next_action"] = f"Make sure {_LABEL[name]} is still where it was and opens, then check again."
            return out
    a, b = sa["values"][fact_id], sb["values"][fact_id]
    out["from_value"], out["to_value"] = a, b
    if a is None or b is None:
        gap = frm if a is None else to
        verb = "does not state" if gap != "sliced" else "does not record"
        out["status"] = "missing"
        out["detail"] = (f"{_LABEL[gap].capitalize()} {verb} a {_WHAT[fact_id]}, so Studio cannot say whether it "
                         f"matches ({_show(fact_id, a)} vs {_show(fact_id, b)}).")
        out["next_action"] = ("Check this setting in Snapmaker Orca directly; Studio will not assume it is the same."
                              if gap == "sliced" else
                              "Set it explicitly in the project so there is a value to compare.")
        return out
    if _equal(fact_id, a, b):
        out["status"] = "unchanged"
        out["detail"] = f"Same in {_LABEL[frm]} and {_LABEL[to]}: {_show(fact_id, b)}."
        return out
    out["status"] = "changed"
    why, act = _advice(fact_id, a, b, frm, to)
    who = "Studio’s prepared copy differs from the project" if to == "prepared" else \
        f"{_LABEL[to].capitalize()} differs from {_LABEL[frm]}"
    out["detail"] = f"{who}: {_difference(fact_id, a, b)}. {why}"
    out["next_action"] = act
    return out


_RANK = {"changed": 3, "missing": 2, "not_checked": 1, "unchanged": 0}


def compare(original_path: str, prepared_path: str | None, sliced_path: str | None) -> dict:
    """Compare the declared settings of the original, the prepared copy and the sliced G-code."""
    stages: dict[str, dict] = {}
    stages["original"] = _read_project(original_path)
    stages["prepared"] = _read_project(prepared_path) if prepared_path else {"state": "not_provided"}
    stages["sliced"] = _read_gcode(sliced_path) if sliced_path else {"state": "not_provided"}

    present = [s for s in STAGES if stages[s]["state"] != "not_provided"]
    pairs = list(zip(present, present[1:]))

    facts = []
    for fact_id, label in FACTS:
        steps = [_step(fact_id, a, b, stages) for a, b in pairs]
        if not steps:
            status = "not_checked"
        else:
            status = max((s["status"] for s in steps), key=lambda v: _RANK[v])
        facts.append({"id": fact_id, "label": label, "status": status, "steps": steps})

    plates = stages["original"].get("plates", 0)
    scope_note = ("Compared as whole-project settings; per-plate and per-object overrides are not compared. "
                  + (f"This project has {plates} plates and the G-code is one plate’s slice; Studio does not "
                     "know which." if plates > 1 else "A G-code is one plate’s slice."))
    counts = {k: sum(1 for f in facts if f["status"] == k) for k in _RANK}
    summary = (f"{counts['changed']} changed, {counts['missing']} missing, {counts['not_checked']} not checked, "
               f"{counts['unchanged']} unchanged.")
    return {"schema_version": SCHEMA_VERSION, "scope": "project", "scope_note": scope_note,
            "stages": stages, "facts": facts, "summary": summary, "separate_from": SEPARATE_FROM}
