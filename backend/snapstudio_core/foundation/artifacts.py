"""Byte identity, snapshots, derivations and the snapshot pin registry.

An artifact is identified by its bytes (`sha256:<hex>:<size>`), never by its path or size
alone. `snapshot` copies a file into a private directory, hashes the copy, and every
later analysis reads the copy; files above the cap are hashed only and must pass
`same_bytes` immediately before each analysis. A `Derivation` records how an output was
produced; only a derivation this Studio process witnessed is `local`, anything imported
is `declared`.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from . import store as _store
from .decode import Decoded, Diagnostic, ERROR, Reader, WARNING, decode_document, diag

ARTIFACT_SCHEMA = "artifact_ref/1"
DERIVATION_SCHEMA = "derivation/1"
PINS_SCHEMA = "snapshot_pins/1"

ROLES = ("original", "prepared", "generated", "sliced", "image", "settings", "lut_ref", "calibration")
INPUT_KINDS = ("image", "project", "settings", "recipe", "lut", "calibration_basis", "artifact")
WITNESSES = ("local", "declared")
HOLDER_KINDS = ("checkpoint", "passport", "assembly", "calibration", "workspace")

SAME, CHANGED, MISSING, UNREADABLE, UNVERIFIED = "same", "changed", "missing", "unreadable", "unverified"

DEFAULT_MAX_COPY_BYTES = 512 * 1024 * 1024
DEFAULT_QUOTA_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_GRACE_S = 24 * 3600
_CHUNK = 1024 * 1024
_ID_RE = re.compile(r"^sha256:([0-9a-f]{64}):(\d+)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ADMISSION_NAME = ".admission"          # lock file base inside the snapshot dir; never counted against the quota
_ADMISSION_WAIT_S = 120.0
_ADMISSION_MAX_AGE_S = 3600.0
_PIN_LOCK_WAIT_S = 30.0
_PARTIAL_RE = re.compile(r"^\.[0-9a-f]{32}\.tmp$")   # an unfinished snapshot copy
_ABSENT = object()                       # "no registry supplied": use the persisted one only

# test seams (no-ops in production)
_after_registry_read = lambda: None          # noqa: E731  sweep/eviction: registry read, nothing deleted yet
_after_quota_check = lambda: None            # noqa: E731  snapshot: quota admitted, copy not started
_on_copy_chunk = lambda path, total: None    # noqa: E731  snapshot: after each copied chunk


def make_artifact_id(sha256: str, size_bytes: int) -> str:
    return f"sha256:{sha256}:{size_bytes}"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_file(path: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                return digest.hexdigest(), total
            digest.update(chunk)
            total += len(chunk)


# -- documents ------------------------------------------------------------------
@dataclass(frozen=True)
class ByteIdentity:
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict:
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


@dataclass
class ArtifactRef:
    artifact_id: str
    role: str
    bytes: ByteIdentity
    name: str
    created_at: str
    locator: dict | None = None   # {path, mtime_ns} of the file as first seen, if any

    def to_dict(self) -> dict:
        return {"schema_version": ARTIFACT_SCHEMA, "artifact_id": self.artifact_id, "role": self.role,
                "bytes": self.bytes.to_dict(), "name": self.name,
                "locator": dict(self.locator) if self.locator else None, "created_at": self.created_at}

    @classmethod
    def create(cls, sha256: str, size_bytes: int, role: str, name: str, *, locator: dict | None = None,
               created_at: str | None = None) -> "ArtifactRef":
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        if not _SHA_RE.match(sha256) or isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise ValueError("invalid byte identity")
        return cls(make_artifact_id(sha256, size_bytes), role, ByteIdentity(sha256, size_bytes), name,
                   created_at or _utc_now_iso(), locator)

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["ArtifactRef"]:
        return decode_document(raw, ARTIFACT_SCHEMA, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "ArtifactRef":
        br = r.child(r.mapping("bytes", required=True), "bytes")
        sha = br.string("sha256")
        size = br.integer("size_bytes", minimum=0)
        if sha is not None and not _SHA_RE.match(sha):
            br.error("wrong_type", "sha256")
        artifact_id = r.string("artifact_id")
        if artifact_id and sha and size is not None and artifact_id != make_artifact_id(sha, size):
            r.error("artifact_id_mismatch", "artifact_id")
        locator = None
        if r.raw.get("locator") is not None:
            lr = r.child(r.mapping("locator"), "locator")
            locator = {"path": lr.string("path"), "mtime_ns": lr.integer("mtime_ns", minimum=0)}
        return cls(artifact_id or "", r.enum("role", ROLES) or "original",
                   ByteIdentity(sha or "", size if size is not None else 0),
                   r.string("name") or "", r.string("created_at") or "", locator)


@dataclass
class Derivation:
    derivation_id: str
    output: str
    inputs: list          # [{kind, ref}]
    producer: dict        # {tool, version|None}
    witness: str
    declared_by: str | None
    created_at: str

    @staticmethod
    def compute_id(output: str, inputs: list, producer: dict, witness: str, declared_by: str | None) -> str:
        canon = json.dumps({"output": output,
                            "inputs": sorted(({"kind": i["kind"], "ref": i["ref"]} for i in inputs),
                                             key=lambda i: (i["kind"], i["ref"])),
                            "producer": {"tool": producer.get("tool"), "version": producer.get("version")},
                            "witness": witness, "declared_by": declared_by},
                           sort_keys=True, separators=(",", ":"))
        return "drv:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:40]

    @classmethod
    def create(cls, output: str, inputs: list, producer: dict, *, witness: str = "local",
               declared_by: str | None = None, created_at: str | None = None) -> "Derivation":
        if witness not in WITNESSES:
            raise ValueError(f"unknown witness {witness!r}")
        if witness == "local" and declared_by is not None:
            raise ValueError("a locally witnessed derivation has no declarer")
        if not producer.get("tool"):
            raise ValueError("producer.tool is required")
        clean = []
        for item in inputs:
            if item.get("kind") not in INPUT_KINDS or not item.get("ref"):
                raise ValueError("invalid derivation input")
            clean.append({"kind": item["kind"], "ref": item["ref"]})
        prod = {"tool": producer["tool"], "version": producer.get("version")}
        return cls(cls.compute_id(output, clean, prod, witness, declared_by), output, clean, prod, witness,
                   declared_by, created_at or _utc_now_iso())

    def to_dict(self) -> dict:
        return {"schema_version": DERIVATION_SCHEMA, "derivation_id": self.derivation_id,
                "output": self.output, "inputs": [dict(i) for i in self.inputs],
                "producer": dict(self.producer), "witness": self.witness,
                "declared_by": self.declared_by, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, raw: Any, *, imported: bool = False) -> Decoded["Derivation"]:
        """`imported=True` (a passport, a manifest) can never yield a locally witnessed derivation."""
        return decode_document(raw, DERIVATION_SCHEMA, lambda r: cls._build(r, imported))

    @classmethod
    def _build(cls, r: Reader, imported: bool) -> "Derivation":
        inputs = []
        for i, item in enumerate(r.items("inputs", required=True)):
            ir = r.child(item, f"inputs[{i}]")
            kind, ref = ir.enum("kind", INPUT_KINDS), ir.string("ref")
            if kind and ref:
                inputs.append({"kind": kind, "ref": ref})
        pr = r.child(r.mapping("producer", required=True), "producer")
        producer = {"tool": pr.string("tool"), "version": pr.string("version", required=False)}
        witness = r.enum("witness", WITNESSES) or "declared"
        declared_by = r.string("declared_by", required=False)
        if imported and witness == "local":
            r.warn("witness_downgraded", "witness")
            witness = "declared"
        if witness == "declared" and not declared_by:
            r.warn("declared_by_missing", "declared_by")
        output = r.string("output") or ""
        stored_id = r.string("derivation_id") or ""
        if producer["tool"] and output and stored_id:
            if stored_id != cls.compute_id(output, inputs, producer, witness, declared_by) and not imported:
                r.error("derivation_id_mismatch", "derivation_id")
        recomputed = (cls.compute_id(output, inputs, producer, witness, declared_by)
                      if producer["tool"] and output else stored_id)
        if imported and stored_id and recomputed != stored_id:
            # An imported id is never trusted; it is replaced by the content-derived one, visibly.
            r.warn("derivation_id_recomputed", "derivation_id")
        return cls(recomputed, output, inputs, producer, witness, declared_by, r.string("created_at") or "")


# -- snapshots and byte checks ----------------------------------------------------
def snapshot_copy_path(ref: ArtifactRef, snapshot_dir: str) -> str | None:
    """Path of the private copy for `ref`, or None when no copy exists (not snapshotted)."""
    candidate = os.path.join(snapshot_dir, ref.bytes.sha256)
    return candidate if os.path.isfile(candidate) else None


def same_bytes(ref: ArtifactRef, path: str | None) -> str:
    """same | changed | missing | unreadable | unverified. Always hashes: size-equal replacement is detected."""
    if not isinstance(ref, ArtifactRef) or not path or not ref.bytes.sha256:
        return UNVERIFIED
    try:
        if not os.path.exists(path):
            return MISSING
        if not os.path.isfile(path):
            return UNREADABLE
        sha, size = _hash_file(path)
    except FileNotFoundError:
        return MISSING
    except OSError:
        return UNREADABLE
    return SAME if (sha == ref.bytes.sha256 and size == ref.bytes.size_bytes) else CHANGED


def snapshot(path: str, role: str, *, max_copy_bytes: int = DEFAULT_MAX_COPY_BYTES, snapshot_dir: str,
             quota_bytes: int = DEFAULT_QUOTA_BYTES, registry: Any = None, now: Any = None,
             grace_s: float = DEFAULT_GRACE_S, data_dir: str | None = None) -> Decoded[ArtifactRef]:
    """Snapshot `path`. Never raises on file problems; see the diagnostics.

    Copy -> hash the copy -> analyse the copy. A file over `max_copy_bytes` is hashed in place
    with diagnostic `not_snapshotted`; callers must `same_bytes` before each analysis.
    If the aggregate quota would be exceeded, unpinned snapshots older than `grace_s` are
    evicted oldest-first; otherwise the new snapshot is refused with `snapshot_quota_exceeded` and
    nothing referenced is deleted. `registry=None` uses the persisted pin registry (under `data_dir`),
    read and acted on while holding its writer lock; eviction happens only when it is readable.
    Admission and copy run under a cross-process lock, the copy never exceeds `max_copy_bytes` or the
    quota even if the source grows (a source that grows past the copy cap is hashed in place instead).
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    fail = lambda code: Decoded(ARTIFACT_SCHEMA, None, [diag(code, "path", ERROR)], False)  # noqa: E731
    try:
        before = os.stat(path)
    except FileNotFoundError:
        return fail("file_missing")
    except OSError:
        return fail("file_unreadable")
    if not os.path.isfile(path):
        return fail("not_a_file")
    name = os.path.basename(path)
    locator = {"path": os.path.abspath(path), "mtime_ns": before.st_mtime_ns}
    diagnostics: list[Diagnostic] = []

    def hash_in_place() -> Decoded[ArtifactRef]:
        try:
            sha, size = _hash_file(path)
        except OSError:
            return fail("file_unreadable")
        diagnostics.append(diag("not_snapshotted", "path", WARNING))
        return Decoded(ARTIFACT_SCHEMA, ArtifactRef.create(sha, size, role, name, locator=locator),
                       diagnostics, True)

    if before.st_size > max_copy_bytes:
        return hash_in_place()

    try:
        os.makedirs(snapshot_dir, exist_ok=True)
    except OSError:
        return fail("snapshot_dir_unavailable")
    try:
        admission = _store.exclusive(os.path.join(snapshot_dir, _ADMISSION_NAME), wait_s=_ADMISSION_WAIT_S,
                                     max_age_s=_ADMISSION_MAX_AGE_S)
        with admission:
            outcome = _admit_and_copy(path, snapshot_dir, before.st_size, max_copy_bytes, quota_bytes,
                                      registry, now, grace_s, data_dir)
    except _store.StoreError:
        return fail("snapshot_dir_unavailable")
    if outcome == "over_copy_cap":
        return hash_in_place()
    if isinstance(outcome, str):
        return fail(outcome)
    sha, size = outcome
    try:
        after = os.stat(path)
        if after.st_mtime_ns != before.st_mtime_ns or after.st_size != before.st_size:
            diagnostics.append(diag("source_changed_during_copy", "path", WARNING))
    except OSError:
        diagnostics.append(diag("source_changed_during_copy", "path", WARNING))
    return Decoded(ARTIFACT_SCHEMA, ArtifactRef.create(sha, size, role, name, locator=locator), diagnostics, True)


def _admit_and_copy(path: str, snapshot_dir: str, expected: int, max_copy_bytes: int, quota_bytes: int,
                    registry: Any, now: Any, grace_s: float, data_dir: str | None) -> Any:
    """Under the admission lock: quota check (with eviction), bounded copy, hash. Returns (sha, size) or an error code."""
    try:
        if _dir_bytes(snapshot_dir) + expected > quota_bytes:
            _evict_for_space(snapshot_dir, registry, expected, quota_bytes, now, grace_s, data_dir)
            if _dir_bytes(snapshot_dir) + expected > quota_bytes:
                return "snapshot_quota_exceeded"
        _after_quota_check()
        room = quota_bytes - _dir_bytes(snapshot_dir)
    except OSError:
        return "snapshot_dir_unavailable"               # cannot measure the quota: refuse admission
    tmp = os.path.join(snapshot_dir, f".{uuid.uuid4().hex}.tmp")
    try:
        copied = 0
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > max_copy_bytes:
                    return "over_copy_cap"
                if copied > room:
                    return "snapshot_quota_exceeded"
                dst.write(chunk)
                _on_copy_chunk(path, copied)
            dst.flush()
            os.fsync(dst.fileno())
        sha, size = _hash_file(tmp)
        final = os.path.join(snapshot_dir, sha)
        if os.path.isfile(final) and os.path.getsize(final) == size:
            os.remove(tmp)
            os.utime(final)          # re-snapshotting renews the grace period of an existing copy
        else:
            os.replace(tmp, final)
        return sha, size
    except OSError:
        return "file_unreadable"
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _dir_bytes(directory: str) -> int:
    """Bytes held in the snapshot directory. Raises OSError when it cannot be measured (fail closed)."""
    total = 0
    with os.scandir(directory) as it:
        for entry in it:
            if entry.name.startswith(_ADMISSION_NAME):
                continue
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                continue                                    # removed while we counted
    return total


# -- pin registry -----------------------------------------------------------------
class PinRegistry:
    """Which artifacts are still referenced, and by whom. Persistence is wired by the store layer."""

    def __init__(self) -> None:
        self._pins: dict[tuple, str] = {}
        self._lock = threading.Lock()

    def pin(self, artifact_id: str, holder_kind: str, holder_id: str) -> None:
        if not _ID_RE.match(artifact_id or ""):
            raise ValueError("invalid artifact_id")
        if holder_kind not in HOLDER_KINDS or not holder_id:
            raise ValueError("invalid pin holder")
        with self._lock:
            self._pins.setdefault((artifact_id, holder_kind, holder_id), _utc_now_iso())

    def unpin(self, artifact_id: str, holder_kind: str, holder_id: str) -> bool:
        with self._lock:
            return self._pins.pop((artifact_id, holder_kind, holder_id), None) is not None

    def holders(self, artifact_id: str) -> list[tuple]:
        with self._lock:
            return sorted((k, i) for (a, k, i) in self._pins if a == artifact_id)

    def holder_artifacts(self, holder_kind: str, holder_id: str) -> list[str]:
        with self._lock:
            return sorted(a for (a, k, i) in self._pins if k == holder_kind and i == holder_id)

    def is_pinned(self, artifact_id: str) -> bool:
        return bool(self.holders(artifact_id))

    def pinned_hashes(self) -> set:
        with self._lock:
            return {_ID_RE.match(a).group(1) for (a, _k, _i) in self._pins}

    def to_dict(self) -> dict:
        with self._lock:
            pins = [{"artifact_id": a, "holder_kind": k, "holder_id": i, "pinned_at": t}
                    for (a, k, i), t in sorted(self._pins.items())]
        return {"schema_version": PINS_SCHEMA, "pins": pins}

    @classmethod
    def from_dict(cls, raw: Any) -> Decoded["PinRegistry"]:
        return decode_document(raw, PINS_SCHEMA, cls._build)

    @classmethod
    def _build(cls, r: Reader) -> "PinRegistry":
        registry = cls()
        for i, item in enumerate(r.items("pins")):
            pr = r.child(item, f"pins[{i}]")
            artifact_id = pr.string("artifact_id")
            kind = pr.enum("holder_kind", HOLDER_KINDS)
            holder = pr.string("holder_id")
            stamp = pr.string("pinned_at", required=False) or _utc_now_iso()
            if artifact_id and not _ID_RE.match(artifact_id):
                pr.error("wrong_type", "artifact_id")
            elif artifact_id and kind and holder:
                registry._pins[(artifact_id, kind, holder)] = stamp
        return registry


_DEFAULT_REGISTRY = PinRegistry()


def default_registry() -> PinRegistry:
    return _DEFAULT_REGISTRY


def pin_in_memory(artifact_id: str, holder_kind: str, holder_id: str, *,
                  registry: PinRegistry | None = None) -> None:
    """Pin in a process-local registry only. Nothing is persisted, so a sweep does not see it."""
    (registry or _DEFAULT_REGISTRY).pin(artifact_id, holder_kind, holder_id)


def unpin_in_memory(artifact_id: str, holder_kind: str, holder_id: str, *,
                    registry: PinRegistry | None = None) -> bool:
    return (registry or _DEFAULT_REGISTRY).unpin(artifact_id, holder_kind, holder_id)


def _readable_registry(registry: Any) -> PinRegistry | None:
    if isinstance(registry, Decoded):
        registry = registry.value
    return registry if isinstance(registry, PinRegistry) else None


def _unpinned_old_snapshots(snapshot_dir: str, registry: PinRegistry, now: Any, grace_s: float) -> list[tuple]:
    from .observations import parse_time  # local import: observations does not depend on artifacts
    stamp = parse_time(now) if now is not None else datetime.datetime.now(datetime.timezone.utc)
    cutoff = (stamp or datetime.datetime.now(datetime.timezone.utc)).timestamp() - grace_s
    pinned = registry.pinned_hashes()
    out = []
    try:
        with os.scandir(snapshot_dir) as it:
            for entry in it:
                if not (_SHA_RE.match(entry.name) and entry.is_file(follow_symlinks=False)):
                    continue
                info = entry.stat(follow_symlinks=False)
                if entry.name not in pinned and info.st_mtime <= cutoff:
                    out.append((info.st_mtime, entry.path, info.st_size))
    except OSError:
        return []
    return sorted(out)


def _protective_registry(supplied: Any, data_dir: str | None) -> PinRegistry | None:
    """Pins that protect snapshots from deletion. Call while holding the pin-registry writer lock.

    Always includes the CURRENT persisted registry; a supplied registry only adds to it and can never
    reduce protection. None when either source is unreadable (the caller then deletes nothing).
    """
    persisted = _readable_registry(load_pin_registry(data_dir))
    if persisted is None:
        return None
    if supplied is _ABSENT or supplied is None:
        return persisted
    extra = _readable_registry(supplied)
    if extra is None:
        return None
    merged = PinRegistry()
    with persisted._lock:
        merged._pins.update(persisted._pins)
    with extra._lock:
        merged._pins.update(extra._pins)
    return merged


def _evict_for_space(snapshot_dir: str, registry: Any, needed: int, quota: int, now: Any, grace_s: float,
                     data_dir: str | None = None) -> list:
    """Evict unpinned old snapshots, deciding from the persisted registry read under its writer lock.

    A supplied `registry` is additive only. Callers hold the admission lock (order: admission, then pins).
    """
    try:
        with _store.document_lock(PIN_STORE_NAME, data_dir=data_dir, wait_s=_PIN_LOCK_WAIT_S):
            return _evict_with(snapshot_dir, _protective_registry(registry, data_dir), needed, quota, now, grace_s)
    except _store.StoreError:
        return []


def _evict_with(snapshot_dir: str, reg: PinRegistry | None, needed: int, quota: int, now: Any,
                grace_s: float) -> list:
    if reg is None:
        return []
    _after_registry_read()
    removed = []
    for _mtime, path, _size in _unpinned_old_snapshots(snapshot_dir, reg, now, grace_s):
        try:
            if _dir_bytes(snapshot_dir) + needed <= quota:
                break
            os.remove(path)
            removed.append(os.path.basename(path))
        except OSError:
            continue
    return removed


# -- persisted pins ---------------------------------------------------------------
# The pin file is the source of truth. Every change is a read-modify-write of one document with
# revision checking, so two processes cannot lose each other's pins. A holder pins BEFORE it
# persists its own reference (`pin_before_persist`) and unpins when it deletes or supersedes
# that reference (`unpin_holder`, `replace_holder_pins`). Sweep and quota eviction use the same
# rule: only unpinned snapshots older than the grace period, and nothing at all when the pin
# file cannot be read.
PIN_STORE_NAME = "snapshot_pins"
_PIN_RETRIES = 5


def load_pin_registry(data_dir: str | None = None) -> Decoded["PinRegistry"]:
    """The persisted registry. A missing file is an empty, valid registry; an unreadable one has value None."""
    doc = _store.read_json(PIN_STORE_NAME, schema=PIN_STORE_NAME, version=1, data_dir=data_dir, rename_damaged=False)
    if doc.value is None:
        return Decoded(doc.schema_version, None, doc.diagnostics, False, raw=doc.raw)
    if doc.value.get("missing"):
        return Decoded(PINS_SCHEMA, PinRegistry(), [], True)
    return PinRegistry.from_dict(doc.value)


def _modify_pins(change: Any, data_dir: str | None) -> Any:
    """Apply `change(registry) -> result` to the persisted registry and save it. Raises if unreadable.

    The read-modify-write runs under the registry's cross-process writer lock, the same lock a sweep or
    quota eviction holds while it reads the registry and deletes, so a pin can never slip between them.
    """
    with _store.document_lock(PIN_STORE_NAME, data_dir=data_dir, wait_s=_PIN_LOCK_WAIT_S):
        doc = _store.read_json(PIN_STORE_NAME, schema=PIN_STORE_NAME, version=1, data_dir=data_dir,
                               rename_damaged=False)
        if doc.value is None:
            code = doc.diagnostics[0].code if doc.diagnostics else "unreadable"
            if code == "newer_schema_version":
                raise _store.StoreVersionError("pin registry was written by a newer version")
            raise _store.StoreError(f"pin registry unreadable ({code})")
        revision = doc.value["revision"]
        if doc.value.get("missing"):
            registry = PinRegistry()
        else:
            decoded = PinRegistry.from_dict(doc.value)
            if decoded.value is None:
                raise _store.StoreError("pin registry unreadable (invalid contents)")
            registry = decoded.value
        result = change(registry)
        body = registry.to_dict()
        body.pop("schema_version", None)
        _store.write_json(PIN_STORE_NAME, body, expected_revision=revision, schema=PIN_STORE_NAME,
                          version=1, data_dir=data_dir, lock_held=True)
        return result


def pin(artifact_id: str, holder_kind: str, holder_id: str, *, data_dir: str | None = None) -> None:
    """Pin `artifact_id` for a holder, persisted (revision-checked) in the pin store."""
    _modify_pins(lambda reg: reg.pin(artifact_id, holder_kind, holder_id), data_dir)


def unpin(artifact_id: str, holder_kind: str, holder_id: str, *, data_dir: str | None = None) -> bool:
    """Remove one persisted pin. Returns whether it existed."""
    return _modify_pins(lambda reg: reg.unpin(artifact_id, holder_kind, holder_id), data_dir)


pin_persisted = pin          # earlier name, kept so existing callers keep working
unpin_persisted = unpin


def unpin_holder(holder_kind: str, holder_id: str, *, data_dir: str | None = None) -> int:
    """Drop every pin a holder has. Call when the holder (checkpoint, passport, ...) is deleted."""
    def change(reg: PinRegistry) -> int:
        owned = reg.holder_artifacts(holder_kind, holder_id)
        for artifact_id in owned:
            reg.unpin(artifact_id, holder_kind, holder_id)
        return len(owned)
    return _modify_pins(change, data_dir)


def replace_holder_pins(holder_kind: str, holder_id: str, artifact_ids: Any, *, data_dir: str | None = None) -> dict:
    """Make the holder's pins exactly `artifact_ids` in one save (new pins and removals together).

    Call when a holder is superseded by a newer version of itself. Returns {added, removed}.
    """
    wanted = sorted(set(artifact_ids))

    def change(reg: PinRegistry) -> dict:
        have = set(reg.holder_artifacts(holder_kind, holder_id))
        for artifact_id in wanted:
            reg.pin(artifact_id, holder_kind, holder_id)
        gone = sorted(have - set(wanted))
        for artifact_id in gone:
            reg.unpin(artifact_id, holder_kind, holder_id)
        return {"added": sorted(set(wanted) - have), "removed": gone}
    return _modify_pins(change, data_dir)


def pin_before_persist(artifact_ids: Any, holder_kind: str, holder_id: str, persist: Any, *,
                       data_dir: str | None = None) -> Any:
    """Pin first, then run `persist()` (which writes the holder's own reference). Returns its result.

    The order matters: a crash between the two leaves a harmless extra pin, never a persisted
    reference to a snapshot that a sweep could delete. If `persist` raises, the pins this call
    added are removed again and the error propagates.
    """
    ids = sorted(set(artifact_ids))

    def add(reg: PinRegistry) -> list:
        fresh = [a for a in ids if (holder_kind, holder_id) not in reg.holders(a)]
        for artifact_id in ids:
            reg.pin(artifact_id, holder_kind, holder_id)
        return fresh

    added = _modify_pins(add, data_dir)
    try:
        return persist()
    except BaseException:
        if added:
            def rollback(reg: PinRegistry) -> None:
                for artifact_id in added:
                    reg.unpin(artifact_id, holder_kind, holder_id)
            try:
                _modify_pins(rollback, data_dir)
            except _store.StoreError:
                pass                       # leave the pins: a stray pin is safe, a missing one is not
        raise


def sweep_snapshots_persisted(snapshot_dir: str, *, data_dir: str | None = None, now: Any = None,
                              grace_s: float = DEFAULT_GRACE_S, dry_run: bool = False) -> dict:
    """Sweep using the persisted registry, read and acted on while holding its writer lock.

    Locks are taken admission first, then pins (the order `snapshot` uses). A snapshot copy renews the
    grace period under the admission lock, so a sweep never deletes a copy that was just renewed. Pin
    creation takes the pin lock, so no pin can be added between the registry read and the deletions.
    """
    return _sweep(snapshot_dir, _ABSENT, now, grace_s, dry_run, data_dir)


def sweep_snapshots(snapshot_dir: str, registry: Any, *, now: Any = None, grace_s: float = DEFAULT_GRACE_S,
                    dry_run: bool = False, data_dir: str | None = None) -> dict:
    """Delete unpinned snapshots older than the grace period. Skips entirely if a registry is unreadable.

    `registry` is additive: the persisted registry (under `data_dir`) is always read under its writer
    lock and also protects, so a stale or empty `registry` can never cause a pinned snapshot to go.
    """
    return _sweep(snapshot_dir, registry, now, grace_s, dry_run, data_dir)


def _sweep(snapshot_dir: str, registry: Any, now: Any, grace_s: float, dry_run: bool, data_dir: str | None) -> dict:
    unreadable = {"deleted": [], "skipped_reason": "pin_registry_unreadable"}
    if registry is not _ABSENT and _readable_registry(registry) is None:
        return unreadable
    if not os.path.isdir(snapshot_dir):
        return {"deleted": [], "skipped_reason": None, "partials_removed": []}
    try:
        with _store.exclusive(os.path.join(snapshot_dir, _ADMISSION_NAME), wait_s=_ADMISSION_WAIT_S):
            try:
                with _store.document_lock(PIN_STORE_NAME, data_dir=data_dir, wait_s=_PIN_LOCK_WAIT_S):
                    reg = _protective_registry(registry, data_dir)
                    if reg is None:
                        return unreadable
                    _after_registry_read()
                    return _sweep_locked(snapshot_dir, reg, now, grace_s, dry_run)
            except _store.StoreError:
                return {"deleted": [], "skipped_reason": "pin_registry_locked"}
    except _store.StoreError:
        return {"deleted": [], "skipped_reason": "snapshot_dir_locked"}


def _sweep_locked(snapshot_dir: str, reg: PinRegistry, now: Any, grace_s: float, dry_run: bool) -> dict:
    """Admission and pin locks held. Re-checks mtime right before each removal."""
    from .observations import parse_time
    stamp = parse_time(now) if now is not None else datetime.datetime.now(datetime.timezone.utc)
    cutoff = (stamp or datetime.datetime.now(datetime.timezone.utc)).timestamp() - grace_s
    deleted, partials = [], []
    for _mtime, path, _size in _unpinned_old_snapshots(snapshot_dir, reg, now, grace_s):
        if not dry_run:
            try:
                if os.stat(path).st_mtime > cutoff:
                    continue                                # renewed since the scan
                os.remove(path)
            except OSError:
                continue
        deleted.append(os.path.basename(path))
    try:
        with os.scandir(snapshot_dir) as it:
            stale = [(e.path, e.name) for e in it if _PARTIAL_RE.match(e.name) and e.is_file(follow_symlinks=False)]
    except OSError:
        stale = []
    for path, name in stale:                                # partial copies left by a crashed snapshot
        try:
            if os.stat(path).st_mtime > cutoff:
                continue
            if not dry_run:
                os.remove(path)
        except OSError:
            continue
        partials.append(name)
    return {"deleted": deleted, "skipped_reason": None, "partials_removed": partials}
