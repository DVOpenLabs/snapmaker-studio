"""The filament presets Snapmaker Orca actually has installed for the U1.

Project Materials maps a physical spool to a *real installed Orca preset* by NAME. Whether a name is
real is not something a provider can tell Studio, so this reads the installed catalogue (read-only:
names, vendor, type, parent and which U1 nozzles a preset is stated to fit) and answers one question
honestly: does this name identify exactly one installed preset that is usable for this U1 nozzle?

Two sources, kept apart on every record:

* ``system`` - Orca's bundled U1 profiles (``resources/profiles/Snapmaker/filament``).
* ``user``   - presets the person made in Orca (``<Orca data>/user/<id>/filament/*.json``). Only that
  folder is listed and only those JSON files are read; nothing else in the data folder is touched,
  and nothing is ever written.

Rules, from the Orca GUI matrices on 2.3.6:

* Orca restores a named installed preset's ``filament_ids`` and print values on load, so the name is
  what decides the filament's behaviour.
* ``filament_id`` / ``setting_id`` cannot identify a preset: the Matte and SnapSpeed U1 presets share
  both. They are never used as a key here.
* The preset *name* Orca writes depends on the nozzle. For 0.4 mm it is often the plain
  ``Snapmaker PLA Matte @U1``; other nozzles carry a `` 0.2 nozzle`` suffix. The catalogue keys on the
  BASE name and hands back the exact name to write for a given nozzle.

A preset is PROVEN only when exactly one installed record matches, it is STATED to fit the U1 for the
confirmed nozzle (its own ``compatible_printers`` list, or the list of the preset it inherits), and
nothing else installed claims the same name. A user preset that does not say which printers it is for
is ``needs_confirmation`` and *confirmable*: the person can say it is a U1 preset, and only then is it
used. Two records for one name and nozzle - system vs user, user vs user, nozzle variants - are
ambiguous and never resolved by last-wins; the person picks one by its ``ref``.
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

SYSTEM = "system"
USER = "user"

_NOZZLE_SUFFIX = re.compile(r"\s+(\d\.\d)\s+nozzle$")
_U1_PRINTER = re.compile(r"^Snapmaker U1 \((\d\.\d) nozzle\)$")
_SPACES = re.compile(r"\s+")
_MAX_INHERIT_DEPTH = 8
_MAX_PRESET_BYTES = 1_000_000            # a filament preset is a few KB; refuse to read anything absurd
_MAX_USER_PRESETS = 2000


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


def default_user_roots(env: dict | None = None, platform: str | None = None) -> list[Path]:
    """Where Snapmaker Orca keeps the presets a person made: ``<Orca data>/user``.

    ``SNAPSTUDIO_ORCA_DATA_DIR`` overrides everything (tests, a custom ``--datadir``).
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    override = env.get("SNAPSTUDIO_ORCA_DATA_DIR")
    if override:
        return [Path(override) / "user"]
    if platform == "win32":
        appdata = env.get("APPDATA")
        return [Path(appdata) / "Snapmaker_Orca" / "user"] if appdata else []
    if platform.startswith("linux"):
        home = env.get("XDG_CONFIG_HOME") or (os.path.join(env["HOME"], ".config") if env.get("HOME") else None)
        return [Path(home) / "Snapmaker_Orca" / "user"] if home else []
    return []


def _fingerprint(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]


def _first(value):
    if isinstance(value, list):
        return str(value[0]) if value else None
    return None if value is None else str(value)


def _label(rec: dict) -> str:
    return f"{rec['name']} ({'your preset' if rec['source'] == USER else 'system preset'})"


class Catalog:
    """An installed filament-preset catalogue. Build with :func:`load`."""

    def __init__(self, entries: dict[str, dict], source: dict):
        self.entries = entries                  # base name -> entry (see _entry_from)
        self.source = source
        by_key: dict[str, list[str]] = {}
        for base in entries:
            by_key.setdefault(norm_key(base), []).append(base)
        self._by_key = {k: sorted(v) for k, v in by_key.items()}
        self.fingerprint = _fingerprint(sorted(r["fingerprint"] for e in entries.values() for r in e["records"]))

    def __len__(self) -> int:
        return len(self.entries)

    # --- listing ---------------------------------------------------------------------------------
    def names_for(self, nozzle: str) -> list[str]:
        """Base names with at least one record usable for `nozzle`, or one the person may confirm."""
        return sorted(b for b, e in self.entries.items()
                      if any(nozzle in r["nozzles"] or not r["nozzles"] for r in e["records"]))

    def records_for(self, base: str, nozzle: str) -> list[dict]:
        """Every record of `base` that is usable for `nozzle` or confirmable, in a stable order."""
        entry = self.entries.get(base)
        if not entry:
            return []
        return sorted((r for r in entry["records"] if nozzle in r["nozzles"] or not r["nozzles"]),
                      key=lambda r: (r["source"] != SYSTEM, r["name"], r["ref"]))

    def preset_name(self, base: str, nozzle: str) -> str | None:
        """The exact preset name Orca writes for `base` on `nozzle`, or None (also when ambiguous)."""
        entry = self.entries.get(base)
        return entry["nozzles"].get(nozzle) if entry else None

    # --- proof -----------------------------------------------------------------------------------
    def evaluate(self, name: str | None, nozzle: str, ref: str | None = None, source: str | None = None) -> dict:
        """Is `name` one real installed preset that is usable for `nozzle`?

        `ref` pins one specific user preset file and `source` pins system or user; that is how a person
        resolves an ambiguous name. Without a pin, more than one viable record is ``needs_confirmation``.
        """
        raw = _clean(name)
        if not raw:
            return _result(NO_MATCH, "No preset name was given.", raw, nozzle)
        candidates = self._by_key.get(norm_key(raw), [])
        if not candidates:
            return _result(NO_MATCH, "No installed Snapmaker Orca U1 preset has that name.", raw, nozzle)
        if len(candidates) > 1:
            return _result(NEEDS_CONFIRMATION, "More than one installed preset matches that name.",
                           raw, nozzle, candidates=candidates)
        base = candidates[0]
        entry = self.entries[base]
        pool = entry["records"]
        if ref is not None:
            pool = [r for r in pool if r["ref"] == ref]
        elif source is not None:
            pool = [r for r in pool if r["source"] == source]
        if not pool:
            return _result(NO_MATCH, "That installed preset is no longer there.", raw, nozzle,
                           base=base, candidates=[base])
        viable = [r for r in pool if nozzle in r["nozzles"] or not r["nozzles"]]
        if not viable:
            return _result(NO_MATCH, f"That preset is installed but has no {nozzle} mm nozzle version.",
                           raw, nozzle, base=base, candidates=[base])
        if len(viable) > 1:
            return _result(NEEDS_CONFIRMATION,
                           f"More than one installed preset claims this name for the {nozzle} mm nozzle.",
                           raw, nozzle, base=base, candidates=sorted(r["name"] for r in viable),
                           choices=[_choice(r) for r in viable])
        rec = viable[0]
        if nozzle not in rec["nozzles"]:
            return _result(NEEDS_CONFIRMATION, rec["unproven_reason"] or "Studio cannot tell which printers this preset is for.",
                           raw, nozzle, base=base, candidates=[base], preset_name=rec["name"],
                           fingerprint=rec["fingerprint"], filament_type=rec["filament_type"], vendor=rec["vendor"],
                           record=rec, confirmable=True)
        exact = raw == base or raw == rec["name"] or raw in {r["name"] for r in entry["records"]}
        status = PROVEN if exact else NEEDS_CONFIRMATION
        reason = ("Exact installed preset." if exact else
                  "The name matches an installed preset only after ignoring letter case.")
        return _result(status, reason, raw, nozzle, base=base, candidates=[base], preset_name=rec["name"],
                       fingerprint=rec["fingerprint"], filament_type=rec["filament_type"], vendor=rec["vendor"],
                       record=rec)

    def suggest_generic(self, family: str | None, nozzle: str) -> dict | None:
        """`Generic <family> @U1`, or the plain `Generic <family>` the U1 catalogue also ships,
        offered as a SUGGESTION only - never proven here. Exact names only: no pattern, no pick
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

    def verify(self, base: str, fingerprint: str | None, nozzle: str, ref: str | None = None,
               proof: str | None = None, source: str | None = None) -> dict:
        """Does a remembered mapping still identify the same installed preset?

        `proof` is how the mapping was confirmed: ``user_confirmed`` for a user preset the person said
        is a U1 preset. That stays usable only while the record is unchanged and still unambiguous."""
        found = self.evaluate(base, nozzle, ref, source)
        usable = found["status"] == PROVEN or (
            proof == "user_confirmed" and found.get("confirmable") and found["status"] == NEEDS_CONFIRMATION)
        if not usable:
            return found
        if fingerprint and found["fingerprint"] != fingerprint:
            found = dict(found)
            found["status"] = NEEDS_CONFIRMATION
            found["confirmable"] = bool(found.get("confirmable"))
            found["reason"] = "The installed preset with this name is no longer the one you confirmed."
            found["stale"] = True
            return found
        if found["status"] != PROVEN:
            found = dict(found)
            found["status"] = PROVEN
            found["proof"] = "user_confirmed"
            found["reason"] = "A preset of yours that you confirmed is for the U1."
        return found


def _choice(rec: dict) -> dict:
    return {"ref": rec["ref"], "name": rec["name"], "source": rec["source"], "location": rec["location"],
            "proof": rec["proof"]}


def _result(status, reason, name, nozzle, *, base=None, candidates=None, preset_name=None,
            fingerprint=None, filament_type=None, vendor=None, choices=None, record=None,
            confirmable=False) -> dict:
    return {"status": status, "reason": reason, "asked": name, "nozzle": nozzle,
            "base_name": base, "preset_name": preset_name, "candidates": candidates or [],
            "fingerprint": fingerprint, "filament_type": filament_type, "vendor": vendor,
            "choices": choices or [], "confirmable": confirmable,
            "source": record["source"] if record else None, "ref": record["ref"] if record else None,
            "proof": record["proof"] if record else None, "location": record["location"] if record else None}


# --- reading the installed presets ---------------------------------------------------------------

def _read_json(path: Path):
    try:
        if path.is_symlink() or path.stat().st_size > _MAX_PRESET_BYTES:
            return None
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _chain(doc: dict, lookup, key: str):
    """(value, depth) of the nearest `key` on the doc or an ancestor, or (None, None)."""
    cur, depth = doc, 0
    while cur is not None and depth < _MAX_INHERIT_DEPTH:
        if key in cur:
            return cur[key], depth
        parent = cur.get("inherits")
        cur = lookup(parent) if parent else None
        depth += 1
    return None, None


def _record(doc: dict, lookup, *, source: str, ref: str, location, file: str, stat) -> dict | None:
    name = _clean(doc.get("name"))
    if not name:
        return None
    printers, depth = _chain(doc, lookup, "compatible_printers")
    listed = printers if isinstance(printers, list) else []
    nozzles = {m.group(1) for p in listed if (m := _U1_PRINTER.match(str(p)))}
    if nozzles:
        proof, reason = ("listed" if depth == 0 else "inherited"), None
    elif listed:
        proof, reason = "unstated", "It lists other printers, not the U1."
    else:
        proof, reason = "unstated", "It does not say which printers it is for, so Studio cannot tell it fits the U1."
    setting_id, _ = _chain(doc, lookup, "setting_id")
    ftype, _ = _chain(doc, lookup, "filament_type")
    vendor, _ = _chain(doc, lookup, "filament_vendor")
    parent = _clean(doc.get("inherits")) or None
    rec = {
        "ref": ref, "name": name, "base": base_name(name), "source": source, "location": location,
        "file": file, "nozzles": nozzles, "proof": proof, "unproven_reason": reason, "parent": parent,
        "setting_id": _first(setting_id), "filament_type": _first(ftype), "vendor": _first(vendor),
        "mtime_ns": getattr(stat, "st_mtime_ns", None), "size": getattr(stat, "st_size", None),
    }
    # Identity, not content: a rename, a different file, another parent, type, vendor or nozzle set changes
    # it; editing a temperature does not, so tuning a preset does not silently un-confirm it.
    rec["fingerprint"] = _fingerprint([
        ref, name, str(rec["setting_id"]), str(rec["filament_type"]), str(rec["vendor"]), str(parent),
        proof, ",".join(sorted(nozzles))])
    return rec


def _entry_from(base: str, records: list[dict]) -> dict:
    claim: dict[str, list[dict]] = {}
    for r in records:
        for n in r["nozzles"]:
            claim.setdefault(n, []).append(r)
    nozzles, collisions = {}, {}
    for n, recs in claim.items():
        if len(recs) == 1:
            nozzles[n] = recs[0]["name"]
        else:
            collisions[n] = sorted(r["name"] for r in recs)
            nozzles[n] = sorted(recs, key=lambda r: (r["source"] != SYSTEM, r["name"]))[0]["name"]
    first = lambda key: next((r[key] for r in sorted(records, key=lambda r: (r["source"] != SYSTEM, r["name"]))  # noqa: E731
                              if r[key]), None)
    return {"base_name": base, "records": records, "nozzles": nozzles, "collisions": collisions,
            "setting_id": first("setting_id"), "filament_type": first("filament_type"), "vendor": first("vendor"),
            "fingerprint": _fingerprint(sorted(r["fingerprint"] for r in records))}


def load(profile_dir: str | os.PathLike, user_roots: list | None = None) -> Catalog | None:
    """Read the installed presets: the system ones under `.../profiles/Snapmaker`, and the person's
    own under each `user_roots` entry (`<Orca data>/user`).

    Returns None when the system folder is missing or holds no usable preset - the caller then treats
    every mapping as unprovable rather than guessing. Read-only throughout."""
    root = Path(profile_dir)
    fdir = root / "filament"
    if not fdir.is_dir():
        return None
    docs: dict[str, dict] = {}
    for path in sorted(fdir.glob("*.json")):
        doc = _read_json(path)
        if doc and doc.get("name"):
            docs[str(doc["name"])] = doc
    # The shared library other vendors' presets inherit from: read for its settings only, never listed.
    library: dict[str, dict] = {}
    lib_dir = root.parent / "OrcaFilamentLibrary" / "filament"
    if lib_dir.is_dir():
        for path in sorted(lib_dir.glob("*.json")):
            doc = _read_json(path)
            if doc and doc.get("name"):
                library[str(doc["name"])] = doc

    def sys_lookup(name):
        return docs.get(name) or library.get(name)

    records: list[dict] = []
    for name, doc in docs.items():
        if str(doc.get("instantiation", "")).lower() != "true":
            continue
        rec = _record(doc, sys_lookup, source=SYSTEM, ref=f"system:{name}", location=None, file=f"{name}.json", stat=None)
        if rec and rec["nozzles"]:
            rec["proof"] = "listed"
            records.append(rec)
    system_count = len({r["base"] for r in records})

    user_count = 0
    for user_root in user_roots or []:
        user_root = Path(user_root)
        try:
            folders = sorted(p for p in user_root.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            continue
        for folder in folders:
            fil = folder / "filament"
            if not fil.is_dir():
                continue
            try:
                files = sorted(fil.glob("*.json"))
            except OSError:
                continue
            for path in files:
                if user_count >= _MAX_USER_PRESETS:
                    break
                doc = _read_json(path)
                if not doc:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    stat = None
                rec = _record(doc, lambda n: sys_lookup(n), source=USER, ref=f"user:{folder.name}/{path.name}",
                              location=folder.name, file=path.name, stat=stat)
                if rec:
                    records.append(rec)
                    user_count += 1
    if not records:
        return None
    by_base: dict[str, list[dict]] = {}
    for rec in records:
        by_base.setdefault(rec["base"], []).append(rec)
    entries = {b: _entry_from(b, recs) for b, recs in by_base.items()}
    vendor_json = _read_json(root.parent / "Snapmaker.json") or {}
    source = {"kind": SYSTEM, "profiles_version": _first(vendor_json.get("version")),
              "presets": system_count, "user_presets": user_count}
    return Catalog(entries, source)


def load_default(env: dict | None = None, platform: str | None = None) -> Catalog | None:
    """The catalogue of the first Orca install found (plus the person's own presets), or None."""
    for candidate in default_profile_dirs(env, platform):
        cat = load(candidate, default_user_roots(env, platform))
        if cat is not None:
            return cat
    return None
