"""The filament presets Snapmaker Orca actually has installed for the U1.

Project Materials maps a physical spool to a *real installed Orca preset* by NAME.
Whether a name is real is not something a provider can tell Studio, so this reads
the installed catalogue (read-only: names, vendor, type and which U1 nozzles a
preset exists for) and answers one question honestly: does this name identify
exactly one installed, U1-compatible preset that supports this nozzle?

Rules, from the Orca GUI matrix on 2.3.6:

* Orca restores a named installed preset's ``filament_ids`` and print values on load,
  so the name is what decides the filament's behaviour.
* ``filament_id`` / ``setting_id`` cannot identify a preset: the Matte and SnapSpeed
  U1 presets share both. They are never used as a key here.
* The preset *name* Orca writes depends on the nozzle. For 0.4 mm it is often the
  plain ``Snapmaker PLA Matte @U1``; other nozzles (and some 0.4 presets) carry a
  `` 0.2 nozzle`` / `` 0.4 nozzle`` suffix. The catalogue therefore keys on the BASE
  name and hands back the exact name to write for a given nozzle.

A preset is PROVEN only when the catalogue holds exactly one matching base preset,
it is U1-compatible, and it supports the confirmed nozzle. Anything else is
``needs_confirmation`` or ``no_match`` — never a silent pick.

Read-only. User-made presets in Orca's own data folder are not read in this version.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

PROVEN = "proven"
NEEDS_CONFIRMATION = "needs_confirmation"
NO_MATCH = "no_match"

_NOZZLE_SUFFIX = re.compile(r"\s+(\d\.\d)\s+nozzle$")
_U1_PRINTER = re.compile(r"^Snapmaker U1 \((\d\.\d) nozzle\)$")
_SPACES = re.compile(r"\s+")
_MAX_INHERIT_DEPTH = 8


def _clean(name) -> str:
    return _SPACES.sub(" ", str(name or "").strip())


def base_name(name: str) -> str:
    """A preset name without its trailing `` <n> nozzle`` suffix."""
    return _NOZZLE_SUFFIX.sub("", _clean(name))


def norm_key(name: str) -> str:
    """The comparison form of a name: spacing, nozzle suffix and letter case removed."""
    return base_name(name).casefold()


def default_profile_dirs(env: dict | None = None, platform: str | None = None) -> list[Path]:
    """Where Snapmaker Orca keeps its bundled U1 profiles, most likely first.

    ``SNAPSTUDIO_ORCA_PROFILES_DIR`` overrides everything (tests, portable installs).
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    override = env.get("SNAPSTUDIO_ORCA_PROFILES_DIR")
    if override:
        return [Path(override)]
    out: list[Path] = []
    if platform == "win32":
        roots = [env.get("ProgramFiles") or r"C:\Program Files", env.get("ProgramFiles(x86)")]
        local = env.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "Programs"))
        for root in roots:
            if root:
                out.append(Path(root) / "Snapmaker_Orca" / "resources" / "profiles" / "Snapmaker")
    elif platform.startswith("linux"):
        for root in ("/opt/snapmaker-orca", "/opt/Snapmaker_Orca", "/usr/share/snapmaker-orca",
                     "/usr/local/share/snapmaker-orca"):
            out.append(Path(root) / "resources" / "profiles" / "Snapmaker")
            out.append(Path(root) / "profiles" / "Snapmaker")
    return out


def _fingerprint(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]


def _first(value):
    if isinstance(value, list):
        return str(value[0]) if value else None
    return None if value is None else str(value)


class Catalog:
    """An installed filament-preset catalogue. Build with :func:`load`."""

    def __init__(self, entries: dict[str, dict], source: dict):
        self.entries = entries                  # base name -> entry
        self.source = source
        by_key: dict[str, list[str]] = {}
        for base in entries:
            by_key.setdefault(norm_key(base), []).append(base)
        self._by_key = {k: sorted(v) for k, v in by_key.items()}
        self.fingerprint = _fingerprint(sorted(e["fingerprint"] for e in entries.values()))

    def __len__(self) -> int:
        return len(self.entries)

    def names_for(self, nozzle: str) -> list[str]:
        """Base names of every preset that supports `nozzle`, sorted."""
        return sorted(b for b, e in self.entries.items() if nozzle in e["nozzles"])

    def preset_name(self, base: str, nozzle: str) -> str | None:
        """The exact preset name Orca writes for `base` on `nozzle`, or None."""
        entry = self.entries.get(base)
        return entry["nozzles"].get(nozzle) if entry else None

    def evaluate(self, name: str | None, nozzle: str) -> dict:
        """Is `name` one real, U1-compatible installed preset that supports `nozzle`?"""
        raw = _clean(name)
        if not raw:
            return _result(NO_MATCH, "No preset name was given.", raw, nozzle)
        candidates = self._by_key.get(norm_key(raw), [])
        if not candidates:
            return _result(NO_MATCH, "No installed Snapmaker Orca U1 preset has that name.",
                           raw, nozzle)
        if len(candidates) > 1:
            return _result(NEEDS_CONFIRMATION,
                           "More than one installed preset matches that name.",
                           raw, nozzle, candidates=candidates)
        base = candidates[0]
        entry = self.entries[base]
        if nozzle not in entry["nozzles"]:
            return _result(NO_MATCH,
                           f"That preset is installed but has no {nozzle} mm nozzle version.",
                           raw, nozzle, base=base, candidates=[base])
        exact = raw == base or raw in entry["nozzles"].values()
        status = PROVEN if exact else NEEDS_CONFIRMATION
        reason = ("Exact installed preset." if exact else
                  "The name matches an installed preset only after ignoring letter case.")
        return _result(status, reason, raw, nozzle, base=base, candidates=[base],
                       preset_name=entry["nozzles"][nozzle], fingerprint=entry["fingerprint"],
                       filament_type=entry["filament_type"], vendor=entry["vendor"])

    def suggest_generic(self, family: str | None, nozzle: str) -> dict | None:
        """`Generic <family> @U1`, or the plain `Generic <family>` the U1 catalogue also ships,
        offered as a SUGGESTION only — never proven here. Exact names only: no pattern, no pick
        between look-alikes (`Generic PETG` and `Generic PETG HF` are different presets)."""
        fam = _clean(family).upper()
        if not fam:
            return None
        for name in (f"Generic {fam} @U1", f"Generic {fam}"):
            found = self.evaluate(name, nozzle)
            if found["status"] == PROVEN:
                found = dict(found)
                found["status"] = NEEDS_CONFIRMATION
                found["reason"] = (f"{found['base_name']} is installed for this nozzle. Studio suggests it "
                                   "but does not choose between presets for you.")
                found["suggestion"] = True
                return found
        return None

    def verify(self, base: str, fingerprint: str | None, nozzle: str) -> dict:
        """Does a remembered mapping still identify the same installed preset?"""
        found = self.evaluate(base, nozzle)
        if found["status"] != PROVEN:
            return found
        if fingerprint and found["fingerprint"] != fingerprint:
            found = dict(found)
            found["status"] = NEEDS_CONFIRMATION
            found["reason"] = "The installed preset with this name is no longer the one you confirmed."
            found["stale"] = True
        return found


def _result(status, reason, name, nozzle, *, base=None, candidates=None, preset_name=None,
            fingerprint=None, filament_type=None, vendor=None) -> dict:
    return {"status": status, "reason": reason, "asked": name, "nozzle": nozzle,
            "base_name": base, "preset_name": preset_name, "candidates": candidates or [],
            "fingerprint": fingerprint, "filament_type": filament_type, "vendor": vendor}


def _read_json(path: Path):
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _inherited(doc: dict, docs: dict[str, dict], key: str):
    seen = 0
    cur = doc
    while cur is not None and seen < _MAX_INHERIT_DEPTH:
        if key in cur:
            return cur[key]
        parent = cur.get("inherits")
        cur = docs.get(parent) if parent else None
        seen += 1
    return None


def load(profile_dir: str | os.PathLike) -> Catalog | None:
    """Read the installed system filament presets under `.../profiles/Snapmaker`.

    Returns None when the folder is missing or holds no usable preset — the caller
    then treats every mapping as unprovable rather than guessing."""
    root = Path(profile_dir)
    fdir = root / "filament"
    if not fdir.is_dir():
        return None
    docs: dict[str, dict] = {}
    for path in sorted(fdir.glob("*.json")):
        doc = _read_json(path)
        if doc and doc.get("name"):
            docs[str(doc["name"])] = doc
    entries: dict[str, dict] = {}
    for name, doc in docs.items():
        if str(doc.get("instantiation", "")).lower() != "true":
            continue
        compat = _inherited(doc, docs, "compatible_printers") or []
        nozzles = {m.group(1) for p in compat if (m := _U1_PRINTER.match(str(p)))}
        if not nozzles:
            continue
        base = base_name(name)
        entry = entries.setdefault(base, {
            "base_name": base, "nozzles": {}, "setting_id": None,
            "filament_type": None, "vendor": None})
        for n in nozzles:
            entry["nozzles"][n] = _clean(name)
        entry["setting_id"] = entry["setting_id"] or _first(_inherited(doc, docs, "setting_id"))
        entry["filament_type"] = entry["filament_type"] or _first(_inherited(doc, docs, "filament_type"))
        entry["vendor"] = entry["vendor"] or _first(_inherited(doc, docs, "filament_vendor"))
    if not entries:
        return None
    for entry in entries.values():
        entry["fingerprint"] = _fingerprint([
            entry["base_name"], str(entry["setting_id"]), str(entry["filament_type"]),
            str(entry["vendor"]),
            ",".join(f"{n}={entry['nozzles'][n]}" for n in sorted(entry["nozzles"]))])
    vendor_json = _read_json(root.parent / "Snapmaker.json") or {}
    source = {"kind": "system", "profiles_version": _first(vendor_json.get("version")),
              "presets": len(entries)}
    return Catalog(entries, source)


def load_default(env: dict | None = None, platform: str | None = None) -> Catalog | None:
    """The catalogue of the first Orca install found, or None when none is found."""
    for candidate in default_profile_dirs(env, platform):
        cat = load(candidate)
        if cat is not None:
            return cat
    return None
