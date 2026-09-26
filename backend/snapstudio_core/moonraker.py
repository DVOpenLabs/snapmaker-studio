"""Printer Hub — the Moonraker client.

The Snapmaker U1 runs stock Moonraker on :7125, LAN-trusted (no auth), mDNS
`U1.local` (see docs/design/PRINTER_HUB.md). Everything above the control section
below is read-only: discover, connect, and read status / temperatures / toolheads
/ print state / history / capabilities.

**The split, and why the file is ordered this way.** Everything down to
`capabilities()` issues GET only and cannot change a machine. Below the CONTROL
banner are the functions that can — pause, resume, cancel, start, emergency stop
and `upload_gcode` — and each of them exists only to serve an explicit,
user-confirmed action in the UI. Nothing there runs on a timer, automatically, or
as a side effect of monitoring, and Studio never starts a print by itself.

`upload_gcode` is the only thing Studio sends anywhere. It goes to a printer whose
address the user supplied, on their own network. There is no other destination and
no cloud.
"""
from __future__ import annotations
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PORT = 7125
SCHEMA_VERSION = "printer/1"

# Klipper names its extruders `extruder`, then `extruder1` upward. Moonraker omits
# any object a query asks for and the printer does not have, so asking for more
# than exist is harmless — but asking for a fixed four means a machine with more
# than four is silently truncated, and a single-extruder machine is described by a
# list written for the U1. `status()` derives the list from the printer's own
# object list when it has one, and falls back to this only when it does not.
_TOOLHEAD_OBJECTS = ["extruder", "extruder1", "extruder2", "extruder3"]


def toolhead_objects(count: int | None = None) -> list[str]:
    """The Klipper extruder object names for a printer with `count` tools."""
    if not count or int(count) < 1:
        return list(_TOOLHEAD_OBJECTS)
    n = int(count)
    return ["extruder"] + [f"extruder{i}" for i in range(1, n)]

# A printer address is a bare hostname / mDNS name / IPv4, or a bracketed IPv6
# literal. The host is interpolated straight into a URL, so anything carrying a
# scheme, credentials, path, query or whitespace would let a saved setting point
# Studio at a different server than the one the user thinks they configured.
_HOSTNAME_RE = re.compile(r"\A(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?\Z")
_IPV6_RE = re.compile(r"\A\[[0-9A-Fa-f:.]{2,45}\]\Z")


class InvalidHost(ValueError):
    """A printer address Studio will not turn into a request URL."""


def validate_host(host: str) -> str:
    """Return the normalized host, or raise InvalidHost.

    Accepts `u1.local`, `192.168.1.50`, `[fe80::1]`. Rejects `http://x`,
    `evil.com/path`, `user@host`, empty strings and anything with whitespace.
    """
    h = (host or "").strip()
    if not h or len(h) > 255:
        raise InvalidHost("Enter the printer's IP address or hostname.")
    if _IPV6_RE.match(h):
        return h
    if not _HOSTNAME_RE.match(h):
        raise InvalidHost(
            "That doesn't look like a printer address. Use the IP address shown "
            "on the printer (for example 192.168.1.50) or a name like u1.local."
        )
    return h


def _url(host: str, port: int, path: str) -> str:
    """Build a Moonraker URL from a validated host. Never accepts a full URL."""
    return f"http://{validate_host(host)}:{int(port)}{path}"


# A printer status response is a few kilobytes; the largest thing Moonraker
# returns here is a Klipper object list. A LAN host that streams more than this is
# either broken or hostile, and the 3MF reader is already careful about exactly
# this, so the network path should be too.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class PrinterUnavailable(Exception):
    """Studio could not ask the printer, as distinct from the printer answering.

    The difference matters everywhere it is reported: "your printer does not
    support this" and "Studio could not reach your printer just now" send a person
    to two different places, and only one of them is about their machine.
    """


def _get(host: str, port: int, path: str, timeout: float) -> dict:
    """Read-only HTTP GET against Moonraker. Raises on failure.

    Retried once when the machine cannot open the socket at all. Studio polls a
    printer every few seconds, and on a machine short of ephemeral ports — one
    here had 14,000 held open by Docker Desktop — that fails intermittently for a
    reason that has nothing to do with the printer. One quick retry turns a
    spurious "your printer stopped answering" into a small pause. A refusal from
    the printer itself is not retried: that is an answer.
    """
    req = urllib.request.Request(_url(host, port, path), method="GET")  # explicit: never anything but GET
    attempts = 3
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(MAX_RESPONSE_BYTES + 1)
            break
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("the printer sent more data than Studio will read")
    return json.loads(raw)


def probe(host: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> dict:
    """Connect check via GET /server/info. Never raises — reports reachability."""
    try:
        res = _get(host, port, "/server/info", timeout).get("result", {})
        return {
            "reachable": True, "host": host, "port": port,
            "klippy_state": res.get("klippy_state"),
            "moonraker_version": res.get("moonraker_version"),
            "api_version": res.get("api_version_string"),
        }
    except Exception as e:
        return {"reachable": False, "host": host, "port": port, "error": str(e)}


# The U1 answers Moonraker on two ports: the Klipper-standard socket on 7125, and
# the on-device nginx proxy on 80 (the same address the built-in Fluidd UI uses).
# Which one is open varies with firmware build and whether the owner has turned on
# Advanced Mode, so discovery tries both rather than assuming one.
#
# The :80 behaviour is documented in the README of U1 Print Hub
# (https://github.com/dlgambill/u1hub, MIT) — a fact about the printer rather than
# any of its code, but worth crediting where it was learned. See
# THIRD_PARTY_NOTICES.md.
CANDIDATE_PORTS = (DEFAULT_PORT, 80)

# What to tell someone when nothing answers. The U1's web/Moonraker interface is
# gated behind a setting on the printer's own touchscreen, so "not found" is far
# more often "the switch is off" than "the network is broken". Saying that is the
# difference between a dead end and a fix.
NOT_FOUND_HINT = (
    "No printer answered. On the U1 touchscreen open Settings → Maintenance and "
    "turn on Advanced Mode — that is what opens the printer's network interface. "
    "Then check the IP address shown there and enter it here."
)

# The hint above is advice about a U1, and it is the right advice while Studio is
# looking for one at the U1's own hostnames. It is the wrong advice about an
# address a person typed, because Studio does not know what is at that address
# and telling someone to go and change a setting on a machine they may not own is
# a guess dressed as instruction.
GENERIC_NOT_FOUND_HINT = (
    "Nothing answered Moonraker at that address. Check the printer is powered on "
    "and on this network, and that the address and port are the ones it shows. If "
    "it is a Snapmaker U1, its network interface only opens once Advanced Mode is "
    "turned on under Settings → Maintenance on the touchscreen."
)


def not_found_hint(host: str | None = None, searched_defaults: bool = False) -> str:
    """What to tell someone when nothing answered, without assuming their machine."""
    return NOT_FOUND_HINT if searched_defaults else GENERIC_NOT_FOUND_HINT


def discover(hosts: list[str] | None = None, port: int | None = None,
             timeout: float = 1.5) -> list[dict]:
    """Probe candidate hosts for a Moonraker printer. Read-only.

    This is **transport discovery** and nothing else: it answers "is something
    speaking Moonraker at this address", which is a different question from "what
    printer is this". Identification is
    :func:`snapstudio_core.printer_profiles.identify`, and it runs on what the
    machine reports once it has answered. Keeping the two apart is what stops
    Studio from calling every Moonraker host a U1, and from calling a machine that
    did not answer "not a U1" when all it did was not answer.

    With no hosts given, the shipped profiles' own default hostnames are tried —
    today only the U1 publishes any. Studio does not scan the network: a printer
    that publishes no discoverable name is reached by typing its address, which is
    a supported way to connect and not a degraded one.

    Returns one entry per host: the first port that answered, or the last failure
    for that host so the caller can show a real reason. Passing an explicit `port`
    checks only that port (used when the user typed one).
    """
    searched_defaults = not hosts
    candidates = hosts or default_hostnames()
    ports = (port,) if port else CANDIDATE_PORTS
    hint = not_found_hint(searched_defaults=searched_defaults)
    out: list[dict] = []
    for h in candidates:
        last: dict | None = None
        for p in ports:
            res = probe(h, p, timeout)
            if res.get("reachable"):
                last = res
                break
            last = res
        if last is not None and not last.get("reachable"):
            last["hint"] = hint
        out.append(last or {"reachable": False, "host": h, "hint": hint})
    return out


def default_hostnames() -> list[str]:
    """Hostnames the shipped printer profiles say their machines publish."""
    from . import printer_profiles

    names: list[str] = []
    for profile in printer_profiles.load_all():
        for name in (profile.get("identity") or {}).get("default_hostnames") or ():
            if name not in names:
                names.append(name)
    return names or ["U1.local", "snapmaker-u1.local"]


def status(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0,
           tool_count: int | None = None) -> dict:
    """Read-only live status: print state, progress, layers, bed + per-toolhead
    temperatures, live message and motion factors.

    `tool_count`, when the caller already knows it from the printer's object list,
    makes the temperature channels follow the machine rather than a list sized for
    a four-toolhead U1.

    GET /printer/objects/query only — no subscriptions are persisted, nothing written."""
    heads = toolhead_objects(tool_count)
    objs = "&".join(["print_stats", "heater_bed", "toolhead", "virtual_sdcard",
                     "display_status", "gcode_move", *heads])
    st = _get(host, port, "/printer/objects/query?" + objs, timeout).get("result", {}).get("status", {})
    ps = st.get("print_stats", {}) or {}
    bed = st.get("heater_bed", {}) or {}
    vsd = st.get("virtual_sdcard", {}) or {}
    disp = st.get("display_status", {}) or {}
    gmove = st.get("gcode_move", {}) or {}
    info = ps.get("info", {}) or {}
    toolheads = []
    for i, key in enumerate(heads):
        e = st.get(key)
        if isinstance(e, dict):
            toolheads.append({
                "index": i,
                "temperature": e.get("temperature"),
                "target": e.get("target"),
                "active": bool(e.get("target")),  # heating/holding => in use this job
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "host": host, "port": port,
        "print_state": ps.get("state"),
        "filename": ps.get("filename") or None,
        "message": disp.get("message") or None,
        "progress": vsd.get("progress") if vsd.get("progress") is not None else disp.get("progress"),
        "print_duration_s": ps.get("print_duration"),
        "total_duration_s": ps.get("total_duration"),
        "filament_used_mm": ps.get("filament_used"),
        "current_layer": info.get("current_layer"),
        "total_layer": info.get("total_layer"),
        "speed_factor": gmove.get("speed_factor"),
        "extrude_factor": gmove.get("extrude_factor"),
        "bed": {"temperature": bed.get("temperature"), "target": bed.get("target")},
        "toolheads": toolheads,
    }


def _job_brief(j: dict) -> dict:
    return {
        "filename": j.get("filename"),
        "status": j.get("status"),
        "start_time": j.get("start_time"),
        "end_time": j.get("end_time"),
        "print_duration_s": j.get("print_duration"),
        "total_duration_s": j.get("total_duration"),
        "filament_used_mm": j.get("filament_used"),
    }


# Moonraker [history] job statuses that mean the print did not finish cleanly.
_FAILURE_STATES = {"error", "cancelled", "klippy_shutdown", "klippy_disconnect", "interrupted"}


def history(host: str, port: int = DEFAULT_PORT, limit: int = 20, timeout: float = 4.0) -> dict:
    """Read-only print history + failure observation via Moonraker [history].
    GET /server/history/list + /server/history/totals only."""
    listing = _get(host, port, f"/server/history/list?limit={int(limit)}&order=desc",
                   timeout).get("result", {})
    jobs = [_job_brief(j) for j in (listing.get("jobs") or [])]
    totals = _get(host, port, "/server/history/totals", timeout).get("result", {}).get("job_totals", {}) or {}
    failures = [j for j in jobs if (j.get("status") in _FAILURE_STATES)]
    return {
        "schema_version": SCHEMA_VERSION,
        "host": host, "port": port,
        "jobs": jobs,
        "failures": failures,
        "totals": {
            "total_jobs": totals.get("total_jobs"),
            "total_print_time_s": totals.get("total_print_time"),
            "total_time_s": totals.get("total_time"),
            "total_filament_used_mm": totals.get("total_filament_used"),
            "longest_print_s": totals.get("longest_print"),
        },
    }


def file_metadata(host: str, filename: str, port: int = DEFAULT_PORT, timeout: float = 4.0) -> dict:
    """Read-only gcode metadata the printer already extracted for a file — the slicer's
    OWN estimate (print time, filament grams/mm, layers, slicer, first-layer temps).
    GET /server/files/metadata only. This is data Studio otherwise can't have without
    slicing; here it's read straight from the open Moonraker stack.

    `available: False` (never raises) when the file isn't on the printer / has no metadata."""
    try:
        from urllib.parse import quote
        res = _get(host, port, "/server/files/metadata?filename=" + quote(filename), timeout).get("result", {}) or {}
    except Exception as e:
        return {"schema_version": SCHEMA_VERSION, "available": False, "filename": filename, "reason": str(e)}
    if not res:
        return {"schema_version": SCHEMA_VERSION, "available": False, "filename": filename}
    thumbs = res.get("thumbnails") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "filename": res.get("filename") or filename,
        "estimated_time_s": res.get("estimated_time"),
        "filament_total_mm": res.get("filament_total"),
        "filament_weight_g": res.get("filament_weight_total"),
        "filament_name": res.get("filament_name"),
        "filament_type": res.get("filament_type"),
        "layer_count": res.get("layer_count"),
        "layer_height": res.get("layer_height"),
        "first_layer_height": res.get("first_layer_height"),
        "object_height": res.get("object_height"),
        "first_layer_bed_temp": res.get("first_layer_bed_temp"),
        "first_layer_extr_temp": res.get("first_layer_extr_temp"),
        "nozzle_diameter": res.get("nozzle_diameter"),
        "slicer": res.get("slicer"),
        "slicer_version": res.get("slicer_version"),
        "thumbnail_count": len(thumbs),
    }


def diagnostics(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> dict:
    """Read-only health diagnostics: klippy state + message + Moonraker warnings.
    GET /printer/info + /server/info only. Never raises — reports what it can."""
    out: dict = {"schema_version": SCHEMA_VERSION, "host": host, "port": port}
    try:
        pi = _get(host, port, "/printer/info", timeout).get("result", {}) or {}
        out["klippy_state"] = pi.get("state")
        out["state_message"] = (pi.get("state_message") or "").strip() or None
        out["hostname"] = pi.get("hostname")
    except Exception as e:
        out["state_message"] = f"printer info unavailable: {e}"
    try:
        si = _get(host, port, "/server/info", timeout).get("result", {}) or {}
        out["warnings"] = si.get("warnings") or []
        out["failed_components"] = si.get("failed_components") or []
        out.setdefault("klippy_state", si.get("klippy_state"))
    except Exception:
        out.setdefault("warnings", [])
        out.setdefault("failed_components", [])
    out["healthy"] = (out.get("klippy_state") == "ready"
                      and not out.get("warnings") and not out.get("failed_components"))
    return out


def _matrix_stats(matrix: list) -> dict | None:
    """Reduce a probed Z matrix to insight stats (NOT a raw dump): overall range/std,
    central vs edge flatness, worst corner. All in mm."""
    rows = [r for r in matrix if isinstance(r, (list, tuple)) and r]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    flat = [float(z) for r in rows for z in r]
    n = len(flat)
    lo, hi = min(flat), max(flat)
    mean = sum(flat) / n
    std = (sum((z - mean) ** 2 for z in flat) / n) ** 0.5
    nr, nc = len(rows), len(rows[0])
    # central block (inner half) vs the rest (edges).
    r0, r1 = nr // 4, nr - nr // 4
    c0, c1 = nc // 4, nc - nc // 4
    center = [float(rows[i][j]) for i in range(r0, max(r1, r0 + 1)) for j in range(c0, max(c1, c0 + 1))]
    center_range = (max(center) - min(center)) if center else (hi - lo)
    corners = [float(rows[0][0]), float(rows[0][-1]), float(rows[-1][0]), float(rows[-1][-1])]
    corner_spread = max(corners) - min(corners)
    return {
        "range_mm": round(hi - lo, 3),
        "std_mm": round(std, 3),
        "max_dip_mm": round(lo - mean, 3),
        "max_peak_mm": round(hi - mean, 3),
        "center_range_mm": round(center_range, 3),
        "corner_spread_mm": round(corner_spread, 3),
        "rows": nr, "cols": nc,
    }


def bed_mesh(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> dict:
    """Read-only: the printer's REAL measured bed surface, reduced to flatness insight
    stats (not a raw matrix). GET /printer/objects/query?bed_mesh only. Never raises."""
    out: dict = {"schema_version": SCHEMA_VERSION, "host": host, "port": port, "available": False}
    try:
        bm = _get(host, port, "/printer/objects/query?bed_mesh", timeout) \
            .get("result", {}).get("status", {}).get("bed_mesh", {}) or {}
    except Exception as e:
        out["reason"] = str(e)
        return out
    matrix = bm.get("probed_matrix") or bm.get("mesh_matrix")
    stats = _matrix_stats(matrix) if matrix else None
    if not stats:
        out["reason"] = "no probed bed mesh on the printer (run a bed mesh calibration first)"
        out["profile_name"] = bm.get("profile_name") or None
        return out
    out.update({
        "available": True,
        "profile_name": bm.get("profile_name") or None,
        "mesh_min": bm.get("mesh_min"),
        "mesh_max": bm.get("mesh_max"),
        **stats,
    })
    return out


def loaded_filaments(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0):
    """What the printer says is loaded right now, or None when it does not say.

    The U1 carries a `print_task_config` Klipper object holding the per-toolhead
    filament assignment as *parallel arrays* — `filament_type`,
    `filament_sub_type`, `filament_color_rgba` and `filament_exist` — one entry
    per toolhead. That shape was read from a real U1 (firmware reporting four
    toolheads and a 271x335x281 mm volume) rather than guessed; an earlier
    version of this function looked for a list of objects and therefore reported
    "not available" against a printer that was in fact reporting it.

    A machine without the object returns None, which Preflight shows as unknown —
    never as an empty machine.

    Read-only: GET /printer/objects/query?print_task_config.
    """
    try:
        status = _get(host, port, "/printer/objects/query?print_task_config", timeout)             .get("result", {}).get("status", {})
    except Exception as exc:
        # Not being able to ask is not the printer saying it has nothing. Both
        # came back as None, so a dropped connection was reported to the user as
        # "this printer does not report which filaments are loaded" — a statement
        # about their machine, made on no evidence.
        raise PrinterUnavailable(
            f"Studio could not read what is loaded: {type(exc).__name__}") from exc
    cfg = status.get("print_task_config")
    if not isinstance(cfg, dict) or not cfg:
        return None

    def column(*names):
        for name in names:
            value = cfg.get(name)
            if isinstance(value, list) and value:
                return value
        return None

    types = column("filament_type")
    colours = column("filament_color_rgba", "filament_color")
    subtypes = column("filament_sub_type")
    vendors = column("filament_vendor")
    present = column("filament_exist")

    slots = max((len(c) for c in (types, colours, subtypes, present) if c), default=0)
    if not slots:
        return None

    def at(seq, i):
        return seq[i] if isinstance(seq, list) and i < len(seq) else None

    def hex_colour(value):
        if isinstance(value, str) and value.strip():
            return "#" + value.strip().lstrip("#")[:6].upper()
        return None

    out = []
    for i in range(slots):
        # `filament_exist` is the printer's own answer to "is a spool loaded
        # here". When it says no, the slot is empty however it is coloured.
        if present is not None and at(present, i) is False:
            out.append(None)
            continue
        material = at(types, i)
        sub = at(subtypes, i)
        entry = {
            "color": hex_colour(at(colours, i)),
            "material": f"{material} {sub}".strip() if (material and sub) else material,
            "vendor": at(vendors, i) or None,
        }
        out.append(entry if any(entry.values()) else None)
    return out


#: Paths a community firmware build serves for itself, with a phrase its own page
#: contains. Both are needed: the U1's web server answers *every* path with the
#: same single-page app, so a 200 on any path proves nothing at all. Verified on a
#: real U1 — `/firmware-config/`, `/metrics` and `/definitely-not-real-9f3b/` all
#: return the identical 2,863-byte page.
EXTENDED_MARKERS = (
    (80, "/firmware-config/", "firmware-config",
     "the Extended Firmware configuration page answered for itself"),
)

#: A path nothing serves on purpose. What comes back for it is what this server
#: says to everything, and anything identical to it is not a marker.
CONTROL_PATH = "/snapstudio-control-9f3b/"


def extended_firmware(host: str, timeout: float = 2.0) -> dict:
    """Is a community firmware build answering on this printer?

    Positive detection only, and detection means the firmware answered *for
    itself*: its own page, distinguishable from what the printer serves for a
    path nobody claims. Without that control request this would report every U1
    as running community firmware, because the U1's web server hands the same
    single-page app to every URL — which is how the first version of this
    function reported a stock machine as extended.

    A printer that does not answer distinctively has told Studio nothing: it may
    be stock, a different build, or behind a proxy. So this returns detected or
    unknown, and there is deliberately no value meaning "this printer is stock".
    """
    if not host:
        return {"detected": False, "known": False, "evidence": "no printer address"}

    def fetch(port: int, path: str) -> bytes | None:
        try:
            request = urllib.request.Request(_url(host, port, path), method="GET")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    return response.read(64 * 1024)
        except Exception:  # noqa: BLE001 — no answer is no evidence
            return None
        return None

    for port, path, phrase, evidence in EXTENDED_MARKERS:
        page = fetch(port, path)
        if not page:
            continue
        control = fetch(port, CONTROL_PATH)
        if control is not None and control == page:
            # The server answers everything with the same page, so this one says
            # nothing about what is installed.
            continue
        if phrase.encode("utf-8") not in page.lower():
            continue
        return {"detected": True, "known": True, "evidence": evidence, "source": path}

    return {"detected": False, "known": False,
            "evidence": ("no community firmware answered for itself on the paths Studio "
                         "knows about — which is not the same as this printer running "
                         "stock firmware")}


def capabilities(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> dict:
    """Read-only printer capabilities — the U1's REAL bed volume + toolhead count, so
    Design Intelligence can use the actual printer instead of assumed values.
    GET /printer/objects/list + /printer/objects/query?toolhead only."""
    objects = _get(host, port, "/printer/objects/list", timeout).get("result", {}).get("objects", []) or []
    toolhead_count = sum(1 for o in objects if o == "extruder" or (o.startswith("extruder") and o[8:].isdigit()))
    th = _get(host, port, "/printer/objects/query?toolhead", timeout).get("result", {}).get("status", {}).get("toolhead", {}) or {}
    amax = th.get("axis_maximum")   # klipper: [x, y, z, e]
    amin = th.get("axis_minimum")
    bed = None
    if isinstance(amax, (list, tuple)) and len(amax) >= 3:
        lo = amin if isinstance(amin, (list, tuple)) and len(amin) >= 3 else [0, 0, 0]
        bed = {"x": round(amax[0] - lo[0], 1), "y": round(amax[1] - lo[1], 1), "z": round(amax[2] - lo[2], 1)}
    return {
        "schema_version": SCHEMA_VERSION,
        "host": host, "port": port,
        "toolhead_count": toolhead_count or None,
        "bed_mm": bed,
        "klipper_objects": objects,   # raw object list — capability manifest for firmware_caps
    }


def machine_info(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> dict:
    """Read-only GET /machine/system_info — the one Moonraker call this project has
    never made before. Its `product_info` block reports the fitted nozzle diameter
    per toolhead directly from firmware (confirmed live against a real Snapmaker U1:
    `product_info.nozzle_diameter` is a real, populated array, not empty/absent as
    the nozzle check previously assumed). Its `sd_info` block is the only storage-
    capacity-shaped data Moonraker exposes; confirmed live that stock U1 firmware
    reports `total_bytes: 0` / `capacity: "Unknown"` there — genuinely not obtainable,
    not a Studio gap, so this function returns `storage_bytes: None` rather than a
    fabricated number when that's what the printer says.

    `/machine/system_info` also carries real identifying data this function must
    NEVER surface past this point: `device_name` (a user-chosen label — the printer
    used to verify this lived one), `serial_number`, `cpu_info.serial_number`,
    `network.*.mac_address`, and real LAN/global IP addresses. Only the two fields
    below are ever read out of the response; nothing else from `product_info`,
    `cpu_info`, `network`, or `sd_info` is extracted, logged, or returned — by
    construction, not by a redaction pass applied afterward.
    """
    result = _get(host, port, "/machine/system_info", timeout).get("result", {}).get("system_info", {}) or {}
    product = result.get("product_info", {}) or {}
    sd = result.get("sd_info", {}) or {}

    nozzle_diameters = product.get("nozzle_diameter")
    if not isinstance(nozzle_diameters, list) or not all(isinstance(n, (int, float)) for n in nozzle_diameters):
        nozzle_diameters = None

    storage_bytes = sd.get("total_bytes")
    if not isinstance(storage_bytes, (int, float)) or storage_bytes <= 0:
        storage_bytes = None

    return {
        "schema_version": SCHEMA_VERSION,
        "nozzle_diameters": nozzle_diameters,
        "storage_bytes": storage_bytes,
    }


# ---------------------------------------------------------------------------
# Printer Hub Phase B — CONTROL (user-initiated only).
#
# These functions issue Moonraker POSTs that move the machine. They are ONLY ever
# called from an explicit, user-confirmed action in the Studio UI (start/pause/
# resume/cancel/upload/emergency-stop). Nothing here runs automatically, on a
# timer, or as a side effect of monitoring. The UI is the safety gate: it must
# confirm start/cancel/emergency-stop before the corresponding function is called.
# LAN-trusted Moonraker (no auth) — same trust boundary as the read-only client.
# ---------------------------------------------------------------------------

def _post(host: str, port: int, path: str, timeout: float, body: bytes | None = None,
          content_type: str | None = None) -> dict:
    """User-initiated HTTP POST against Moonraker. Raises on failure."""
    headers = {"Content-Type": content_type} if content_type else {}
    req = urllib.request.Request(_url(host, port, path), data=body or b"", method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        try:
            return json.loads(raw) if raw else {"result": "ok"}
        except Exception:
            return {"result": "ok"}


def pause(host: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Pause the running print (safe, reversible). POST /printer/print/pause."""
    return {"ok": True, "action": "pause", "result": _post(host, port, "/printer/print/pause", timeout).get("result")}


def resume(host: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Resume a paused print. POST /printer/print/resume."""
    return {"ok": True, "action": "resume", "result": _post(host, port, "/printer/print/resume", timeout).get("result")}


def cancel(host: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Cancel the running print (NOT reversible — UI must confirm). POST /printer/print/cancel."""
    return {"ok": True, "action": "cancel", "result": _post(host, port, "/printer/print/cancel", timeout).get("result")}


def start(host: str, filename: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Start printing a gcode file ALREADY on the printer (UI must confirm + show the
    filename and a 'printer clear/loaded/ready' warning). POST /printer/print/start?filename=."""
    from urllib.parse import quote
    path = "/printer/print/start?filename=" + quote(filename.lstrip("/"))
    return {"ok": True, "action": "start", "filename": filename,
            "result": _post(host, port, path, timeout).get("result")}


def emergency_stop(host: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Emergency stop — cut heaters + halt motion immediately (UI must confirm on a
    dedicated screen). Klipper then needs FIRMWARE_RESTART to recover.

    Uses the canonical Klipper ``M112`` via ``/printer/gcode/script`` rather than
    Moonraker's ``POST /printer/emergency_stop`` — hardware testing on a real Snapmaker
    U1 (firmware 1.4.1.6) showed the U1's Moonraker build returns 404 for
    ``/printer/emergency_stop``, while ``/printer/gcode/script`` is available. M112 is
    the underlying emergency-shutdown gcode and works across Klipper builds."""
    return {"ok": True, "action": "emergency_stop",
            "result": _post(host, port, "/printer/gcode/script?script=M112", timeout).get("result")}


def job_queue(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> dict:
    """Read-only: the Moonraker job queue (list + state). GET /server/job_queue/status."""
    res = _get(host, port, "/server/job_queue/status", timeout).get("result", {}) or {}
    jobs = res.get("queued_jobs", []) or []
    return {"queue_state": res.get("queue_state"),
            "jobs": [{"filename": j.get("filename"), "id": j.get("job_id")} for j in jobs],
            "count": len(jobs)}


class UploadRefused(Exception):
    """The printer answered and refused the file.

    Kept apart from a network failure on purpose: a printer that says "no room" or
    "not permitted" has been reached and has an opinion, and the fix is on the
    printer. A connection that dropped has been reached by nothing, and the file
    may or may not be there.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


def upload_gcode(host: str, file_path: str, port: int = DEFAULT_PORT, timeout: float = 60.0) -> dict:
    """Upload a sliced .gcode to the printer (user-initiated). POST multipart /server/files/upload.
    Only .gcode/.g files; the file is read from a local path the user chose."""
    import os
    name = os.path.basename(file_path)
    ext = os.path.splitext(name)[1].lower()
    if ext not in (".gcode", ".g", ".gco"):
        raise ValueError("only sliced gcode (.gcode/.g) can be uploaded to the printer")
    with open(file_path, "rb") as f:
        content = f.read()
    boundary = "----snapstudioupload"
    pre = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
           f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    body = pre + content + post
    try:
        res = _post(host, port, "/server/files/upload", timeout, body=body,
                    content_type=f"multipart/form-data; boundary={boundary}")
    except urllib.error.HTTPError as exc:
        raise UploadRefused(exc.code, _refusal(exc)) from exc
    item = res.get("item", {}) if isinstance(res, dict) else {}
    return {"ok": True, "action": "upload", "filename": name,
            "path": item.get("path", name), "size": len(content)}


def _refusal(exc) -> str:
    """What a printer's refusal means to the person holding the file."""
    code = getattr(exc, "code", 0)
    if code == 401 or code == 403:
        return ("The printer refused the upload as not permitted. If it has been given a "
                "password or an API key, Studio has not been told it.")
    if code == 404:
        return ("This printer does not offer file uploads at the address Studio used. "
                "Check the port in Printer Hub.")
    if code == 409:
        return "The printer refused the upload because it is busy with something else."
    if code == 413:
        return "The printer refused the file as too large for it."
    if 400 <= code < 500:
        return f"The printer refused the upload (error {code})."
    return (f"The printer answered the upload with an error ({code}). Nothing has been "
            "started; check the printer before sending again.")


def confirm_upload(host: str, filename: str, expected_size: int | None = None,
                   port: int = DEFAULT_PORT, attempts: int = 10,
                   pause: float = 1.0, timeout: float = 5.0) -> dict:
    """Has the printer really got this file, and finished reading it?

    A successful upload POST means Moonraker accepted the bytes. It does not mean
    the file is listed, and it does not mean the metadata has been parsed —
    Moonraker does that asynchronously. Treating the POST as completion is how a
    tool ends up starting a job the printer cannot describe yet, or showing a
    thumbnail from the previous file of the same name. The U1 Toolkit hit this;
    Studio would have hit it too.

    So this polls the printer's own metadata for the file, asks it to scan once if
    the metadata has not appeared, and reports what is actually true. It never
    starts anything.
    """
    state = {"filename": filename, "present": False, "metadata_ready": False,
             "size_matches": None, "attempts": 0, "rescanned": False,
             "fresh": None, "modified": None}
    started = time.time()

    def look():
        try:
            data = _get(host, port, f"/server/files/metadata?filename={urllib.parse.quote(filename)}",
                        timeout)
        except Exception:
            return None
        # Moonraker wraps everything in {"result": ...}; _get returns the envelope.
        if isinstance(data, dict):
            inner = data.get("result")
            return inner if isinstance(inner, dict) else data
        return None

    for round_number in range(max(1, attempts)):
        state["attempts"] = round_number + 1
        meta = look()
        if meta:
            state["present"] = True
            size = meta.get("size")
            if expected_size is not None and isinstance(size, (int, float)):
                state["size_matches"] = int(size) == int(expected_size)
            # Moonraker can still be holding the metadata of the file this one
            # replaced. Same name, same size, older timestamp: the thumbnail and
            # the time estimate would be the previous job's.
            modified = meta.get("modified")
            if isinstance(modified, (int, float)):
                state["modified"] = modified
                state["fresh"] = modified >= (started - 60)
            # Moonraker fills these in once it has actually read the file.
            state["metadata_ready"] = any(
                meta.get(key) is not None
                for key in ("estimated_time", "object_height", "layer_count", "filament_total"))
            if state["metadata_ready"]:
                break
        if round_number == max(1, attempts) // 2 and not state["metadata_ready"]:
            # Ask once, politely, then keep waiting rather than hammering it.
            try:
                _post(host, port, "/server/files/metascan", timeout,
                      body=json.dumps({"filename": filename}).encode(),
                      content_type="application/json")
                state["rescanned"] = True
            except Exception:
                pass
        time.sleep(pause)

    state["ok"] = bool(state["present"] and state["metadata_ready"]
                       and state["size_matches"] is not False
                       and state["fresh"] is not False)
    state["detail"] = _upload_detail(state)
    return state


def _upload_detail(state: dict) -> str:
    if not state["present"]:
        return ("The printer has not listed this file. The upload may not have completed — "
                "check the printer before starting anything.")
    if state["size_matches"] is False:
        return ("The printer has a file with this name, but it is a different size. "
                "An older job of the same name may still be there.")
    if state["fresh"] is False:
        return ("The printer is still describing an older file of this name. Its estimate "
                "and thumbnail would be the previous job's, so give it a moment or check "
                "the file on the printer.")
    if not state["metadata_ready"]:
        return ("The file is on the printer, but it has not finished reading it yet. "
                "Give it a moment before starting the print.")
    return "The printer has the file and has finished reading it."
