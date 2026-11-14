"""Notice the sliced job coming back, without watching the whole machine.

The workflow had one manual step left in it: after Snapmaker Orca sliced the
prepared copy, the user had to find the `.gcode` and hand it back to Studio. That
step is where the loop stopped feeling like one thing.

This closes it, deliberately narrowly:

* **One folder, chosen by the user.** Their slicer's export folder, picked once.
  Not the whole disk, not the home directory, and nothing is watched until they
  say so.
* **Polled, not daemonised.** The engine answers requests; it does not run
  background threads that touch the filesystem while nobody is looking. The app
  asks "anything new?" while the user is on the page that cares.
* **Only complete files.** A G-code file being written grows for as long as the
  slicer is exporting it. A candidate is offered only once its size has stopped
  changing and it ends the way a finished job ends.
* **Nothing leaves the machine**, and nothing is modified: this reads sizes,
  timestamps and file ends.

Which project a job belongs to is not decided here — `provenance.py` weighs that,
and an ambiguous answer is shown to the user rather than resolved by guessing.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

SCHEMA_VERSION = "watch/1"


def _limit(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


#: How many files to consider. A slicer's output folder can hold hundreds of old
#: jobs; the interesting ones are always the newest.
MAX_CANDIDATES = _limit("SNAPSTUDIO_WATCH_MAX", 12)

#: Ignore anything older than this. A job sliced last week is not the one that
#: just came out of Orca.
MAX_AGE_SECONDS = _limit("SNAPSTUDIO_WATCH_MAX_AGE", 24 * 60 * 60)

#: A file whose size changed within this window is still being written.
SETTLE_SECONDS = _limit("SNAPSTUDIO_WATCH_SETTLE", 2)

#: How much of the end of a file to read looking for a terminator.
TAIL_WINDOW = 64 * 1024

#: How many files to remember between polls. Only sizes and timestamps.
MAX_REMEMBERED = 256

SUFFIXES = (".gcode", ".gco", ".g")

#: Markers that only appear where a slicer *stops* writing. Deliberately not
#: "estimated printing time" or "total filament used": Snapmaker Orca writes both
#: inside the first few hundred kilobytes of a job, so a file that was cut off
#: early can contain them and would be offered as finished.
TERMINATORS = (
    "; CONFIG_BLOCK_END",           # Orca / Bambu / Snapmaker Orca
    "; prusaslicer_config = end",   # PrusaSlicer / SuperSlicer
    "; End of Gcode",
)

#: Markers that say which dialect a file is written in. An Orca-family job always
#: ends with its configuration block, so one of these without a terminator means
#: the file stopped before the end — even though the toolpaths, the summary and
#: `PRINT_END` are all already there.
DIALECT_MARKERS = ("; EXECUTABLE_BLOCK_END", "; CONFIG_BLOCK_START",
                   "; HEADER_BLOCK_END", "; prusaslicer_config = begin")

#: Weaker terminators, for flavours that write no configuration block at all.
FALLBACK_TERMINATORS = ("PRINT_END", "M2\n", "M30")

#: What Studio has seen before, so a second look can tell "settled" from "paused
#: mid-write" without blocking a request while it waits. Sizes and modification
#: times only — no contents, and nothing written to disk.
_OBSERVED: dict[str, tuple[int, float, float]] = {}


def forget() -> None:
    """Drop what previous polls observed. For tests, and for changing folder."""
    _OBSERVED.clear()


def _remember(key: str, size: int, modified: float, now: float) -> tuple[int, float, float] | None:
    previous = _OBSERVED.get(key)
    if previous is None or previous[0] != size or previous[1] != modified:
        if len(_OBSERVED) >= MAX_REMEMBERED:
            oldest = min(_OBSERVED, key=lambda k: _OBSERVED[k][2])
            _OBSERVED.pop(oldest, None)
        _OBSERVED[key] = (size, modified, now)
        return None
    return previous


def _looks_finished(path: Path, size: int, modified: float, now: float) -> tuple[bool, str]:
    """Has the slicer finished writing this?

    Three independent signals, because none of them is sufficient alone:

    * the file is not empty;
    * it has stopped changing — either its modification time is already older
      than the settle window, or a previous poll saw exactly this size and time;
    * and it *ends* the way a finished job ends. A slicer that is interrupted
      leaves a file that stops mid-toolpath, so the terminator is what separates
      "finished" from "stalled for a couple of seconds".

    Nothing here sleeps. A file that has only just appeared is reported as still
    being written and settles on the next poll, which keeps a folder of twelve
    jobs from costing twelve times the settle window on every request.
    """
    if size == 0:
        return False, "the file is empty"

    key = str(path)
    seen_before = _remember(key, size, modified, now)
    settled = (now - modified) >= SETTLE_SECONDS
    if not settled and seen_before is not None:
        settled = (now - seen_before[2]) >= SETTLE_SECONDS
    if not settled:
        return False, "still being written"

    try:
        with path.open("rb") as handle:
            magic = handle.read(2)
            handle.seek(max(0, size - TAIL_WINDOW))
            tail = handle.read(TAIL_WINDOW).decode("utf-8", errors="replace")
    except PermissionError:
        return False, "another program is holding this file open"
    except OSError as exc:
        return False, f"could not read the end of it: {exc.strerror or exc}"

    if magic == b"PK":
        # A project file renamed .gcode. Naming it is more useful than offering it
        # and letting every check downstream fail for no stated reason.
        return False, "this is a project file, not a sliced job"

    if tail.endswith("\x00" * 16):
        # A file the filesystem has reserved space for but not filled: the export
        # is under way, or it failed and left a hole.
        return False, "the end of the file has not been written yet"

    if any(marker in tail for marker in TERMINATORS):
        return True, "complete"

    # The weaker markers are only trustworthy in a flavour that writes no
    # configuration block at all. A file that shows itself to be one that does,
    # and has not closed it, stopped early — whatever else it contains.
    known_dialect = any(marker in tail for marker in DIALECT_MARKERS)
    if not known_dialect and any(marker in tail for marker in FALLBACK_TERMINATORS):
        return True, "complete"
    return False, ("the end of the file is missing — the slicer may still be writing it, "
                   "or it stopped part-way")


def _is_file(entry) -> bool:
    try:
        return entry.is_file()
    except OSError:
        return False


def scan(folder: str | Path, *, since: float | None = None,
         limit: int | None = None) -> dict:
    """List complete, recent sliced jobs in one folder. Never raises."""
    target = Path(folder) if folder else None
    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "available": False,
        "folder": str(target) if target else None,
        "candidates": [],
    }
    if not target:
        out["error"] = "no folder chosen"
        return out
    if not target.exists() or not target.is_dir():
        out["error"] = "that folder does not exist"
        return out

    cutoff = since if since is not None else time.time() - MAX_AGE_SECONDS
    try:
        # scandir rather than iterdir: it lists a folder of hundreds of old jobs
        # without a stat call each, and an entry that cannot be read is one entry
        # rather than the end of the scan.
        with os.scandir(target) as listing:
            entries = [Path(entry.path) for entry in listing
                       if Path(entry.path).suffix.lower() in SUFFIXES and _is_file(entry)]
    except OSError as exc:
        out["error"] = f"Studio could not read that folder: {exc.strerror or exc}"
        return out

    recent = []
    unreadable = 0
    for path in entries:
        try:
            stat = path.stat()
        except OSError:
            # A file that cannot be stat'ed — too long a path, a broken network
            # mount, no permission — is counted rather than silently dropped.
            unreadable += 1
            continue
        if stat.st_mtime < cutoff:
            continue
        recent.append((stat.st_mtime, stat.st_size, str(path), path, stat.st_mtime_ns))
    recent.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    now = time.time()
    out["available"] = True
    out["seen"] = len(entries)
    if unreadable:
        out["unreadable"] = unreadable
    for modified, size, _text, path, modified_ns in recent[:(limit or MAX_CANDIDATES)]:
        complete, why = _looks_finished(path, size, modified, now)
        out["candidates"].append({
            "path": str(path),
            "name": path.name,
            "size_bytes": size,
            "modified": modified,
            # Exact modification time as text (a JSON number would lose digits). Lets a caller
            # tell "the same file" from "rewritten" without reading it.
            "modified_ns": str(modified_ns),
            "age_seconds": int(max(0, now - modified)),
            "complete": complete,
            "state": why,
        })
    out["summary"] = _summary(out)
    return out


def match_project(folder: str | Path, project_path: str | None, *,
                  since: float | None = None, limit: int | None = None) -> dict:
    """Scan a folder and weigh each complete job against an open project."""
    from . import gcode, project_traits, provenance

    found = scan(folder, since=since, limit=limit)
    if not found.get("available"):
        return found

    traits = {}
    if project_path:
        try:
            traits = project_traits.extract(project_path)
        except Exception:
            traits = {}

    for candidate in found["candidates"]:
        if not candidate["complete"]:
            continue
        facts = gcode.read_facts(candidate["path"])
        candidate["job"] = {
            "slicer": facts.get("slicer"),
            "printer_model": facts.get("printer_model"),
            "layer_count": facts.get("layer_count"),
            "tools_used": facts.get("tools_used"),
            "total_g": (facts.get("filament") or {}).get("total_g"),
            "readable": facts.get("available", False),
        }
        if traits and facts.get("available"):
            candidate["provenance"] = provenance.compare(
                traits, facts,
                project_name=Path(project_path).name if project_path else None,
                gcode_name=candidate["name"])

    best = provenance.best_of(found["candidates"])
    found["best"] = best["path"] if best else None
    found["best_verdict"] = best["provenance"]["verdict"] if best else None
    found["summary"] = _summary(found)
    return found


def _summary(found: dict) -> str:
    candidates = found.get("candidates") or []
    if not candidates:
        return "Nothing new in that folder yet. Slice in Snapmaker Orca and it will appear here."
    complete = [c for c in candidates if c["complete"]]
    writing = [c for c in candidates if not c["complete"]]
    if found.get("best"):
        name = next((c["name"] for c in candidates if c["path"] == found["best"]), "")
        verdict = found.get("best_verdict")
        word = "is" if verdict == "confirmed" else "looks like"
        return f"{name} {word} the sliced version of your project."
    bits = []
    if complete:
        bits.append(f"{len(complete)} finished job(s)")
    if writing:
        bits.append(f"{len(writing)} still being written")
    text = " and ".join(bits)
    return (text[:1].upper() + text[1:] +
            ". None of them could be tied to your project, so pick the right one yourself.")
