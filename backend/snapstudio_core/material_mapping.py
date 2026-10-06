"""What Studio remembers about which installed Orca preset a spool maps to.

A mapping answers "this spool (or this kind of spool) is that Snapmaker Orca preset".
It is local only, holds no credentials and no provider secrets, and it is never
trusted blindly: every use is checked against the installed catalogue again, and a
mapping whose preset is gone, renamed, or no longer the same preset comes back as
``needs_confirmation`` instead of being applied.

Two scopes, and the first one found wins:

* ``spool``     — one exact spool: ``(provider, spool id)``.
* ``signature`` — a reusable kind of spool: ``(provider, vendor, material family, subtype)``.

The preset is stored by BASE NAME plus the fingerprint, profiles version and catalogue
fingerprint seen when the person confirmed it — enough to notice that the name no
longer identifies the same installed preset. ``filament_id`` and ``setting_id`` are
never the key.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from . import paths, preset_catalog
from .preset_catalog import PROVEN, NEEDS_CONFIRMATION, NO_MATCH

SCHEMA = 1
FILE_NAME = "material-mappings.json"

SCOPE_SPOOL = "spool"
SCOPE_SIGNATURE = "signature"

SOURCE_SAVED_SPOOL = "saved_spool"
SOURCE_SAVED_SIGNATURE = "saved_signature"
SOURCE_EXACT_NAME = "exact_name"
SOURCE_MANUAL = "manual"
SOURCE_NONE = "none"

ORIGINS = (SOURCE_EXACT_NAME, SOURCE_MANUAL)

_MAX_TEXT = 200


def _text(value) -> str:
    return " ".join(str(value or "").split())[:_MAX_TEXT]


def _norm(value) -> str:
    return _text(value).casefold()


def signature(vendor, material, subtype) -> dict:
    """The reusable key of a kind of spool. Case and spacing do not matter."""
    return {"vendor": _norm(vendor), "family": _norm(material), "subtype": _norm(subtype)}


def default_path(explicit_dir: str | None = None) -> str:
    return os.path.join(paths.data_dir(explicit_dir), FILE_NAME)


class Store:
    """The mapping file. Reads never raise; a damaged file reads as empty."""

    def __init__(self, path: str | None = None):
        self.path = path or default_path()

    def _read(self) -> tuple[list[dict], bool]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return [], False
        except (OSError, ValueError):
            return [], True
        rows = data.get("mappings") if isinstance(data, dict) else None
        if not isinstance(rows, list) or (isinstance(data, dict) and data.get("schema") != SCHEMA):
            return [], True
        return [r for r in rows if isinstance(r, dict) and r.get("preset_base")], False

    def all(self) -> list[dict]:
        return self._read()[0]

    def find(self, provider: str, spool_id, sig: dict | None) -> tuple[dict | None, str]:
        """The spool-scoped mapping if there is one, else the signature-scoped one."""
        rows = self.all()
        sid = _text(spool_id)
        if sid:
            for r in rows:
                if r.get("scope") == SCOPE_SPOOL and r.get("provider") == provider \
                        and r.get("spool_id") == sid:
                    return r, SOURCE_SAVED_SPOOL
        if sig and any(sig.values()):
            for r in rows:
                if r.get("scope") == SCOPE_SIGNATURE and r.get("provider") == provider \
                        and r.get("signature") == sig:
                    return r, SOURCE_SAVED_SIGNATURE
        return None, SOURCE_NONE

    def put(self, *, scope: str, provider: str, preset: dict, origin: str,
            spool_id=None, sig: dict | None = None, catalog=None, accept_unproven: bool = False) -> dict:
        """Remember a confirmed mapping. `preset` is a :meth:`Catalog.evaluate` result: PROVEN, or - only
        when the person said so (`accept_unproven`) - a user preset Studio could not itself tell is for
        the U1 (``confirmable``). The latter is stored as ``user_confirmed`` and is re-checked on every use."""
        if scope not in (SCOPE_SPOOL, SCOPE_SIGNATURE):
            raise ValueError("scope must be 'spool' or 'signature'")
        if origin not in ORIGINS:
            raise ValueError("origin must be 'exact_name' or 'manual'")
        proven = preset.get("status") == PROVEN
        confirmable = (preset.get("status") == NEEDS_CONFIRMATION and bool(preset.get("confirmable"))
                       and accept_unproven)
        if not (proven or confirmable) or not preset.get("base_name"):
            raise ValueError("only a proven installed preset, or one of your own presets you confirmed, can be remembered")
        row = {
            "source": preset.get("source"),
            # The exact installed record, whether Orca's or the person's: a mapping never falls back to a
            # same-name sibling. (A system preset's file differs by nozzle; Prepare writes one nozzle.)
            "ref": preset.get("ref"),
            "proof": "evidence" if proven else "user_confirmed",
            "scope": scope,
            "provider": _text(provider),
            "preset_base": preset["base_name"],
            "fingerprint": preset.get("fingerprint"),
            "origin": origin,
            "profiles_version": (catalog.source.get("profiles_version") if catalog else None),
            "catalog_fingerprint": (catalog.fingerprint if catalog else None),
            "confirmed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if scope == SCOPE_SPOOL:
            if not _text(spool_id):
                raise ValueError("a spool mapping needs a spool id")
            row["spool_id"] = _text(spool_id)
        else:
            if not sig or not any(sig.values()):
                raise ValueError("a signature mapping needs vendor, material or subtype")
            row["signature"] = {k: _norm(v) for k, v in sig.items()}
        rows, damaged = self._read()
        rows = [r for r in rows if not _same_key(r, row)] + [row]
        self._write(rows, keep_damaged=damaged)
        return row

    def remove(self, *, scope: str, provider: str, spool_id=None, sig: dict | None = None) -> bool:
        probe = {"scope": scope, "provider": _text(provider)}
        if scope == SCOPE_SPOOL:
            probe["spool_id"] = _text(spool_id)
        else:
            probe["signature"] = sig
        rows, damaged = self._read()
        kept = [r for r in rows if not _same_key(r, probe)]
        if len(kept) == len(rows):
            return False
        self._write(kept, keep_damaged=damaged)
        return True

    def _write(self, rows: list[dict], *, keep_damaged: bool) -> None:
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        if keep_damaged and os.path.exists(self.path):
            try:
                os.replace(self.path, self.path + ".damaged")
            except OSError:
                pass
        fd, tmp = tempfile.mkstemp(prefix=".mappings-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"schema": SCHEMA, "mappings": rows}, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _same_key(a: dict, b: dict) -> bool:
    if a.get("scope") != b.get("scope") or a.get("provider") != b.get("provider"):
        return False
    if a.get("scope") == SCOPE_SPOOL:
        return a.get("spool_id") == b.get("spool_id")
    return a.get("signature") == b.get("signature")


def resolve(catalog, store: Store | None, provider: str, spool: dict, nozzle: str) -> dict:
    """The Orca preset for one spool, with how it was found and how far to trust it.

    Order: a remembered spool mapping, a remembered signature mapping, then the
    provider's own slicer filament name (SpoolEase) when it names exactly one
    installed preset — which is only ever ``needs_confirmation``. Nothing is chosen
    between presets; an unresolved spool comes back ``no_match`` so the person picks one.
    """
    out = {"status": NO_MATCH, "match_source": SOURCE_NONE, "preset_name": None,
           "base_name": None, "reason": "", "candidates": [], "fingerprint": None,
           "stale": False, "catalog_missing": catalog is None}
    if catalog is None:
        out["reason"] = ("Snapmaker Orca's installed filament presets could not be read, so no "
                         "preset can be proven.")
        return out
    sig = signature(spool.get("vendor"), spool.get("material"), spool.get("subtype"))
    saved, source = (store.find(provider, spool.get("id"), sig) if store else (None, SOURCE_NONE))
    if saved:
        found = catalog.verify(saved["preset_base"], saved.get("fingerprint"), nozzle, saved.get("ref"),
                               saved.get("proof"), saved.get("source"))
        out.update(_carry(found))
        out["match_source"] = SOURCE_NONE if found["status"] == NO_MATCH else source
        if found["status"] == NO_MATCH:
            out["reason"] = ("The preset you confirmed earlier is not available for this nozzle "
                             "or is no longer installed. " + found["reason"])
        return out
    named = _text(spool.get("slicer_filament"))
    if named:
        found = catalog.evaluate(named, nozzle)
        if found["status"] != NO_MATCH:
            # The provider's text is a claim, not a decision. Even when it names exactly one
            # installed preset it stays unconfirmed until the person confirms it, which saves
            # a mapping; only a saved mapping proves it.
            out.update(_carry(found), match_source=SOURCE_EXACT_NAME)
            if out["status"] == PROVEN:
                out["status"] = NEEDS_CONFIRMATION
                out["reason"] = ("The provider names this installed preset. Confirm it to use "
                                 "it and to remember it.")
            return out
        out["reason"] = (f"The provider names “{named}” as its slicer filament, but "
                         + found["reason"][0].lower() + found["reason"][1:])
        return out
    out["reason"] = "No preset has been chosen for this spool yet."
    return out


def _carry(found: dict) -> dict:
    keys = ("status", "reason", "preset_name", "base_name", "candidates", "fingerprint", "source", "ref",
            "proof", "choices")
    out = {k: found.get(k) for k in keys}
    out["choices"] = out["choices"] or []
    out["confirmable"] = bool(found.get("confirmable"))
    out["stale"] = bool(found.get("stale"))
    return out
