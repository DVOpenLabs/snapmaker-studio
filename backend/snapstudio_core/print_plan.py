"""What actually happens during this print, in order.

`gcode.read_facts` reads the ends of a file and reports what the slicer wrote
down. That answers "what is this job?" but not "what will the machine do, and
when?" — which is the question that matters for a multi-toolhead print, where a
job can look fine and still stop at layer 34 because the tool it switches to has
no filament in it.

This does a single streaming pass and builds a timeline of the events that are
*deterministically recoverable*: layer changes, tool changes, pauses and manual
filament changes, temperature targets, and object boundaries. It never simulates
motion, never estimates, and never invents an event the file does not contain.

**What an unsliced project cannot know, and what this narrows without fully
closing.** `color_plan` answers, from a project's own painted/assigned
colours, whether two colours *can* land on the same printed layer — proven
only when their height ranges cannot overlap; everywhere else it reserves a
toolhead rather than guess. That is the honest limit of reading a project:
heights overlapping shows two colours *can* meet on a layer, not that they
do. This module narrows that gap once the job is sliced, but does not close
it: it walks every tool-change line in order, so `tool_first_layer` and
`tool_last_layer` are the real layers a tool was *selected* on — carried
forward from the layer it was chosen on to every later layer until something
else is chosen, not only the exact layer a `T<n>` line appears on, since a
real slicer does not repeat a tool-change command for every layer that keeps
using the same tool. That much is a fact read straight off the G-code.

Whether two tools ever shared a single printed layer is a different, harder
question this scan deliberately does not answer. Multiple attempts at it were
tried and abandoned in this branch's history, each defeated by the same root
cause: a `T<n>` line proves the active tool changed, never that filament was
deposited before the next change, and no combination of *which* layers a
tool was selected on or *how many times* it changed within one layer can
tell a genuine same-layer multi-tool print apart from an ordinary sequential
handoff. A print where two tools alternate one clean switch per layer, each
extruding for the whole layer it owns, and a print where those same two
tools both extrude within *every* layer, produce IDENTICAL tool-change
traces — telling them apart needs to know where the extrusion moves
themselves fall relative to the tool-change and layer-change lines, which
this scan's line-level regex does not parse (see the Cost note below for
why: on a real multi-megabyte job, extrusion lines are most of the file, and
matching them the way `_TOOL`/`_LAYER` are matched here would cost real,
currently unmeasured, time). A slicer's own per-feature comments (Orca's
`;TYPE:` lines, for one) might narrow this more cheaply than parsing
extrusion moves, but that is a slicer convention rather than a fact every
job carries, and has not been tried. Reporting a guess either direction —
"safe to swap" or "needs a toolhead" — built on a trace that cannot
distinguish the two would be worse than not answering: color_plan's
pre-slice "reserve a toolhead" stays the honest answer for coexistence,
before AND after slicing, until this module reads more than tool-change and
layer-change lines.

**Cost.** A pass over a 330 MB job takes a few seconds, so this is deliberately
separate from the cheap facts: the Post-Slice Doctor answers immediately, and the
timeline is asked for. Memory stays flat regardless of file size — the file is
read in chunks and only the events are kept.

**Bounds.** The number of events kept is capped. A pathological file cannot make
Studio allocate without limit, and when the cap is hit the report says so rather
than silently truncating.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

SCHEMA_VERSION = "printplan/1"

CHUNK = 1 << 20            # 1 MiB reads; the regexes run over whole chunks


def _limit(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_EVENTS = _limit("SNAPSTUDIO_PLAN_MAX_EVENTS", 20_000)
MAX_BYTES = _limit("SNAPSTUDIO_PLAN_MAX_BYTES", 2 * 1024 * 1024 * 1024)

# Every pattern here matches a line a slicer actually writes. Nothing is inferred
# from motion commands.
_LAYER = re.compile(r"^(?:;LAYER_CHANGE|;LAYER:(\d+)|; CHANGE_LAYER)", re.M)
_LAYER_Z = re.compile(r"^;Z:([\d.]+)", re.M)
_STATS_LAYER = re.compile(r"^SET_PRINT_STATS_INFO .*CURRENT_LAYER=(\d+)", re.M)
_TOOL = re.compile(r"^T(\d{1,2})\s*$", re.M)
_PAUSE = re.compile(r"^(M600|M601|PAUSE|M25)\b", re.M)
_NOZZLE_TEMP = re.compile(r"^M10[49](?:\s+T(\d+))?\s+S([\d.]+)", re.M)
_BED_TEMP = re.compile(r"^M1[49]0\s+S([\d.]+)", re.M)
_FAN = re.compile(r"^M106(?:\s+P(\d+))?\s+S([\d.]+)", re.M)
_OBJECT_START = re.compile(r"^EXCLUDE_OBJECT_START", re.M)
_CUSTOM = re.compile(r"^;TYPE:Custom", re.M)


class _Cap(Exception):
    """Raised internally when the event budget is exhausted."""


def scan(path: str | Path) -> dict:
    """Stream a sliced job once and return its event timeline."""
    target = Path(path)
    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "available": False,
        "events": [],
        "truncated": False,
    }
    if not target.exists() or not target.is_file():
        out["error"] = "that file does not exist"
        return out

    size = target.stat().st_size
    if size > MAX_BYTES:
        out["error"] = (f"that file is {size / 1e9:.1f} GB, larger than Studio will scan "
                        f"({MAX_BYTES / 1e9:.1f} GB)")
        return out

    layer = 0
    z_by_layer: dict[int, float] = {}
    current_tool: int | None = None
    events: list[dict] = []
    tool_layers: dict[int, list[int]] = {}
    tool_changes = 0
    pauses = 0
    objects = 0
    bed_target: float | None = None
    nozzle_targets: dict[int, float] = {}
    truncated = False

    def add(kind: str, **fields):
        nonlocal truncated
        if len(events) >= MAX_EVENTS:
            truncated = True
            raise _Cap
        events.append({"layer": layer, "kind": kind, **fields})

    try:
        # Universal newlines on purpose: a job written on Windows ends its lines
        # with CR LF, and a stray CR would sit between the marker and the end of
        # the line, so every anchored pattern below would miss.
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            carry = ""
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                blob = carry + chunk
                # Keep the last partial line for the next round.
                cut = blob.rfind("\n")
                if cut == -1:
                    carry = blob
                    continue
                carry = blob[cut + 1:]
                blob = blob[:cut + 1]

                # Walk the interesting lines in order. Iterating matched lines is
                # far cheaper than splitting every line of a 330 MB file.
                for match in re.finditer(
                        r"^(?:;LAYER_CHANGE|;LAYER:\d+|; CHANGE_LAYER|;Z:[\d.]+|"
                        r"T\d{1,2}|M600|M601|PAUSE|M25|M10[49][^\n]*|M1[49]0[^\n]*|"
                        r"EXCLUDE_OBJECT_START[^\n]*|SET_PRINT_STATS_INFO[^\n]*)$",
                        blob, re.M):
                    line = match.group(0)

                    if line.startswith((";LAYER_CHANGE", "; CHANGE_LAYER")):
                        layer += 1
                        if current_tool is not None:
                            tool_layers.setdefault(current_tool, []).append(layer)
                        continue
                    if line.startswith(";LAYER:"):
                        layer = int(line.split(":", 1)[1] or 0)
                        if current_tool is not None:
                            tool_layers.setdefault(current_tool, []).append(layer)
                        continue
                    if line.startswith(";Z:"):
                        try:
                            z_by_layer[layer] = float(line[3:])
                        except ValueError:
                            pass
                        continue
                    if line.startswith("SET_PRINT_STATS_INFO"):
                        found = _STATS_LAYER.match(line)
                        if found:
                            layer = max(layer, int(found.group(1)))
                            if current_tool is not None:
                                tool_layers.setdefault(current_tool, []).append(layer)
                        continue

                    tool = _TOOL.match(line)
                    if tool:
                        index = int(tool.group(1))
                        if index != current_tool:
                            tool_changes += 1
                            add("tool", tool=index, previous=current_tool)
                            current_tool = index
                        tool_layers.setdefault(index, []).append(layer)
                        continue

                    if _PAUSE.match(line):
                        pauses += 1
                        add("pause", command=line.split()[0])
                        continue

                    nozzle = _NOZZLE_TEMP.match(line)
                    if nozzle:
                        index = int(nozzle.group(1)) if nozzle.group(1) else (current_tool or 0)
                        value = float(nozzle.group(2))
                        if nozzle_targets.get(index) != value:
                            nozzle_targets[index] = value
                            if value > 0:
                                add("nozzle_temp", tool=index, celsius=value)
                        continue

                    bed = _BED_TEMP.match(line)
                    if bed:
                        value = float(bed.group(1))
                        if bed_target != value:
                            bed_target = value
                            add("bed_temp", celsius=value)
                        continue

                    if line.startswith("EXCLUDE_OBJECT_START"):
                        objects += 1
                        continue
    except _Cap:
        pass
    except OSError as exc:
        out["error"] = f"could not read the file: {exc.strerror or exc}"
        return out

    first_tool = next((e["tool"] for e in events if e["kind"] == "tool"), None)
    last_tool = next((e["tool"] for e in reversed(events) if e["kind"] == "tool"), None)

    out.update({
        "available": True,
        "size_bytes": size,
        "layers_seen": layer,
        "events": events,
        "truncated": truncated,
        "tool_changes": tool_changes,
        "first_tool": first_tool,
        "last_tool": last_tool,
        "tools_seen": sorted(tool_layers),
        "tool_first_layer": {str(t): min(ls) for t, ls in tool_layers.items() if ls},
        "tool_last_layer": {str(t): max(ls) for t, ls in tool_layers.items() if ls},
        "pauses": pauses,
        "objects_started": objects,
        "bed_target_c": bed_target,
        "nozzle_targets_c": {str(k): v for k, v in nozzle_targets.items()},
        "z_by_layer": {str(k): v for k, v in list(z_by_layer.items())[:2000]},
    })
    return out


# --- plain language ---------------------------------------------------------

def _ordinal_layer(layer: int) -> str:
    return "before the first layer" if layer <= 0 else f"layer {layer}"


def narrate(plan: dict, facts: dict | None = None,
            loaded: list | None = None) -> list[dict]:
    """A short, ordered, plain-language account of the print.

    One line per thing that actually happens, with the G-code evidence kept
    alongside so an expert can check it. Repetitive tool changes are collapsed:
    a 400-change job produces a readable summary, not 400 lines.
    """
    if not plan.get("available"):
        return []

    def material_for(tool: int) -> str | None:
        if loaded and tool < len(loaded) and loaded[tool]:
            entry = loaded[tool]
            colour = entry.get("color")
            material = entry.get("material")
            return " ".join(x for x in (colour, material) if x) or None
        slots = (facts or {}).get("slots") or []
        for slot in slots:
            if slot.get("tool") == tool and slot.get("type"):
                return slot["type"]
        return None

    lines: list[dict] = []
    first = plan.get("first_tool")
    if first is not None:
        material = material_for(first)
        lines.append({
            "at": "Start",
            "text": f"Prints with slot {first + 1}" + (f", loaded with {material}" if material else ""),
            "evidence": f"T{first} before any layer change",
        })

    bed = plan.get("bed_target_c")
    if bed is not None:
        lines.append({
            "at": "Start",
            "text": (f"Heats the bed to {bed:g} °C" if bed > 0
                     else "Does not heat the bed — the job asks for 0 °C"),
            "evidence": f"M140 S{bed:g}",
        })

    # Tool introductions, in the order they first appear.
    introduced = sorted(
        ((int(tool), layer) for tool, layer in (plan.get("tool_first_layer") or {}).items()),
        key=lambda pair: pair[1])
    for tool, layer in introduced:
        if tool == first and layer <= 0:
            continue
        material = material_for(tool)
        lines.append({
            "at": _ordinal_layer(layer).capitalize(),
            "text": f"Slot {tool + 1} joins in" + (f" — {material}" if material else ""),
            "evidence": f"first T{tool} at layer {layer}",
        })

    # Tools that stop being used before the end — worth knowing, because the
    # spool can come out.
    layers_total = plan.get("layers_seen") or 0
    for tool, layer in sorted(
            ((int(t), l) for t, l in (plan.get("tool_last_layer") or {}).items()),
            key=lambda pair: pair[1]):
        if layers_total and layer < layers_total - 1 and len(introduced) > 1:
            lines.append({
                "at": _ordinal_layer(layer).capitalize(),
                "text": f"Slot {tool + 1} is finished with",
                # Not necessarily a literal T{tool} line at this layer: once a
                # tool is carried forward through every layer it stays
                # selected on, this is the last layer it was still the
                # selected tool for, which may be later than its last T-line.
                "evidence": f"T{tool} last selected through layer {layer}",
            })

    for event in plan.get("events", []):
        if event["kind"] == "pause":
            lines.append({
                "at": _ordinal_layer(event["layer"]).capitalize(),
                "text": "The print pauses and waits for you",
                "evidence": event.get("command", "pause command"),
            })

    changes = plan.get("tool_changes") or 0
    if changes > 1:
        lines.append({
            "at": "Throughout",
            "text": f"{changes} tool changes in total"
                    + (" — each one purges some filament" if changes > 1 else ""),
            "evidence": f"{changes} T commands that change the active tool",
        })

    if layers_total:
        lines.append({
            "at": "Finish",
            "text": f"{layers_total} layers"
                    + (f", ending on slot {plan['last_tool'] + 1}" if plan.get("last_tool") is not None else ""),
            "evidence": f"{layers_total} layer changes counted",
        })

    return lines


def summary(plan: dict) -> str:
    if not plan.get("available"):
        return plan.get("error", "Studio could not read that file.")
    bits = [f"{plan.get('layers_seen', 0)} layers"]
    tools = plan.get("tools_seen") or []
    if tools:
        bits.append(f"slot{'s' if len(tools) != 1 else ''} " +
                    ", ".join(str(t + 1) for t in tools))
    if plan.get("tool_changes"):
        bits.append(f"{plan['tool_changes']} tool change{'s' if plan['tool_changes'] != 1 else ''}")
    if plan.get("pauses"):
        bits.append(f"{plan['pauses']} pause{'s' if plan['pauses'] != 1 else ''}")
    text = ", ".join(bits) + "."
    if plan.get("truncated"):
        text += (f" Only the first {MAX_EVENTS:,} events were kept — this job has more "
                 "than Studio will hold in one report.")
    return text
