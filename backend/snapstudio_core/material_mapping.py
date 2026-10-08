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

import contextlib
import errno
import json
import os
import tempfile
import threading
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


# The API serves requests on threads; a read-modify-replace of the file must not interleave with another,
# or a save could be lost or a forgotten mapping come back. One process owns the file, so one lock is enough.
_WRITE_LOCK = threading.RLock()
_HELD = threading.local()      # per-thread nesting depth, so only the outermost entry takes the OS lock
_ABSENT = object()            # 'no expectation sent' - distinct from 'expected null'


@contextlib.contextmanager
def _exclusive(path: str):
    """Hold the thread lock AND an OS file lock for the mapping file's folder, so two running copies of
    Studio (each with its own engine process) cannot interleave a read-modify-replace either. The lock is
    on a side file, never on the data file, which is replaced atomically."""
    with _WRITE_LOCK:
        depth = getattr(_HELD, "depth", 0)
        if depth:                      # already inside: a second handle's byte lock would wait for ourselves
            _HELD.depth = depth + 1
            try:
                yield
            finally:
                _HELD.depth = depth
            return
        folder = os.path.dirname(path) or "."
        os.makedirs(folder, exist_ok=True)
        fh = open(os.path.join(folder, ".material-mappings.lock"), "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                for attempt in range(6):
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)   # blocks ~10 s per try, then raises
                        break
                    except OSError:
                        if attempt == 5:       # a minute without the lock is not contention: say so, never hang
                            raise
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            _HELD.depth = 1
            yield
        finally:
            _HELD.depth = 0
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            fh.close()


class StaleMapping(ValueError):
    """The saved mapping is no longer the one the person was shown."""


class MappingFileUnavailable(RuntimeError):
    """The mapping file exists but could not be read, so nothing was changed.

    This is not corruption: nothing was learned about the file's content. A save or a forget that
    cannot read the current mappings must stop, because writing from an unread state would replace
    mappings it never saw."""


# Access failures that are expected to pass on their own: another program (antivirus, a sync client,
# another Studio) holds the file for a moment. Everything else that fails to read is permanent.
_TRANSIENT_ERRNO = {errno.EACCES, errno.EBUSY, errno.EAGAIN, errno.EINTR}
_TRANSIENT_WINERROR = {5, 32, 33}          # access denied, sharing violation, lock violation
_READ_ATTEMPTS = 5
_READ_BACKOFF_SECONDS = (0.02, 0.04, 0.08, 0.16)       # about 0.3 s in all, then give up


def _is_transient(exc: OSError) -> bool:
    if isinstance(exc, (IsADirectoryError, NotADirectoryError, FileNotFoundError)):
        return False
    return (isinstance(exc, PermissionError) or exc.errno in _TRANSIENT_ERRNO
            or getattr(exc, "winerror", None) in _TRANSIENT_WINERROR)


class Store:
    """The mapping file. Reads never raise; a damaged file reads as empty."""

    def __init__(self, path: str | None = None):
        self.path = path or default_path()

    def _read_checked(self) -> tuple[list[dict], bool]:
        """The saved mappings and whether the file is confirmed damaged.

        - missing file: no mappings, not damaged
        - read in full but not valid (bad JSON, bytes that are not text, wrong schema): no mappings, DAMAGED
        - cannot be read (access denied, in use, a folder where the file should be, an I/O error): after a
          short bounded retry for the transient ones only, raises :class:`MappingFileUnavailable`. It is never
          reported as damaged, because nothing was read.
        """
        data = None
        for attempt in range(_READ_ATTEMPTS):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                break
            except FileNotFoundError:
                return [], False
            except ValueError:                      # includes JSONDecodeError and UnicodeDecodeError: content was read
                return [], True
            except OSError as exc:
                if _is_transient(exc) and attempt < _READ_ATTEMPTS - 1:
                    time.sleep(_READ_BACKOFF_SECONDS[attempt])
                    continue
                raise MappingFileUnavailable(
                    "Studio could not read its saved mappings just now"
                    + (" (the file may be in use by another program)" if _is_transient(exc) else "")
                    + ". Nothing was changed. Try again in a moment.") from exc
        rows = data.get("mappings") if isinstance(data, dict) else None
        if not isinstance(rows, list) or (isinstance(data, dict) and data.get("schema") != SCHEMA):
            return [], True
        return [r for r in rows if isinstance(r, dict) and r.get("preset_base")], False

    def _read(self) -> tuple[list[dict], bool]:
        """For callers that only look: an unreadable file reads as no mappings for this call (and is not
        marked damaged), so a momentary access failure never changes anything on disk."""
        try:
            return self._read_checked()
        except MappingFileUnavailable:
            return [], False

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
        with _exclusive(self.path):
            rows, damaged = self._read_checked()
            rows = [r for r in rows if not _same_key(r, row)] + [row]
            self._write(rows, keep_damaged=damaged)
        return row

    def remove(self, *, scope: str, provider: str, spool_id=None, sig: dict | None = None,
               expect_preset_base=_ABSENT, expect_ref=_ABSENT, expect_fingerprint=_ABSENT) -> bool:
        """Forget one mapping. With the `expect_*` values (the preset, its installed record and its
        fingerprint, as the person was shown them), only if the saved mapping is still exactly that: one
        replaced since raises :class:`StaleMapping` and is left alone."""
        probe = {"scope": scope, "provider": _text(provider)}
        if scope == SCOPE_SPOOL:
            probe["spool_id"] = _text(spool_id)
        else:
            probe["signature"] = sig
        expected = {k: v for k, v in (("preset_base", expect_preset_base), ("ref", expect_ref),
                                      ("fingerprint", expect_fingerprint)) if v is not _ABSENT}
        with _exclusive(self.path):
            rows, damaged = self._read_checked()
            hit = [r for r in rows if _same_key(r, probe)]
            if not hit:
                return False
            if any(r.get(k) != v for r in hit for k, v in expected.items()):
                raise StaleMapping("That saved mapping has changed since it was shown. Nothing was forgotten.")
            kept = [r for r in rows if not _same_key(r, probe)]
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
            for attempt in range(20):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    # Windows refuses to replace a file another thread has open for reading; wait it out.
                    if attempt == 19:
                        raise
                    time.sleep(0.025)
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
        # The saved row exactly as stored: what a later Forget compares against, so a mapping replaced
        # in the meantime is never removed by a confirmation that described the old one.
        out["saved"] = {k: saved.get(k) for k in ("preset_base", "ref", "fingerprint")}
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
