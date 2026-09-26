"""Community printer verification — evidence anyone can attach to an issue.

Every printer-profile assumption Studio ships — build volume, toolhead
count, which capabilities a firmware exposes — has only ever been checked
against the one machine this project's own maintainer owns. This is the
other half: a read-only check anyone can run against *their* printer,
producing a bundle safe to hand to a stranger — no IP, no hostname, no
credentials, nothing that identifies the network it ran on.

Every check here goes through the exact same read-only Moonraker calls
`printer_facts`/`preflight` already make — `probe`, `capabilities`,
`loaded_filaments` — never a control route, never a write. A verdict is
PASS, FAIL or UNKNOWN, and UNKNOWN is not a failure: firmware that does not
publish a fact is a different thing from Studio failing to read one that
exists, and the two must never look the same on the page.

This deliberately does not call anything "hardware verified" — that label
belongs on docs/PRINTER_COMPATIBILITY.md, decided by a maintainer reading a
bundle someone submitted, never asserted by the tool that produced it.
"""
from __future__ import annotations

import platform
from datetime import datetime, timezone

SCHEMA_VERSION = "hardwareverify/1"

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"


def _check(id_: str, title: str, result: str, evidence: str) -> dict:
    return {"id": id_, "title": title, "result": result, "evidence": evidence}


def run(host: str, port: int = 7125) -> dict:
    """Read-only checks against one printer. Returns PASS/FAIL/UNKNOWN per
    check plus the facts a hardware-compatibility table needs — nothing here
    is redacted yet; call `build_evidence` for the version safe to share."""
    from . import moonraker, printer_profiles

    checks = [None]  # placeholder for the reachability check, filled below
    probe = moonraker.probe(host, port)
    reachable = bool(probe.get("reachable"))
    klippy_state = probe.get("klippy_state")
    checks[0] = _check(
        "printer.reachable", "Printer answers on the network",
        PASS if reachable else FAIL,
        f"Moonraker {probe.get('moonraker_version')}" if reachable
        else (probe.get("error") or "no answer"))

    if not reachable:
        return {
            "schema_version": SCHEMA_VERSION, "checks": checks,
            "moonraker_version": None, "printer_model": None, "capabilities": None,
            "klippy_state": None,
        }

    checks.append(_check(
        "moonraker.version", "Moonraker reports a version",
        PASS if probe.get("moonraker_version") else UNKNOWN,
        probe.get("moonraker_version") or "not reported"))
    # Moonraker answering is not the same as Klipper being connected to it —
    # "Klippy Host not connected" is a common, ordinary state (a firmware
    # restart, a config reload in progress) and exactly the moment someone
    # would run this tool wondering why nothing else answers.
    checks.append(_check(
        "printer.klippy_ready", "Klipper is connected to Moonraker",
        PASS if klippy_state == "ready" else UNKNOWN,
        klippy_state or "not reported"))

    # Moonraker being reachable does not mean the object/capability query
    # will succeed — a disconnected Klipper answers /server/info (above) but
    # refuses /printer/objects/list with an HTTP error. That failure is a
    # transport/connection state, not evidence about what this firmware
    # supports, and must read as unknown rather than crash the whole scan.
    try:
        caps = moonraker.capabilities(host, port)
        toolhead_count = caps.get("toolhead_count")
        bed_mm = caps.get("bed_mm") or {}
        objects = caps.get("klipper_objects") or []
        capabilities_error = None
    except Exception as exc:
        toolhead_count = None
        bed_mm = {}
        objects = []
        capabilities_error = f"{type(exc).__name__}: {exc}"

    if capabilities_error:
        note = f"could not read capabilities: {capabilities_error}"
        checks.append(_check("capabilities.toolhead_count", "Toolhead count reported", UNKNOWN, note))
        checks.append(_check("capabilities.bed_size", "Bed size reported", UNKNOWN, note))
        checks.append(_check("capabilities.object_list", "Firmware object list enumerated", UNKNOWN, note))
    else:
        checks.append(_check(
            "capabilities.toolhead_count", "Toolhead count reported",
            PASS if toolhead_count else UNKNOWN,
            f"{toolhead_count} toolhead(s)" if toolhead_count else "not reported"))
        checks.append(_check(
            "capabilities.bed_size", "Bed size reported",
            PASS if bed_mm.get("x") and bed_mm.get("y") and bed_mm.get("z") else UNKNOWN,
            f"{bed_mm.get('x')} x {bed_mm.get('y')} x {bed_mm.get('z')} mm" if bed_mm else "not reported"))
        checks.append(_check(
            "capabilities.object_list", "Firmware object list enumerated",
            PASS if objects else UNKNOWN,
            f"{len(objects)} object(s)"))

    # A dropped connection while asking what is loaded is a transport
    # failure, not the firmware saying it has nothing — `loaded_filaments`
    # raises PrinterUnavailable for exactly that distinction, and mixing the
    # two here would put a false statement about the user's firmware into a
    # bundle meant to be public evidence.
    try:
        loaded = moonraker.loaded_filaments(host, port)
        loaded_error = None
    except moonraker.PrinterUnavailable as exc:
        loaded = None
        loaded_error = str(exc)
    except Exception as exc:
        loaded = None
        loaded_error = f"{type(exc).__name__}: {exc}"

    if loaded_error:
        checks.append(_check(
            "material.loaded_filaments", "Loaded filament reported by firmware", UNKNOWN,
            f"Studio could not read it: {loaded_error}"))
    else:
        checks.append(_check(
            "material.loaded_filaments", "Loaded filament reported by firmware",
            PASS if loaded is not None else UNKNOWN,
            f"{len([f for f in loaded if f])} slot(s) reported" if loaded is not None
            else "this firmware does not report loaded filament"))

    identity = printer_profiles.identify({
        "reachable": True, "toolhead_count": toolhead_count, "klipper_objects": objects,
    })
    checks.append(_check(
        "printer.identified", "Studio recognises this printer model",
        PASS if identity.get("matched") else UNKNOWN,
        identity.get("evidence") or "not recognised"))

    return {
        "schema_version": SCHEMA_VERSION,
        "checks": checks,
        "moonraker_version": probe.get("moonraker_version"),
        "printer_model": identity.get("printer_id"),
        "klippy_state": klippy_state,
        "capabilities": None if capabilities_error else {
            "toolhead_count": toolhead_count,
            "bed_mm": bed_mm or None,
            "object_count": len(objects),
        },
    }


def build_evidence(host: str, port: int = 7125) -> dict:
    """The full, redacted, ready-to-attach bundle — the point of this module.

    Goes through `diagnostics.redact()`, the same scrub every other support
    artifact in Studio uses, so the one place that decides what is safe to
    hand to a stranger stays the one place — never duplicated here.
    """
    from . import diagnostics

    result = run(host, port)
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "studio_version": diagnostics._version(),
        "os": f"{platform.system()} {platform.release()}",
        **result,
    }
    return diagnostics.redact(bundle)
