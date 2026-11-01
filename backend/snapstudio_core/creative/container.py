"""Bounded, read-only 3MF container inspection.

Unknown members are represented only by their archive names and SHA-256 digests;
their payloads are never interpreted or rewritten.
"""
from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
import zlib
from dataclasses import dataclass
from xml.etree import ElementTree

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class ContainerError(ValueError):
    """The archive is malformed, unsafe, or exceeds reader limits."""


@dataclass(frozen=True)
class MemberDigest:
    name: str
    sha256: str


@dataclass(frozen=True)
class ThreeMFManifest:
    members: tuple[MemberDigest, ...]
    understood_parts: tuple[str, ...]
    passed_through: tuple[MemberDigest, ...]
    model_xml: bytes
    project_settings: dict | None

    def to_dict(self) -> dict:
        """Serialize member identity only; original archive payloads stay untouched."""
        return {"schema_version": "creative_3mf_manifest/1",
                "members": [{"name": item.name, "sha256": item.sha256} for item in self.members],
                "understood_parts": list(self.understood_parts),
                "passed_through": [{"name": item.name, "sha256": item.sha256} for item in self.passed_through]}


def _safe_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        raise ContainerError("unsafe_member_name")
    if ".." in name.split("/"):
        raise ContainerError("unsafe_member_name")
    normalized = posixpath.normpath(name)
    if normalized in (".", "..") or normalized.startswith("../") or ":" in normalized.split("/")[0]:
        raise ContainerError("unsafe_member_name")
    return normalized


def _check_model(xml: bytes) -> None:
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ContainerError("unsafe_xml")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ContainerError("bad_xml") from exc
    if root.tag != f"{{{CORE_NS}}}model":
        raise ContainerError("unsupported_3mf_version")


def read_3mf(data: bytes) -> ThreeMFManifest:
    """Validate a small 3MF ZIP and return an immutable identity manifest.

    Container shape reference: captured FullSpectrum packaging notes list the
    3MF ZIP members and Metadata config paths at lines 13-38 and 74-76.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ContainerError("archive_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ContainerError("bad_zip") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ContainerError("too_many_members")
        names: set[str] = set()
        total = 0
        blobs: dict[str, bytes] = {}
        for info in infos:
            name = _safe_name(info.filename)
            if name in names:
                raise ContainerError("duplicate_member")
            names.add(name)
            if info.is_dir():
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                raise ContainerError("member_too_large")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ContainerError("archive_expanded_too_large")
            if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                raise ContainerError("compression_ratio_exceeded")
            try:
                blob = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile, OSError, NotImplementedError, zlib.error) as exc:
                raise ContainerError("bad_zip_member") from exc
            if len(blob) != info.file_size:
                raise ContainerError("truncated_member")
            blobs[name] = blob
    model = blobs.get("3D/3dmodel.model")
    if model is None:
        raise ContainerError("missing_model")
    _check_model(model)
    settings = None
    if "Metadata/project_settings.config" in blobs:
        import json
        try:
            parsed = json.loads(blobs["Metadata/project_settings.config"])
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ContainerError("bad_project_settings") from exc
        if not isinstance(parsed, dict):
            raise ContainerError("bad_project_settings")
        settings = parsed
    understood = ["3D/3dmodel.model"]
    if settings is not None:
        understood.append("Metadata/project_settings.config")
    records = tuple(MemberDigest(n, hashlib.sha256(blobs[n]).hexdigest()) for n in sorted(blobs))
    passed = tuple(rec for rec in records if rec.name not in understood)
    return ThreeMFManifest(records, tuple(understood), passed, model, settings)
