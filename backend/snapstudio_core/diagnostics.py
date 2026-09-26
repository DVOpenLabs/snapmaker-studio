"""A support bundle a user can actually send, and read before sending.

Studio asks people to report when it gets an analysis wrong. That report is only
useful with the facts behind it — which slicer wrote the file, what Studio
concluded, what the printer said. Asking a beginner to gather those by hand means
they will not.

Three rules make this safe to hand to a stranger:

1. **Nothing leaves the machine.** This builds a file; sending it is the user's
   choice, made outside Studio.
2. **Everything is redacted before it is written**, not after. Usernames, home
   directories, IP addresses, hostnames and anything that looks like a token are
   replaced with placeholders on the way in.
3. **The user sees it first.** ``preview`` returns exactly what ``build`` would
   write, so nobody is asked to trust a black box.

Secrets are never *read* in order to be scrubbed: no environment sweep, no
credential store, no reading of files Studio was not already using.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "diagnostics/1"

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TOKENISH = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")
_WIN_PATH = re.compile(r"[A-Za-z]:\\\\[^\"'<>|\r\n]*|[A-Za-z]:\\[^\"'<>|\r\n]*")
_POSIX_HOME = re.compile(r"/(?:home|Users)/[^/\s\"']+")


def _placeholders() -> list[tuple[re.Pattern, str]]:
    """Literal values worth replacing first, longest first so a home directory
    is replaced before the username inside it."""
    pairs: list[tuple[str, str]] = []
    home = str(Path.home())
    if home:
        pairs.append((home, "<home>"))
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if user and len(user) > 2:
        pairs.append((user, "<user>"))
    try:
        host = socket.gethostname()
        if host and len(host) > 2:
            pairs.append((host, "<machine>"))
    except OSError:
        pass
    pairs.sort(key=lambda p: -len(p[0]))
    return [(re.compile(re.escape(value), re.I), token) for value, token in pairs]


def redact(value):
    """Scrub a JSON-ish structure. Returns a new structure; never mutates."""
    subs = _placeholders()

    def scrub_text(text: str) -> str:
        # Paths first. Replacing a username inside a path would insert angle
        # brackets that then stop the path pattern dead, leaving the rest of the
        # path — including the model's name — in the bundle.
        text = _WIN_PATH.sub("<path>", text)
        text = _POSIX_HOME.sub("<home>", text)
        text = _IPV4.sub("<ip>", text)
        for pattern, token in subs:
            text = pattern.sub(token, text)
        # A long opaque run is more likely a token than prose, and there is no
        # way to tell a hash from a credential by shape alone: a hex-format API
        # key is indistinguishable from a sha256 digest under any regex. This
        # used to keep anything that looked like a hash on the reasoning that
        # hashes are "useful and not secret" — but this same file already
        # strips a genuinely harmless hash (`name_hashes`, below) on the
        # opposite reasoning, that a bundle goes to a stranger who could check
        # a guess against it. A support bundle is not the place to bet on
        # which reasoning applies to a given 32-64 character run; everything
        # that shape is redacted, unconditionally.
        text = _TOKENISH.sub("<redacted>", text)
        return text

    def walk(node):
        if isinstance(node, str):
            return scrub_text(node)
        if isinstance(node, dict):
            return {scrub_text(str(k)): walk(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(v) for v in node]
        return node

    return walk(value)


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("snapmaker-studio")
    except Exception:
        return "unknown"


def collect(project_path: str | None = None,
            gcode_path: str | None = None,
            host: str | None = None,
            port: int = 7125,
            include_printer: bool = True,
            data_dir: str | None = None) -> dict:
    """Gather the bundle. Every section is optional and failure is reported, not raised."""
    bundle: dict = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "studio": {
            "engine_version": _version(),
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
        },
        "sections": [],
        "errors": [],
    }

    if project_path:
        bundle["project"] = _section(bundle, "project", lambda: _project(project_path))
    if gcode_path:
        bundle["sliced_job"] = _section(bundle, "sliced_job", lambda: _sliced(gcode_path))
    if include_printer and host:
        bundle["printer"] = _section(bundle, "printer", lambda: _printer(host, port))
    bundle["fix_ledger"] = _section(bundle, "fix_ledger", lambda: _ledger(data_dir))

    return redact(bundle)


def _section(bundle: dict, name: str, fn):
    try:
        value = fn()
        bundle["sections"].append(name)
        return value
    except Exception as exc:  # noqa: BLE001 — a failed section must not lose the rest
        bundle["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        return None


def _project(path: str) -> dict:
    from . import doctor, project_traits
    traits = project_traits.extract(path)
    findings = None
    try:
        findings = doctor.diagnose(path)
    except Exception:
        pass
    return {
        # The file name is the user's model name and is deliberately not carried.
        "extension": Path(path).suffix.lower(),
        "size_bytes": Path(path).stat().st_size if Path(path).exists() else None,
        "traits": traits,
        "doctor": findings,
    }


def _sliced(path: str) -> dict:
    from . import gcode, post_slice, sliced_cost
    facts = gcode.read_facts(path)
    # The reader reports which file it read, and that name is the user's model
    # name — `dads urn lid v3.gcode` in a bundle handed to a stranger. The project
    # section has always dropped it; this one was carrying it through.
    trimmed = {k: v for k, v in facts.items() if k not in ("config", "file")}
    trimmed["extension"] = Path(path).suffix.lower()
    # The object hashes are how Studio recognises a project in its own slice. They
    # are not names, but a bundle goes to a stranger, and someone holding a guess
    # could check it against a hash. The count and the set digest answer every
    # question a bug report needs to ask.
    if isinstance(trimmed.get("objects"), dict):
        trimmed["objects"] = {k: v for k, v in trimmed["objects"].items()
                              if k != "name_hashes"}
    return {
        "facts": trimmed,
        "checks": post_slice.analyse(facts, {"reachable": False}),
        "cost": sliced_cost.estimate(facts),
    }


def _loaded_or_reason(moonraker, host: str, port: int):
    """What is loaded, or why Studio could not find out. Never the two conflated."""
    try:
        return moonraker.loaded_filaments(host, port)
    except moonraker.PrinterUnavailable as exc:
        return {"error": str(exc)}


def _printer(host: str, port: int) -> dict:
    from . import moonraker
    caps = moonraker.capabilities(host, port)
    out = {
        "reachable": True,
        "toolhead_count": caps.get("toolhead_count"),
        "bed_mm": caps.get("bed_mm"),
        "klipper_object_count": len(caps.get("klipper_objects") or []),
        "loaded_filaments": _loaded_or_reason(moonraker, host, port),
    }
    try:
        out["print_state"] = moonraker.status(host, port).get("print_state")
    except Exception:
        out["print_state"] = None
    try:
        out["firmware"] = moonraker.diagnostics(host, port).get("firmware")
    except Exception:
        pass
    return out


def _ledger(data_dir: str | None = None) -> dict:
    """The fix ledger's exportable form, which already strips local paths."""
    from . import fix_ledger
    from .paths import data_dir as _resolve_data_dir

    # The engine's own data directory, resolved by the shared resolver —
    # staying within the core, without importing the API layer. Diagnostics is
    # read-only: resolve the path without creating it (a missing directory just
    # means an empty ledger, same as before this resolver was centralized).
    base = _resolve_data_dir(data_dir, create=False)
    return fix_ledger.export_all(base, limit=20)


def preview(**kwargs) -> dict:
    """Exactly what ``build`` would write, so the user can read it first."""
    bundle = collect(**kwargs)
    text = json.dumps(bundle, indent=2, sort_keys=True, default=str)
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle": bundle,
        "text": text,
        "bytes": len(text.encode("utf-8")),
        "sections": bundle.get("sections", []),
        "note": ("Nothing has been sent anywhere. Usernames, home directories, file paths, "
                 "machine names and addresses were replaced before this was assembled."),
    }


def build(out_dir: str | None = None, **kwargs) -> dict:
    """Write the bundle next to the user's other Studio files and return its path."""
    result = preview(**kwargs)
    directory = Path(out_dir) if out_dir else Path.home() / "Documents"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"snapmaker-studio-diagnostics-{stamp}.json"
    target.write_text(result["text"], encoding="utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(target),
        "bytes": result["bytes"],
        "sections": result["sections"],
        "note": result["note"],
    }
