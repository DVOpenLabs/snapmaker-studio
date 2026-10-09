"""scene/1 -- a read-only, bounded description of a project's geometry, placement and findings.

The contract is the committed JSON Schema ``data/scene-1.schema.json`` (frozen: closed objects,
every field required, unknown is null). This module is the only producer of it.

What a scene IS: a consistent snapshot of the file as it was copied for the job. It is not a live
view. ``SOURCE_CHANGED`` therefore only ever applies to a reused request_id+path or an
``expected_revision`` mismatch (see ``snapstudio_api.scene_jobs``); it does not apply to edits made
after the snapshot was taken.

Design rules, in order of importance:

* **Untrusted input.** The archive is opened by a SELECTIVE reader that owns its own checks:
  colliding or traversal-looking entry names, external relationships, DTD/ENTITY declarations and
  any text encoding other than UTF-8 are rejected BEFORE parsing; only the ``.model``, ``.rels`` and
  the two metadata configs the scene needs are ever read (never thumbnails or embedded G-code);
  every read is metered against the budgets in ``scene_limits`` while it happens.
  ``ThreeMF.open()`` and ``config_io`` are deliberately untouched.
* **Cooperative interruption.** Archive reads are <= 1 MiB, lxml ``iterparse`` checks the cancel /
  deadline hook every <= 1,000 events (and on every read), geometry encode/transform runs in
  batches of <= 5,000 triangles. The worst uninterruptible call is one such unit. Accepted
  limitation: a single stuck native/filesystem call cannot be interrupted in-process; the backstop
  is the job registry's fail-closed WORKER_WEDGED state (no multiprocessing in v1).
* **Honest unknowns.** Placement, plate membership and volume roles that the file does not prove
  are reported as ``unknown``/``ambiguous`` with a limitation, never guessed. Bed fit is only
  claimed when the bed is Studio's U1 template, placement is known and the instance is not one of
  several build items of the same object id (the engine's own placement answer for those is
  unverified, see ``REPEATED_INSTANCE_PLACEMENT_UNVERIFIED``).
* **Never silent truncation.** Over any budget the build stops with ``LIMIT_EXCEEDED``.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import posixpath
import re
import sys
import zipfile
import zlib
from array import array
from importlib.resources import files

from lxml import etree

from . import scene_limits as L
from . import units as _units
from .errors import SnapStudioError

SCHEMA_ID = "scene/1"
SCHEMA_RESOURCE = "scene-1.schema.json"

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_T = {n: f"{{{CORE_NS}}}{n}" for n in (
    "model", "resources", "object", "mesh", "vertices", "vertex", "triangles", "triangle",
    "components", "component", "build", "item")}
_PROD_PATH = f"{{{PROD_NS}}}path"

ROOT_MODEL_DEFAULT = "3D/3dmodel.model"
MODEL_SETTINGS = "Metadata/model_settings.config"
PRUSA_CONFIG = "Metadata/Slic3r_PE_model.config"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MODEL_REL_TYPE = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

# limitation codes that make a scene "partial" rather than "complete"
PARTIAL_LIMITATIONS = frozenset({
    "UNKNOWN_VOLUME_ROLE", "UNKNOWN_PLACEMENT", "PLATE_MEMBERSHIP_AMBIGUOUS", "PLATE_MEMBERSHIP_UNKNOWN", "UNSUPPORTED_UNIT",
    "BED_TEMPLATE_UNAVAILABLE", "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED", "NON_MM_SOURCE_UNIT",
    "NO_BUILD_ITEMS"})
#: Information only: the scene is still as complete as the file allows.
INFORMATIONAL_LIMITATIONS = frozenset({"PLATES_UNAVAILABLE", "MULTI_PLATE_PLACEMENT_UNCHECKED"})

ERROR_CODES = (
    "INVALID_REQUEST", "UNSUPPORTED_FORMAT", "INVALID_ARCHIVE", "INVALID_GEOMETRY",
    "UNRESOLVED_REFERENCE", "LIMIT_EXCEEDED", "SOURCE_CHANGED", "CANCELLED", "TIMEOUT",
    "EXPIRED", "NOT_READY", "WORKER_WEDGED", "INTERNAL")


class SceneError(SnapStudioError):
    """A refusal with a stable machine code (one of ERROR_CODES) and a message safe to show."""

    def __init__(self, code: str, message: str) -> None:
        assert code in ERROR_CODES, code
        self.code = code
        self.message = message
        super().__init__(message)


class SceneCancelled(Exception):
    """Raised by the job control hook when the job was cancelled."""


class SceneTimeout(Exception):
    """Raised by the job control hook when the job's deadline passed."""


class Control:
    """The cancel/deadline/progress hook. The default does nothing."""

    def check(self) -> None:  # pragma: no cover - trivial
        return None

    def progress(self, stage: str, completed: int | None, total: int | None) -> None:  # pragma: no cover
        return None


def load_schema() -> dict:
    return json.loads((files("snapstudio_core.data") / SCHEMA_RESOURCE).read_text("utf-8"))


# --------------------------------------------------------------------------------------------
# Selective archive reader
# --------------------------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")      # http:, file:, C: ... never a package-relative path
_XML_DECL_ENCODING = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([^"']+)["']""", re.I)
_BOMS_REJECTED = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")
_READ_ERRORS = (zipfile.BadZipFile, NotImplementedError, zlib.error, EOFError, RuntimeError, OSError)


def normalize_entry_name(name: str) -> tuple[str, bool]:
    """A zip entry name as a normalized archive-relative path, and whether it is a directory.

    Rejected: control characters, rooted names, drive letters, any ``..`` segment. Backslashes are
    read as separators, so ``a\\b`` and ``a/b`` collide (and are rejected as a pair by the caller).
    """
    n = name.replace("\\", "/")
    if _CONTROL_CHARS.search(n):
        raise SceneError("INVALID_ARCHIVE", "The archive has an entry name with control characters.")
    if n.startswith("/") or _DRIVE.match(n):
        raise SceneError("INVALID_ARCHIVE", "The archive has an entry with an absolute path.")
    segments = n.split("/")
    if ".." in segments:
        raise SceneError("INVALID_ARCHIVE", "The archive has an entry that escapes its own folder.")
    clean = [s for s in segments if s not in ("", ".")]
    if not clean:
        raise SceneError("INVALID_ARCHIVE", "The archive has an entry with an empty name.")
    return "/".join(clean), n.endswith("/")


def resolve_reference(target: str, base_dir: str = "") -> str:
    """Resolve a relationship Target / component path to a normalized part name.

    A leading ``/`` means "from the package root", which is how every slicer writes them, so it is
    accepted. A reference that climbs above the package root is rejected.
    """
    t = target.replace("\\", "/")
    if _CONTROL_CHARS.search(t) or _SCHEME.match(t):
        raise SceneError("INVALID_ARCHIVE", "The project has a malformed internal reference.")
    parts = [] if t.startswith("/") else [s for s in base_dir.split("/") if s]
    for seg in t.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                raise SceneError("INVALID_ARCHIVE", "A reference in the project escapes the archive.")
            parts.pop()
        else:
            parts.append(seg)
    if not parts:
        raise SceneError("INVALID_ARCHIVE", "The project has an empty internal reference.")
    return "/".join(parts)


class GuardedStream:
    """A file-like over one archive member that meters, scans and honours cancellation.

    Reads at most ``CHUNK`` bytes per call (bounded uninterruptible work). The DTD/ENTITY scan and
    the encoding check run on the raw bytes BEFORE the parser sees them.
    """

    def __init__(self, archive: "Archive", info: zipfile.ZipInfo, kind: str, cap: int, scan: bool = True):
        self.archive, self.kind, self.cap, self.scan = archive, kind, cap, scan
        self.bytes_read = 0
        self._carry = b""
        self._first = True
        try:
            self._fh = archive.zf.open(info, "r")
        except _READ_ERRORS as exc:
            raise SceneError("INVALID_ARCHIVE", "A part of the archive could not be opened.") from exc

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass

    def read(self, size: int = -1) -> bytes:
        self.archive.ctl.check()
        n = L.SNAPSHOT_CHUNK_BYTES if size is None or size < 0 else min(size, L.SNAPSHOT_CHUNK_BYTES)
        try:
            chunk = self._fh.read(n)
            if self._first and chunk and len(chunk) < 4:
                chunk += self._fh.read(4 - len(chunk))
        except _READ_ERRORS as exc:
            raise SceneError("INVALID_ARCHIVE", "A part of the archive is damaged.") from exc
        if not chunk:
            return chunk
        self.bytes_read += len(chunk)
        self.archive.account(len(chunk), self.kind)
        if self.bytes_read > self.cap:
            raise SceneError("LIMIT_EXCEEDED", "A part of the archive expands past what Studio will read.")
        if self.scan:
            if self._first:
                self._check_encoding(chunk)
            hay = (self._carry + chunk).lower()
            if b"<!doctype" in hay or b"<!entity" in hay:
                raise SceneError("INVALID_ARCHIVE", "The project contains a DTD or entity declaration, which Studio does not accept.")
            self._carry = hay[-9:]
        self._first = False
        return chunk

    @staticmethod
    def _check_encoding(head: bytes) -> None:
        if head.startswith(b"\xef\xbb\xbf"):
            head = head[3:]
        elif head.startswith(_BOMS_REJECTED) or b"\x00" in head[:4]:
            raise SceneError("INVALID_ARCHIVE", "The project is not UTF-8 text, which is the only encoding Studio accepts.")
        found = _XML_DECL_ENCODING.match(head)
        if found and found.group(1).strip().lower() not in (b"utf-8", b"utf8"):
            raise SceneError("INVALID_ARCHIVE", "The project is not UTF-8 text, which is the only encoding Studio accepts.")


class Archive:
    """Read-only, selective, metered access to one 3MF."""

    def __init__(self, path: str, ctl: Control):
        self.ctl = ctl
        self.total_read = 0
        self.model_read = 0
        self.model_declared = 0
        try:
            self.zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise SceneError("INVALID_ARCHIVE", "This file is not a readable 3MF archive.") from exc
        infos = self.zf.infolist()
        if len(infos) > L.ARCHIVE_MAX_ENTRIES:
            raise SceneError("LIMIT_EXCEEDED", "The archive has more entries than Studio will read.")
        self.index: dict[str, tuple[str, zipfile.ZipInfo]] = {}
        for info in infos:
            norm, is_dir = normalize_entry_name(info.filename)
            key = norm.casefold()
            if key in self.index:
                raise SceneError("INVALID_ARCHIVE", "The archive has duplicate or colliding entry names.")
            if info.flag_bits & 0x1:
                raise SceneError("INVALID_ARCHIVE", "The archive is encrypted.")
            self.index[key] = (norm, info)
            if is_dir:
                self.index[key] = (norm + "/", info)

    def close(self) -> None:
        self.zf.close()

    def account(self, n: int, kind: str) -> None:
        self.total_read += n
        if self.total_read > L.ARCHIVE_EXPANSION_BYTES:
            raise SceneError("LIMIT_EXCEEDED", "The archive expands past what Studio will read.")
        if kind == "model":
            self.model_read += n
            if self.model_read > L.MODEL_XML_BYTES:
                raise SceneError("LIMIT_EXCEEDED", "The model data is larger than Studio will read.")

    def has(self, name: str) -> bool:
        entry = self.index.get(name.casefold())
        return entry is not None and not entry[0].endswith("/")

    def names(self) -> list[str]:
        return [norm for norm, _ in self.index.values() if not norm.endswith("/")]

    def open(self, name: str, kind: str, scan: bool = True) -> GuardedStream:
        entry = self.index.get(name.casefold())
        if entry is None or entry[0].endswith("/"):
            raise SceneError("UNRESOLVED_REFERENCE", "The project refers to a part that is not in the archive.")
        info = entry[1]
        if len(entry[0]) > L.MAX_PART_NAME_LENGTH:
            # part names are carried on nodes, meshes and sources: bound them before they are placed
            raise SceneError("LIMIT_EXCEEDED", f"A part name is longer than the {L.MAX_PART_NAME_LENGTH} characters Studio carries.")
        cap = L.MODEL_XML_BYTES if kind == "model" else L.CONFIG_PART_BYTES
        if info.file_size > cap:
            raise SceneError("LIMIT_EXCEEDED", "A part of the archive is larger than Studio will read.")
        if kind == "model":
            self.model_declared += info.file_size
        return GuardedStream(self, info, kind, cap, scan)

    def read_small(self, name: str) -> bytes:
        stream = self.open(name, "config")
        try:
            out = []
            while True:
                chunk = stream.read(L.SNAPSHOT_CHUNK_BYTES)
                if not chunk:
                    break
                out.append(chunk)
            return b"".join(out)
        finally:
            stream.close()


def iter_xml(stream: GuardedStream, ctl: Control, known=None, consume=frozenset(), local=False):
    """Yield lxml ``(event, element)`` pairs with the hardened options.

    The parser is also asked, on its first event, whether it saw a doctype / internal DTD or a
    non-UTF-8 declaration, so rejection does not depend on the raw byte scan alone.

    Every completed element is COUNTED against ``MAX_XML_ELEMENTS`` (so a part under its byte cap that is
    made of millions of tiny elements is refused early). When ``known`` (the local names the caller reads)
    is given, any completed element outside it is released as soon as the caller has seen it, so unknown
    junk never accumulates (an element in the namespace the caller does not read is unknown too), and so is
    any element named in ``consume`` (self-contained records the caller has read at their own end event);
    the caller releases the recognized parents it consumed. ``local=True`` matches by local name.
    """
    try:
        it = etree.iterparse(stream, events=("start", "end"), resolve_entities=False,
                             load_dtd=False, no_network=True, huge_tree=False)
        first, count, elements = True, 0, 0
        for event, elem in it:
            if first:
                first = False
                info = elem.getroottree().docinfo
                if info.doctype or info.internalDTD is not None or info.system_url or info.public_id:
                    raise SceneError("INVALID_ARCHIVE", "The project contains a DTD, which Studio does not accept.")
                if (info.encoding or "UTF-8").upper() not in ("UTF-8", "UTF8"):
                    raise SceneError("INVALID_ARCHIVE", "The project is not UTF-8 text, which is the only encoding Studio accepts.")
            count += 1
            if count % L.XML_EVENTS_PER_CHECK == 0:
                ctl.check()
            if event == "end":
                elements += 1
                if elements > L.MAX_XML_ELEMENTS:
                    raise SceneError("LIMIT_EXCEEDED", f"A part of the project has more than {L.MAX_XML_ELEMENTS:,} elements.")
            yield event, elem
            if known is not None and event == "end":
                tag = etree.QName(elem).localname if local else elem.tag
                if tag not in known or tag in consume:
                    _free(elem)
    except etree.LxmlError as exc:
        raise SceneError("INVALID_ARCHIVE", "A part of the project is not well-formed XML.") from exc
    finally:
        stream.close()


def _free(elem) -> None:
    """Release ONE completed element: clear it and detach it from its parent.

    Never its siblings. Records that a parent consumes later (the ``<part>``/``<volume>``/``<model_instance>``
    children of a settings ``<object>``/``<plate>``) are siblings of whatever unknown element happens to follow
    them, and deleting them would silently turn a negative part into a printable one. The caller must have
    read everything it needs from ``elem`` (as plain data) BEFORE calling this.
    """
    elem.clear()
    parent = elem.getparent()
    if parent is not None:
        parent.remove(elem)


# --------------------------------------------------------------------------------------------
# Matrices (column-major 4x4 as 16 floats; a 3MF transform is 12 numbers: 3 columns + translation)
# --------------------------------------------------------------------------------------------

IDENTITY16 = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def parse_transform(text: str | None, mm_per_unit: float) -> list[float] | None:
    """A 3MF ``transform`` attribute as a column-major 16-float matrix in millimetres."""
    if text is None:
        return None
    parts = text.split()
    if len(parts) != 12:
        raise SceneError("INVALID_GEOMETRY", "A transform does not have twelve numbers.")
    try:
        v = [float(p) for p in parts]
    except ValueError as exc:
        raise SceneError("INVALID_GEOMETRY", "A transform has a value that is not a number.") from exc
    if not all(math.isfinite(x) for x in v):
        raise SceneError("INVALID_GEOMETRY", "A transform has a value that is not finite.")
    return [v[0], v[1], v[2], 0.0, v[3], v[4], v[5], 0.0, v[6], v[7], v[8], 0.0,
            v[9] * mm_per_unit, v[10] * mm_per_unit, v[11] * mm_per_unit, 1.0]


def mat_mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = (a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1]
                              + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3])
    return out


def mat_det3(m: list[float]) -> float:
    return (m[0] * (m[5] * m[10] - m[9] * m[6]) - m[4] * (m[1] * m[10] - m[9] * m[2])
            + m[8] * (m[1] * m[6] - m[5] * m[2]))


def _round_matrix(m: list[float]) -> list[float]:
    return [float(f"{x:.9g}") + 0.0 for x in m]   # + 0.0 turns -0.0 into 0.0


# --------------------------------------------------------------------------------------------
# Model parts
# --------------------------------------------------------------------------------------------

class Budget:
    """Counters shared by every model part of one scene, enforced WHILE parsing (never after)."""

    def __init__(self) -> None:
        self.vertices = 0
        self.triangles = 0
        self.elements = 0
        self.objects = 0


class MeshData:
    __slots__ = ("pos", "idx", "nverts", "ntris", "max_index")

    def __init__(self) -> None:
        self.pos = array("d")
        self.idx = array("I")
        self.nverts = 0
        self.ntris = 0
        self.max_index = -1


class Component:
    __slots__ = ("object_id", "part", "transform")

    def __init__(self, object_id: str, part: str, transform):
        self.object_id, self.part, self.transform = object_id, part, transform


class ObjectDef:
    __slots__ = ("id", "mesh", "components")

    def __init__(self, oid: str):
        self.id = oid
        self.mesh: MeshData | None = None
        self.components: list[Component] = []


class BuildItem:
    """A build item. ``part`` is the model FILE its object lives in: the root unless the item carries a
    production-extension ``p:path`` (so identity everywhere is the pair part + object id)."""
    __slots__ = ("object_id", "part", "transform")

    def __init__(self, object_id: str, part: str, transform):
        self.object_id, self.part, self.transform = object_id, part, transform


class ModelFile:
    def __init__(self, part: str):
        self.part = part
        self.unit = _units.DEFAULT_UNIT
        self.mm_per_unit = 1.0
        self.unit_recognized = True
        self.objects: dict[str, ObjectDef] = {}
        self.build: list[BuildItem] = []


def _check_id(value: str | None, what: str) -> str:
    if value is None or not value.strip():
        raise SceneError("INVALID_ARCHIVE", f"A {what} has no id.")
    if len(value) > L.MAX_ID_LENGTH:
        raise SceneError("LIMIT_EXCEEDED", f"A {what} id is longer than Studio will carry.")
    return value


def _package_path(ref: str) -> str:
    """A production-extension ``p:path``: an ABSOLUTE package path (leading ``/``); relative ones are refused."""
    if not ref.startswith("/"):
        raise SceneError("UNRESOLVED_REFERENCE", "A p:path reference must be an absolute package path.")
    return resolve_reference(ref)


def parse_model(arc: Archive, part: str, budget: Budget, ctl: Control, is_root: bool) -> ModelFile:
    """Stream one ``.model`` part into objects, meshes, components and (root only) build items."""
    mf = ModelFile(part)
    stream = arc.open(part, "model")
    cur: ObjectDef | None = None
    mesh: MeshData | None = None
    saw_root = False
    t_vertex, t_triangle, t_component, t_item = _T["vertex"], _T["triangle"], _T["component"], _T["item"]
    t_object, t_mesh, t_model = _T["object"], _T["mesh"], _T["model"]
    limit_v, limit_t, max_coord = L.MAX_VERTICES, L.MAX_PARSED_TRIANGLES, L.MAX_COORDINATE_MM
    for event, elem in iter_xml(stream, ctl):
        tag = elem.tag
        if event == "start":
            if not saw_root:
                saw_root = True
                if tag != t_model:
                    raise SceneError("INVALID_ARCHIVE", "A model part does not start with a model element.")
                # The SAME function the legacy readers use, on the real root element.
                info = _units.resolve_unit(elem.get("unit"))
                mf.unit_recognized = info.recognized
                mf.unit = info.name if info.recognized else _units.DEFAULT_UNIT   # documented fallback
                mf.mm_per_unit = info.factor
            elif tag == t_object:
                budget.objects += 1
                if budget.objects > L.MAX_OBJECT_DEFINITIONS:
                    raise SceneError("LIMIT_EXCEEDED", f"The project defines more than {L.MAX_OBJECT_DEFINITIONS:,} objects.")
                oid = _check_id(elem.get("id"), "object")
                if oid in mf.objects:
                    raise SceneError("INVALID_ARCHIVE", "A model part defines the same object id twice.")
                cur = ObjectDef(oid)
                mf.objects[oid] = cur
            elif tag == t_mesh and cur is not None:
                mesh = MeshData()
            continue
        # --- end events
        budget.elements += 1
        if budget.elements > L.MAX_XML_ELEMENTS:
            raise SceneError("LIMIT_EXCEEDED", f"The model data has more than {L.MAX_XML_ELEMENTS:,} elements.")
        if tag == t_vertex:
            if mesh is None:
                continue
            try:
                x, y, z = float(elem.get("x")), float(elem.get("y")), float(elem.get("z"))
            except (TypeError, ValueError) as exc:
                raise SceneError("INVALID_GEOMETRY", "A vertex has a coordinate that is missing or not a number.") from exc
            scale = mf.mm_per_unit
            x, y, z = x * scale, y * scale, z * scale
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                raise SceneError("INVALID_GEOMETRY", "A vertex has a coordinate that is not finite.")
            if abs(x) > max_coord or abs(y) > max_coord or abs(z) > max_coord:
                raise SceneError("INVALID_GEOMETRY", "A vertex coordinate is outside the range Studio can represent.")
            budget.vertices += 1
            if budget.vertices > limit_v:
                raise SceneError("LIMIT_EXCEEDED", "The project has more vertices than Studio will draw.")
            mesh.pos.append(x)
            mesh.pos.append(y)
            mesh.pos.append(z)
            mesh.nverts += 1
        elif tag == t_triangle:
            if mesh is None:
                continue
            try:
                a, b, c = int(elem.get("v1")), int(elem.get("v2")), int(elem.get("v3"))
            except (TypeError, ValueError) as exc:
                raise SceneError("INVALID_GEOMETRY", "A triangle has an index that is missing or not a whole number.") from exc
            if a < 0 or b < 0 or c < 0 or a > 0xFFFFFFFF or b > 0xFFFFFFFF or c > 0xFFFFFFFF:
                raise SceneError("INVALID_GEOMETRY", "A triangle has a vertex index outside the supported range.")
            budget.triangles += 1
            if budget.triangles > limit_t:
                raise SceneError("LIMIT_EXCEEDED", f"The project has at least {budget.triangles:,} triangles; Studio draws at most {limit_t:,}.")
            top = max(a, b, c)
            if top > mesh.max_index:
                mesh.max_index = top
            mesh.idx.append(a)
            mesh.idx.append(b)
            mesh.idx.append(c)
            mesh.ntris += 1
        elif tag == t_mesh:
            if mesh is not None and cur is not None:
                if mesh.nverts == 0 or mesh.ntris == 0:
                    raise SceneError("INVALID_GEOMETRY", "A mesh has no vertices or no triangles.")
                if mesh.max_index >= mesh.nverts:
                    raise SceneError("INVALID_GEOMETRY", "A triangle refers to a vertex that does not exist.")
                cur.mesh = mesh
            mesh = None
        elif tag == t_component:
            if cur is None:
                continue
            oid = _check_id(elem.get("objectid"), "component")
            ref = elem.get(_PROD_PATH)
            if ref is not None and not is_root:
                raise SceneError("UNRESOLVED_REFERENCE", "A component path is only honoured in the root model part.")
            target = _package_path(ref) if ref is not None else part
            cur.components.append(Component(oid, target, parse_transform(elem.get("transform"), mf.mm_per_unit)))
            if len(cur.components) > L.MAX_NODES:
                raise SceneError("LIMIT_EXCEEDED", "An object has more components than Studio will draw.")
        elif tag == t_object:
            if cur is not None and cur.mesh is not None and cur.components:
                raise SceneError("INVALID_ARCHIVE", "An object has both a mesh and components.")
            cur = None
        elif tag == t_item and is_root:
            oid = _check_id(elem.get("objectid"), "build item")
            ref = elem.get(_PROD_PATH)
            item_part = _package_path(ref) if ref is not None else part
            mf.build.append(BuildItem(oid, item_part, parse_transform(elem.get("transform"), mf.mm_per_unit)))
            if len(mf.build) > L.MAX_NODES:
                raise SceneError("LIMIT_EXCEEDED", "The build has more items than Studio will draw.")
        # Every completed element is released, whatever it is (unknown extensions, junk, containers):
        # memory stays flat however many elements a model part holds, and the counters above stop it.
        _free(elem)
    if not saw_root:
        raise SceneError("INVALID_ARCHIVE", "A model part is empty.")
    return mf


_RELS_KNOWN = frozenset({"Relationships", "Relationship"})
_BAMBU_KNOWN = frozenset({"config", "object", "part", "metadata", "plate", "model_instance", "mesh_stat"})
_PRUSA_KNOWN = frozenset({"config", "object", "volume", "metadata", "mesh"})


def find_root_model(arc: Archive) -> str:
    """The root model part named by ``_rels/.rels`` (default ``3D/3dmodel.model``).

    Every ``.rels`` part is read and an external relationship in any of them is a rejection.
    """
    rels = [n for n in arc.names() if n.lower().endswith(".rels")]
    if len(rels) > L.MAX_RELS_PARTS:
        raise SceneError("LIMIT_EXCEEDED", "The archive has more relationship parts than Studio will read.")
    root = None
    for name in rels:
        stream = arc.open(name, "config")
        for event, elem in iter_xml(stream, arc.ctl, known=_RELS_KNOWN, consume=frozenset({"Relationship"}), local=True):
            if event != "end" or etree.QName(elem).localname != "Relationship":
                continue
            if (elem.get("TargetMode") or "").lower() == "external":
                raise SceneError("INVALID_ARCHIVE", "The project has an external relationship, which Studio does not follow.")
            target = elem.get("Target")
            if not target:
                raise SceneError("INVALID_ARCHIVE", "A relationship has no target.")
            # a relationship Target is relative to the folder that holds the PART the .rels describes
            parent = posixpath.dirname(name)
            base = posixpath.dirname(parent) if posixpath.basename(parent).casefold() == "_rels" else parent
            resolved = resolve_reference(target, base)
            if name.casefold() == "_rels/.rels" and elem.get("Type") == _MODEL_REL_TYPE and root is None:
                root = resolved
    root = root or ROOT_MODEL_DEFAULT
    if not arc.has(root):
        raise SceneError("UNRESOLVED_REFERENCE", "The project has no root model part.")
    return arc.index[root.casefold()][0]


#: Stands in for a subtype when two records for one (object, part) disagree; ``role_of`` reads it as unknown.
CONFLICTING_SUBTYPE = "conflicting_records"


class SettingsInfo:
    """What model_settings.config / Slic3r_PE_model.config say, reduced to what the scene uses."""

    def __init__(self) -> None:
        self.dialect: str | None = None            # "bambu" | "prusa" | None
        self.part_subtypes: dict[str, dict[str, str | None]] = {}   # object id -> {part id: subtype}
        self.metadata_objects: set[str] = set()    # object ids with ANY part record (even one that is malformed)
        self.plates: list[dict] = []               # {"id","ui_number","members":[(oid, inst|None)]}
        self.prusa_volumes: dict[str, list[dict]] = {}


def parse_settings(arc: Archive, ctl: Control) -> SettingsInfo:
    from .assignments import role_of  # imported lazily: assignments is a heavy module

    info = SettingsInfo()
    if arc.has(MODEL_SETTINGS):
        info.dialect = "bambu"
        stream = arc.open(arc.index[MODEL_SETTINGS.casefold()][0], "config")
        objects = 0
        for event, elem in iter_xml(stream, ctl, known=_BAMBU_KNOWN):
            if event != "end":
                continue
            if elem.tag == "object":
                objects += 1
                if objects > 5 * L.MAX_NODES:
                    raise SceneError("LIMIT_EXCEEDED", "The settings describe more objects than Studio will read.")
                oid = elem.get("id") or ""
                # a duplicated record may not silently overwrite another: two records for the same
                # (object id, part id) that disagree make the role unknown (identical ones are fine)
                parts = info.part_subtypes.setdefault(oid, {})
                for p in elem.iterchildren("part"):
                    info.metadata_objects.add(oid)          # the object HAS metadata, whatever this record says
                    pid = p.get("id")
                    if pid is None:
                        continue
                    subtype = p.get("subtype")
                    if pid in parts and parts[pid] != subtype:
                        subtype = CONFLICTING_SUBTYPE
                    parts[pid] = subtype
                _free(elem)
            elif elem.tag == "plate":
                if len(info.plates) >= 256:
                    raise SceneError("LIMIT_EXCEEDED", "The settings describe more plates than Studio will read.")
                meta = {m.get("key"): m.get("value") for m in elem.iterchildren("metadata")}
                number = meta.get("plater_id")
                members = []
                for mi in elem.iterchildren("model_instance"):
                    mm = {m.get("key"): m.get("value") for m in mi.iterchildren("metadata")}
                    if mm.get("object_id") is not None:
                        members.append((mm["object_id"], mm.get("instance_id")))
                    if len(members) > 10 * L.MAX_NODES:
                        raise SceneError("LIMIT_EXCEEDED", "A plate lists more objects than Studio will read.")
                ui = (int(number) if number is not None and number.isascii() and number.isdigit()
                      and len(number) <= 6 else None)
                info.plates.append({"ui_number": ui, "members": members})
                _free(elem)
    elif arc.has(PRUSA_CONFIG):
        info.dialect = "prusa"
        stream = arc.open(arc.index[PRUSA_CONFIG.casefold()][0], "config")
        count = 0
        for event, elem in iter_xml(stream, ctl, known=_PRUSA_KNOWN):
            if event != "end" or elem.tag != "object":
                continue
            count += 1
            if count > L.MAX_OBJECT_DEFINITIONS:
                raise SceneError("LIMIT_EXCEEDED", "The settings describe more objects than Studio will read.")
            entries = []
            for vol in elem.iterchildren("volume"):
                # attributes are read BY NAME: their order in the tag does not matter
                first, last = vol.get("firstid"), vol.get("lastid")
                valid = (first is not None and last is not None and first.isascii() and last.isascii()
                         and first.isdigit() and last.isdigit() and len(first) <= 9 and len(last) <= 9)
                kind = None
                for m in vol.iterchildren("metadata"):
                    if m.get("key") == "volume_type" and m.get("type") in (None, "volume"):
                        kind = m.get("value")
                entries.append({"range": (int(first), int(last)) if valid else None, "role": role_of(kind)})
                if len(entries) > L.MAX_VOLUMES_PER_MESH:
                    raise SceneError("LIMIT_EXCEEDED", "An object has more volumes than Studio will read.")
            if entries:
                info.prusa_volumes.setdefault(elem.get("id") or "", []).extend(entries)
            _free(elem)
    return info


# --------------------------------------------------------------------------------------------
# Bed
# --------------------------------------------------------------------------------------------

def _bed(limitations: list[dict]) -> tuple[dict, dict]:
    """(bed object for the scene, rectangle used for findings). Surfaces a fallback, never hides it."""
    from . import plate_placement as pp

    rect = None
    try:
        rect = pp.parse_printable_area(pp._u1_printable_area())
    except Exception:  # noqa: BLE001 - a missing/corrupt template is a limitation, not a crash
        rect = None
    policy = "u1_template"
    if rect is None:
        policy = "fallback"
        rect = {"min_x": 0.0, "min_y": 0.0, "max_x": 270.0, "max_y": 270.0}
        limitations.append({"code": "BED_TEMPLATE_UNAVAILABLE", "target_ids": []})
    height = None
    try:
        data = json.loads((files("snapstudio_core.data") / "templates" / "u1_base_project_settings.json").read_text("utf-8"))
        height = float(data.get("printable_height"))
    except Exception:  # noqa: BLE001
        height = None
    poly = [[rect["min_x"], rect["min_y"]], [rect["max_x"], rect["min_y"]],
            [rect["max_x"], rect["max_y"]], [rect["min_x"], rect["max_y"]]]
    return ({"polygon_mm": poly, "height_mm": height, "edge_margin_mm": pp.EDGE_MARGIN_MM, "policy": policy}, rect)




# --------------------------------------------------------------------------------------------
# Traversal
# --------------------------------------------------------------------------------------------

class Node:
    __slots__ = ("id", "parent", "resource", "mesh_key", "local", "world", "mirrored", "build_index",
                 "path", "plate", "placement_known", "printable", "has_non_part", "bounds",
                 "finding_ids", "children", "top", "repeated", "role_ctx")

    def __init__(self) -> None:
        self.parent: Node | None = None
        self.children: list[Node] = []
        self.finding_ids: list[str] = []
        self.bounds = None
        self.printable = None
        self.has_non_part = False
        self.mesh_key = None
        self.role_ctx = None


class TopContext:
    """What every node under one build item inherits."""

    def __init__(self, ordinal: int, build_index, plate: dict, placement_known: bool, repeated: bool):
        self.ordinal, self.build_index, self.plate = ordinal, build_index, plate
        self.placement_known, self.repeated = placement_known, repeated
        self.node: Node | None = None
        self.top_part: str | None = None


class MeshInfo:
    """Volumes and printable-geometry facts for one emitted mesh."""

    def __init__(self, key: tuple[str, str], data: MeshData):
        self.key, self.data = key, data
        self.volumes: list[dict] = []
        self.part_verts: list[int] = []
        self.lo = self.hi = None
        self.has_part = False
        self.has_non_part = False
        self.has_unknown = False


class Traversal:
    def __init__(self, files_by_part: dict[str, ModelFile], settings: SettingsInfo, root_part: str, ctl: Control):
        self.files, self.settings, self.root_part, self.ctl = files_by_part, settings, root_part, ctl
        self.nodes: list[Node] = []
        self.rendered = 0
        self.mesh_order: list[tuple[str, str]] = []
        self._ids: set[str] = set()
        self.mesh_users: dict[tuple[str, str], list[str]] = {}

    def add_tree(self, key: tuple[str, str], transform, ctx: TopContext) -> None:
        ctx.top_part = key[0]
        self._expand(key, transform, None, [], ctx, ())

    def _context_role(self, parent: Node | None, via: str | None, inherited: str | None,
                      ctx: "TopContext | None" = None) -> str | None:
        """The role this USE imposes (Bambu/Orca ``<part subtype=...>``), following the traversal context.

        A part record belongs to one (object, component) pair, so a mesh shared by two objects can be a
        negative part under one and an ordinary part under the other, and a role given to a component
        ASSEMBLY applies to everything beneath it (``inherited`` wins unless it is a plain part). An object
        that HAS part records but none for this component gives ``unknown``, never a printable part.
        """
        if ctx is not None and self.settings.dialect is not None and ctx.top_part != self.root_part:
            # Part records are matched against ROOT-file objects. A build item whose object lives in another
            # file (p:path) cannot be associated provably with any record, so every part beneath it is
            # unknown (fail closed): never printable, never judged against the bed.
            return "unknown"
        own = None
        if parent is not None and via is not None and self.settings.dialect == "bambu" and parent.resource[0] == self.root_part:
            subtypes = self.settings.part_subtypes.get(parent.resource[1])
            if parent.resource[1] in self.settings.metadata_objects and subtypes is not None:
                from .assignments import role_of
                own = role_of(subtypes[via]) if via in subtypes else "unknown"
        if inherited not in (None, "part"):
            return inherited
        return own if own is not None else inherited

    def _expand(self, key, local, parent: Node | None, path: list[int], ctx: TopContext,
                stack: tuple, via: str | None = None, inherited: str | None = None) -> Node:
        self.ctl.check()
        mf = self.files.get(key[0])
        obj = mf.objects.get(key[1]) if mf else None
        if obj is None:
            raise SceneError("UNRESOLVED_REFERENCE", "The project refers to an object that is not defined.")
        if key in stack:
            raise SceneError("INVALID_ARCHIVE", "The project's components refer to themselves.")
        if len(path) >= L.MAX_DEPTH:
            raise SceneError("LIMIT_EXCEEDED", "The project nests objects deeper than Studio will follow.")
        if len(self.nodes) >= L.MAX_NODES:
            raise SceneError("LIMIT_EXCEEDED", "The project has more objects than Studio will draw.")
        node = Node()
        node.parent = parent
        node.resource = key
        node.path = list(path)
        node.local = local if local is not None else IDENTITY16
        node.world = node.local if parent is None else mat_mul(parent.world, node.local)
        if not all(math.isfinite(x) for x in node.world):
            raise SceneError("INVALID_GEOMETRY", "A combined transform is not finite.")
        node.mirrored = mat_det3(node.world) < 0
        node.id = self._node_id(ctx, parent, path)
        if node.id in self._ids:       # digested ids give 128-bit practical uniqueness; a collision is detected
            raise SceneError("INTERNAL", "Two nodes would share an id.")
        self._ids.add(node.id)
        node.role_ctx = self._context_role(parent, via, inherited, ctx)
        node.build_index, node.plate = ctx.build_index, ctx.plate
        node.placement_known, node.repeated, node.top = ctx.placement_known, ctx.repeated, ctx
        self.nodes.append(node)
        if parent is None:
            ctx.node = node
        else:
            parent.children.append(node)
        if obj.mesh is not None:
            node.mesh_key = key
            self.rendered += obj.mesh.ntris
            if self.rendered > L.MAX_RENDERED_TRIANGLES:
                raise SceneError("LIMIT_EXCEEDED", f"The project has at least {self.rendered:,} triangles counting repeated objects; Studio draws at most {L.MAX_RENDERED_TRIANGLES:,}.")
            if key not in self.mesh_users:
                self.mesh_users[key] = []
                self.mesh_order.append(key)
            self.mesh_users[key].append(node.id)
        elif obj.components:
            for i, comp in enumerate(obj.components):
                self._expand((comp.part, comp.object_id), comp.transform, node, path + [i], ctx,
                             stack + (key,), via=comp.object_id, inherited=node.role_ctx)
        else:
            raise SceneError("INVALID_GEOMETRY", "An object has neither a mesh nor components.")
        return node

    @staticmethod
    def _node_id(ctx: TopContext, parent: Node | None, path: list[int]) -> str:
        """``b<build ordinal>`` plus ``.c<index>`` per component level. When that would not fit in
        ``MAX_ID_LENGTH`` the ancestry is replaced by a deterministic digest of it (``b3.~<32 hex>``),
        which is unique per ancestry, so 128 characters always suffice at the deepest allowed nesting."""
        natural = f"b{ctx.ordinal}" + "".join(f".c{i}" for i in path)
        if len(natural) <= L.MAX_ID_LENGTH:
            return natural
        return f"b{ctx.ordinal}.~" + hashlib.sha256(natural.encode("ascii")).hexdigest()[:32]

    # ---- volumes -------------------------------------------------------------------------
    def mesh_data(self, key) -> MeshData:
        return self.files[key[0]].objects[key[1]].mesh

    def build_mesh_info(self, key) -> MeshInfo:
        data = self.mesh_data(key)
        info = MeshInfo(key, data)
        total = data.ntris
        if (self.settings.dialect == "prusa" and key[0] == self.root_part
              and key[1] in self.settings.prusa_volumes):
            info.volumes = self._prusa_ranges(self.settings.prusa_volumes[key[1]], total)
        else:
            info.volumes = [{"id": "v0", "triangle_start": 0, "triangle_count": total, "role": "part", "source": "object"}]
        if len(info.volumes) > L.MAX_VOLUMES_PER_MESH:
            raise SceneError("LIMIT_EXCEEDED", "A mesh has more volumes than Studio will carry.")
        used: set[int] = set()
        for vol in info.volumes:
            if vol["role"] == "part":
                info.has_part = True
                s, c = vol["triangle_start"], vol["triangle_count"]
                used.update(data.idx[3 * s:3 * (s + c)])
            else:
                info.has_non_part = True
                if vol["role"] == "unknown":
                    info.has_unknown = True
        if used:
            pos = data.pos
            lo = [math.inf] * 3
            hi = [-math.inf] * 3
            info.part_verts = sorted(used)
            for n, vi in enumerate(info.part_verts):
                if n % L.VERTEX_BATCH == 0:
                    self.ctl.check()
                b = 3 * vi
                for ax in range(3):
                    v = pos[b + ax]
                    if v < lo[ax]:
                        lo[ax] = v
                    if v > hi[ax]:
                        hi[ax] = v
            info.lo, info.hi = lo, hi
        return info

    @staticmethod
    def _prusa_ranges(entries: list[dict], total: int) -> list[dict]:
        """Partition ALL triangles into volumes. An unmapped gap is an ``unknown`` volume; ranges that
        overlap or leave the mesh make the whole mesh one ``unknown`` volume (never a guess)."""
        whole = [{"id": "v0", "triangle_start": 0, "triangle_count": total, "role": "unknown", "source": "prusa_range"}]
        if any(e["range"] is None for e in entries):
            return whole                       # a range Studio cannot read: never a printable guess
        spans = sorted((e["range"][0], e["range"][1], e["role"]) for e in entries)
        out: list[dict] = []
        cursor = 0
        for first, last, role in spans:
            if first < cursor or last < first or last >= total:
                return whole
            if first > cursor:
                out.append({"id": f"v{len(out)}", "triangle_start": cursor, "triangle_count": first - cursor,
                            "role": "unknown", "source": "prusa_range"})
            out.append({"id": f"v{len(out)}", "triangle_start": first, "triangle_count": last - first + 1,
                        "role": role, "source": "prusa_range"})
            cursor = last + 1
        if cursor < total:
            out.append({"id": f"v{len(out)}", "triangle_start": cursor, "triangle_count": total - cursor,
                        "role": "unknown", "source": "prusa_range"})
        return out or whole


def _world_bounds(info: MeshInfo, world: list[float], ctl: Control):
    """Exact world-space bounds of the printable (role=part) vertices of one instance."""
    if not info.part_verts:
        return None
    m = world
    # Rows with at most one non-zero entry map each output axis from a single input axis, so the
    # transformed local box is exact (no rotation). Anything else transforms the vertices.
    rows = []
    simple = True
    for i in range(3):
        nz = [(j, m[j * 4 + i]) for j in range(3) if abs(m[j * 4 + i]) > 1e-12]
        if len(nz) > 1:
            simple = False
            break
        rows.append(nz[0] if nz else None)
    if simple:
        lo_out = [0.0] * 3
        hi_out = [0.0] * 3
        for i in range(3):
            t = m[12 + i]
            if rows[i] is None:
                lo_out[i] = hi_out[i] = t
            else:
                j, c = rows[i]
                a, b = c * info.lo[j] + t, c * info.hi[j] + t
                lo_out[i], hi_out[i] = (a, b) if a <= b else (b, a)
        return lo_out, hi_out
    pos = info.data.pos
    lo_out = [math.inf] * 3
    hi_out = [-math.inf] * 3
    m0, m1, m2, m4, m5, m6, m8, m9, m10, t0, t1, t2 = (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10], m[12], m[13], m[14])
    for n, vi in enumerate(info.part_verts):
        if n % L.VERTEX_BATCH == 0:
            ctl.check()
        b = 3 * vi
        x, y, z = pos[b], pos[b + 1], pos[b + 2]
        px = m0 * x + m4 * y + m8 * z + t0
        py = m1 * x + m5 * y + m9 * z + t1
        pz = m2 * x + m6 * y + m10 * z + t2
        if px < lo_out[0]: lo_out[0] = px
        if px > hi_out[0]: hi_out[0] = px
        if py < lo_out[1]: lo_out[1] = py
        if py > hi_out[1]: hi_out[1] = py
        if pz < lo_out[2]: lo_out[2] = pz
        if pz > hi_out[2]: hi_out[2] = pz
    return lo_out, hi_out


# --------------------------------------------------------------------------------------------
# Plates
# --------------------------------------------------------------------------------------------

def _plate_assignment(settings: SettingsInfo, oid: str, ordinal: int, instances_of_object: int) -> tuple[dict, bool]:
    """(plate ref, ambiguous?) for the ``ordinal``-th build item of object ``oid``."""
    if not settings.plates:
        return {"state": "unknown", "plate_id": None, "source": None}, False
    found: set[str] = set()
    for idx, plate in enumerate(settings.plates):
        pid = f"p{plate['ui_number']}" if plate["ui_number"] is not None else f"plate-{idx}"
        for moid, inst in plate["members"]:
            if moid != oid:
                continue
            if inst is None:
                # a record that does not say which instance covers all of them only if there is one
                if instances_of_object == 1:
                    found.add(pid)
                else:
                    return {"state": "ambiguous", "plate_id": None, "source": "plate_config"}, True
            elif inst.isascii() and inst.isdigit() and int(inst) == ordinal:
                found.add(pid)
    if len(found) == 1:
        return {"state": "known", "plate_id": next(iter(found)), "source": "plate_config"}, False
    if len(found) > 1:
        return {"state": "ambiguous", "plate_id": None, "source": "plate_config"}, True
    return {"state": "unknown", "plate_id": None, "source": None}, False


# --------------------------------------------------------------------------------------------
# Assembly and encoding
# --------------------------------------------------------------------------------------------

class _Limitations:
    ORDER = ("UNKNOWN_VOLUME_ROLE", "UNKNOWN_PLACEMENT", "PLATE_MEMBERSHIP_AMBIGUOUS", "PLATE_MEMBERSHIP_UNKNOWN",
             "PLATES_UNAVAILABLE", "BED_TEMPLATE_UNAVAILABLE", "REPEATED_INSTANCE_PLACEMENT_UNVERIFIED",
             "NON_MM_SOURCE_UNIT", "UNSUPPORTED_UNIT", "MULTI_PLATE_PLACEMENT_UNCHECKED", "NO_BUILD_ITEMS")

    def __init__(self) -> None:
        self._by: dict[str, list[str]] = {}

    def has(self, code: str) -> bool:
        return code in self._by

    def add(self, code: str, target_ids=()) -> None:
        bucket = self._by.setdefault(code, [])
        for t in target_ids:
            if t not in bucket:
                bucket.append(t)

    def render(self) -> list[dict]:
        out = [{"code": c, "target_ids": self._by[c][:2000]} for c in self.ORDER if c in self._by]
        if len(out) > L.MAX_LIMITATIONS:
            raise SceneError("LIMIT_EXCEEDED", "The scene has more limitations than Studio will carry.")
        return out


def _b64_len(n: int) -> int:
    return 4 * ((n + 2) // 3)


def _encode_f32(pos: array, ctl: Control) -> str:
    step = 3 * L.GEOMETRY_BATCH_TRIANGLES
    out = []
    for s in range(0, len(pos), step):
        ctl.check()
        chunk = array("f", pos[s:s + step])
        if sys.byteorder == "big":
            chunk.byteswap()
        out.append(base64.b64encode(chunk.tobytes()).decode("ascii"))
    return "".join(out)


def _encode_u32(idx: array, ctl: Control) -> str:
    assert idx.itemsize == 4
    step = 3 * L.GEOMETRY_BATCH_TRIANGLES
    out = []
    for s in range(0, len(idx), step):
        ctl.check()
        chunk = idx[s:s + step]
        if sys.byteorder == "big":
            chunk = array("I", chunk)
            chunk.byteswap()
        out.append(base64.b64encode(chunk.tobytes()).decode("ascii"))
    return "".join(out)


def _rounded(v) -> list[float]:
    return [round(float(x), 6) + 0.0 for x in v]


def _finish(revision: str, sources: list[dict], bed: dict, rect: dict, trav: Traversal, tops: list[TopContext],
            plates: list[dict], plate_count: int, lims: _Limitations, ctl: Control, *,
            repeated_tops: list[str]) -> dict:
    from . import plate_placement as pp

    ctl.progress("encoding", 0, trav.rendered)
    infos = {key: trav.build_mesh_info(key) for key in trav.mesh_order}

    # per-node printable facts, children before parents
    for node in reversed(trav.nodes):
        if node.mesh_key is not None:
            info = infos[node.mesh_key]
            if node.role_ctx not in (None, "part"):
                # this USE is a modifier / negative part / support helper (or unknown): nothing prints
                node.printable = None if node.role_ctx == "unknown" else False
                node.has_non_part = True
                node.bounds = None
            else:
                node.printable = True if info.has_part else (None if info.has_unknown else False)
                node.has_non_part = info.has_non_part
                node.bounds = _world_bounds(info, node.world, ctl) if info.has_part else None
        else:
            kids = node.children
            node.has_non_part = any(k.has_non_part for k in kids)
            node.printable = True if any(k.printable is True for k in kids) else (
                None if any(k.printable is None for k in kids) else False)
            boxes = [k.bounds for k in kids if k.bounds is not None]
            node.bounds = ([min(b[0][i] for b in boxes) for i in range(3)],
                           [max(b[1][i] for b in boxes) for i in range(3)]) if boxes else None
    for node in trav.nodes:
        if node.mesh_key is not None and node.role_ctx == "unknown":
            lims.add("UNKNOWN_VOLUME_ROLE", [node.id])
        elif node.mesh_key is not None and node.role_ctx in (None, "part") and infos[node.mesh_key].has_unknown:
            lims.add("UNKNOWN_VOLUME_ROLE", [node.id])

    # findings -- only what the geometry plus the file prove
    findings: list[dict] = []
    all_mm = all(s["unit"] == "millimeter" for s in sources) and not lims.has("UNSUPPORTED_UNIT")
    if not all(s["unit"] == "millimeter" for s in sources):
        lims.add("NON_MM_SOURCE_UNIT")
    if plate_count > 1:
        lims.add("MULTI_PLATE_PLACEMENT_UNCHECKED")
    usable_x = rect["max_x"] - rect["min_x"] - 2 * pp.EDGE_MARGIN_MM
    usable_y = rect["max_y"] - rect["min_y"] - 2 * pp.EDGE_MARGIN_MM
    enabled = bed["policy"] == "u1_template" and plate_count <= 1
    all_mm_or_known = not lims.has("UNSUPPORTED_UNIT")
    index_of = {id(n): i for i, n in enumerate(trav.nodes)}
    for ctx in tops:
        node = ctx.node
        if node is None or not enabled or node.bounds is None or node.printable is not True:
            continue
        if plate_count > 0 and node.plate["state"] != "known":
            continue                  # the project has plates but this instance is provably on none / on two
        if ctx.repeated or not ctx.placement_known:
            # REPEATED_INSTANCE_PLACEMENT_UNVERIFIED / unknown placement: geometry stays visible,
            # but no bed-fit statement of any kind is attached.
            continue
        lo, hi = node.bounds
        pointer = f"/nodes/{index_of[id(node)]}"
        if all_mm:
            over = pp._overhang({"min": lo, "max": hi}, rect)
            if any(v > 0 for v in over.values()):
                fid = f"f{len(findings)}"
                findings.append({"id": fid, "engine": "scene", "schema": SCHEMA_ID, "pointer": pointer,
                                 "scope": "instance", "kind": "placement", "target_ids": [node.id],
                                 "value": {"code": "PLACEMENT_OUTSIDE_BED", "overhang_mm": over}})
                node.finding_ids.append(fid)
        if all_mm_or_known and ((hi[0] - lo[0]) > usable_x + 1e-9 or (hi[1] - lo[1]) > usable_y + 1e-9):
            fid = f"f{len(findings)}"
            findings.append({"id": fid, "engine": "scene", "schema": SCHEMA_ID, "pointer": pointer,
                             "scope": "instance", "kind": "size", "target_ids": [node.id],
                             "value": {"code": "SIZE_EXCEEDS_BED", "overhang_mm": None}})
            node.finding_ids.append(fid)
        if len(findings) > L.MAX_FINDINGS:
            raise SceneError("LIMIT_EXCEEDED", "The scene has more findings than Studio will carry.")
    if repeated_tops:
        lims.add("REPEATED_INSTANCE_PLACEMENT_UNVERIFIED", repeated_tops)

    # response preflight: the geometry alone decides this exactly, before any encoding work
    geom = 0
    for info in infos.values():
        geom += _b64_len(info.data.nverts * 12) + _b64_len(info.data.ntris * 12)
    if geom > L.MAX_RESPONSE_BYTES:
        raise SceneError("LIMIT_EXCEEDED", "The geometry alone is larger than the response Studio will send.")

    meshes = []
    done = 0
    for key in trav.mesh_order:
        info = infos[key]
        d = info.data
        meshes.append({
            "key": {"part": key[0], "object_id": key[1]},
            "vertex_count": d.nverts, "triangle_count": d.ntris,
            "positions_f32le_base64": _encode_f32(d.pos, ctl),
            "indices_u32le_base64": _encode_u32(d.idx, ctl),
            "volumes": info.volumes})
        done += d.ntris
        ctl.progress("encoding", done, trav.rendered)

    nodes = []
    for node in trav.nodes:
        nodes.append({
            "id": node.id,
            "parent_id": node.parent.id if node.parent else None,
            "resource": {"part": node.resource[0], "object_id": node.resource[1]},
            "mesh_key": ({"part": node.mesh_key[0], "object_id": node.mesh_key[1]} if node.mesh_key else None),
            "local_to_parent_mm": _round_matrix(node.local),
            "world_mm": _round_matrix(node.world),
            "mirrored": node.mirrored,
            "role_context": node.role_ctx,
            "build_index": node.build_index,
            "instance_ref": {"build_index": node.build_index, "component_path": node.path},
            "plate": node.plate,
            "placement_state": "known" if node.placement_known else "unknown",
            "printable": node.printable,
            "has_non_part_volumes": node.has_non_part,
            "bounds_mm": ({"min": _rounded(node.bounds[0]), "max": _rounded(node.bounds[1])} if node.bounds else None),
            "finding_ids": node.finding_ids})
    limitations = lims.render()
    status = "partial" if any(x["code"] in PARTIAL_LIMITATIONS for x in limitations) else "complete"
    return {
        "schema": SCHEMA_ID, "revision": revision, "status": status, "units": "mm", "axes": "right-handed-z-up",
        "sources": sources, "bed": bed, "meshes": meshes, "nodes": nodes, "plates": plates,
        "findings": findings, "limitations": limitations,
        "counts": {"nodes": len(nodes), "meshes": len(meshes),
                   "vertices": sum(i.data.nverts for i in infos.values()),
                   "triangles": sum(i.data.ntris for i in infos.values()),
                   "rendered_triangles": trav.rendered, "plates": len(plates),
                   "findings": len(findings), "limitations": len(limitations)},
        "limits": dict(L.LIMITS_ECHO)}


def serialize(scene: dict) -> bytes:
    """The whole response body, once, compact ASCII JSON, with the cap enforced AS IT IS BUILT.

    Each top-level member (and each element of a list member) is serialized separately and the running
    length is checked before it is kept, so an over-cap scene is refused after at most one element past
    the cap: the full body (or a UTF-8 copy of it) is never built first.
    """
    cap = L.MAX_RESPONSE_BYTES

    def dump(value) -> str:
        try:
            return json.dumps(value, separators=(",", ":"), allow_nan=False)
        except ValueError as exc:
            raise SceneError("INVALID_GEOMETRY", "The scene contains a value that is not finite.") from exc

    def over() -> SceneError:
        return SceneError("LIMIT_EXCEEDED", "The scene is larger than the response Studio will send.")

    total = 2                                   # the braces; every other byte is added exactly, before it is kept
    members = []
    for key, value in scene.items():
        head = dump(key) + ":"
        total += len(head) + (1 if members else 0)          # the comma between members
        if total > cap:
            raise over()
        if isinstance(value, list) and value and isinstance(value[0], dict):
            items = []
            total += 2                                       # [ ]
            for item in value:
                text = dump(item)
                total += len(text) + (1 if items else 0)
                if total > cap:
                    raise over()
                items.append(text)
            members.append(head + "[" + ",".join(items) + "]")
        else:
            text = dump(value)
            total += len(text)
            if total > cap:
                raise over()
            members.append(head + text)
    return ("{" + ",".join(members) + "}").encode("ascii")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(L.SNAPSHOT_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------------------------
# Front ends
# --------------------------------------------------------------------------------------------

def _build_3mf(path: str, revision: str, ctl: Control) -> dict:
    lims = _Limitations()
    bed, rect = _bed([])
    if bed["policy"] == "fallback":
        lims.add("BED_TEMPLATE_UNAVAILABLE")
    arc = Archive(path, ctl)
    try:
        ctl.progress("parsing", 0, None)
        root_part = find_root_model(arc)
        budget = Budget()
        files_by_part: dict[str, ModelFile] = {}
        queue = [root_part]
        while queue:
            part = queue.pop(0)
            if part in files_by_part:
                continue
            if len(files_by_part) >= L.MAX_MODEL_PARTS:
                raise SceneError("LIMIT_EXCEEDED", "The project uses more model parts than Studio will read.")
            if not arc.has(part):
                raise SceneError("UNRESOLVED_REFERENCE", "The project refers to a model part that is not in the archive.")
            canon = arc.index[part.casefold()][0]
            mf = parse_model(arc, canon, budget, ctl, canon == root_part)
            files_by_part[canon] = mf
            ctl.progress("parsing", arc.model_read, arc.model_declared)
            for item in mf.build:      # a build item's p:path names the FILE its object lives in
                if not arc.has(item.part):
                    raise SceneError("UNRESOLVED_REFERENCE", "A build item refers to a model part that is not in the archive.")
                item.part = arc.index[item.part.casefold()][0]
                if item.part not in files_by_part:
                    queue.append(item.part)
            for obj in mf.objects.values():
                for comp in obj.components:
                    if not arc.has(comp.part):
                        raise SceneError("UNRESOLVED_REFERENCE", "A component refers to a model part that is not in the archive.")
                    comp.part = arc.index[comp.part.casefold()][0]
                    if comp.part not in files_by_part:
                        queue.append(comp.part)
        settings = parse_settings(arc, ctl)
        root = files_by_part[root_part]
        bad_unit_parts = {mf.part for mf in files_by_part.values() if not mf.unit_recognized}
        sources = [{"part": mf.part, "unit": mf.unit, "mm_per_unit": mf.mm_per_unit}
                   for mf in files_by_part.values()]
        plates = []
        seen_ui = set()
        for idx, plate in enumerate(settings.plates):
            ui = plate["ui_number"]
            if ui is not None and ui in seen_ui:
                continue
            seen_ui.add(ui)
            plates.append({"id": f"p{ui}" if ui is not None else f"plate-{idx}", "ui_number": ui, "origin_mm": None})
        trav = Traversal(files_by_part, settings, root_part, ctl)
        counts: dict[tuple[str, str], int] = {}
        for item in root.build:
            counts[(item.part, item.object_id)] = counts.get((item.part, item.object_id), 0) + 1
        part_by_bare: dict[str, set[str]] = {}
        for item in root.build:
            part_by_bare.setdefault(item.object_id, set()).add(item.part)
        tops: list[TopContext] = []
        seen_n: dict[tuple[str, str], int] = {}
        repeated_tops: list[str] = []
        ambiguous_ids: list[str] = []
        cross_file_ambiguous: list = []
        unknown_plate_ids: list[str] = []
        if root.build:
            for bi, item in enumerate(root.build):
                ikey = (item.part, item.object_id)
                n = seen_n.get(ikey, 0)
                seen_n[ikey] = n + 1
                plate, ambiguous = _plate_assignment(settings, item.object_id, n, counts[ikey])
                if len(part_by_bare[item.object_id]) > 1 and settings.plates:
                    # plate records name a BARE object id: when two build resources in different files share
                    # it, a record cannot prove membership for either of them
                    plate, ambiguous = {"state": "ambiguous", "plate_id": None, "source": "plate_config"}, False
                    cross_file_ambiguous.append(None)
                ctx = TopContext(bi, bi, plate, True, counts[ikey] > 1)
                trav.add_tree(ikey, item.transform, ctx)
                tops.append(ctx)
                if ctx.repeated:
                    repeated_tops.append(ctx.node.id)
                if ambiguous:
                    ambiguous_ids.append(ctx.node.id)
                elif plate["state"] == "unknown" and settings.plates:
                    unknown_plate_ids.append(ctx.node.id)
                elif cross_file_ambiguous and plate["state"] == "ambiguous" and ctx.node.id not in unknown_plate_ids:
                    unknown_plate_ids.append(ctx.node.id)
        else:
            lims.add("NO_BUILD_ITEMS")
            for ordinal, oid in enumerate(root.objects):
                ctx = TopContext(ordinal, None, {"state": "unknown", "plate_id": None, "source": None}, False, False)
                trav.add_tree((root_part, oid), None, ctx)
                tops.append(ctx)
                lims.add("UNKNOWN_PLACEMENT", [ctx.node.id])
        if bad_unit_parts:
            # target_ids name the NODES that live in the affected part(s); for such a source `unit` and
            # `mm_per_unit` in sources[] are the fallback millimetre values (the limitation says so)
            # a build item's transform is written in the ROOT model's unit, so when the root is the bad part the
            # top node of every item is affected too, even if its mesh lives in another file
            lims.add("UNSUPPORTED_UNIT", [n.id for n in trav.nodes
                                          if n.resource[0] in bad_unit_parts or (n.parent is None and root_part in bad_unit_parts)])
        if not settings.plates:
            lims.add("PLATES_UNAVAILABLE")
        if ambiguous_ids:
            lims.add("PLATE_MEMBERSHIP_AMBIGUOUS", ambiguous_ids)
        if unknown_plate_ids:
            lims.add("PLATE_MEMBERSHIP_UNKNOWN", unknown_plate_ids)
        return _finish(revision, sources, bed, rect, trav, tops, plates, len(plates), lims, ctl,
                       repeated_tops=repeated_tops)
    finally:
        arc.close()


def _build_stl(path: str, revision: str, ctl: Control) -> dict:
    import os
    import struct

    from .stl_io import StlTooLarge, decode_stl_stream

    lims = _Limitations()
    bed, rect = _bed([])
    if bed["policy"] == "fallback":
        lims.add("BED_TEMPLATE_UNAVAILABLE")
    size = os.path.getsize(path)
    ctl.progress("parsing", 0, size)
    try:
        with open(path, "rb") as fh:
            # bounded and incremental: the binary header count is judged BEFORE any triangle is decoded,
            # decoding runs in batches with the cancel/deadline hook between them, ASCII is line-streamed
            verts, tris = decode_stl_stream(fh, size, max_triangles=L.MAX_PARSED_TRIANGLES,
                                            max_vertices=L.MAX_VERTICES, check=ctl.check,
                                            batch=L.GEOMETRY_BATCH_TRIANGLES)
    except StlTooLarge as exc:
        raise SceneError("LIMIT_EXCEEDED", f"The model has {exc.triangles:,} {exc.what}; Studio draws at most {exc.limit:,}.") from exc
    except (SnapStudioError, ValueError, struct.error) as exc:
        raise SceneError("INVALID_GEOMETRY", "This STL file could not be read.") from exc
    mesh = MeshData()
    for n, v in enumerate(verts):
        if n % L.VERTEX_BATCH == 0:
            ctl.check()
        if not all(math.isfinite(c) and abs(c) <= L.MAX_COORDINATE_MM for c in v):
            raise SceneError("INVALID_GEOMETRY", "A vertex coordinate is not usable.")
        mesh.pos.extend(v)
    for n, t in enumerate(tris):
        if n % L.VERTEX_BATCH == 0:
            ctl.check()
        mesh.idx.extend(t)
    mesh.nverts, mesh.ntris, mesh.max_index = len(verts), len(tris), len(verts) - 1
    part = "model.stl"
    mf = ModelFile(part)
    obj = ObjectDef("0")
    obj.mesh = mesh
    mf.objects["0"] = obj
    trav = Traversal({part: mf}, SettingsInfo(), part, ctl)
    ctx = TopContext(0, None, {"state": "unknown", "plate_id": None, "source": None}, False, False)
    trav.add_tree((part, "0"), None, ctx)
    lims.add("UNKNOWN_PLACEMENT", [ctx.node.id])
    lims.add("PLATES_UNAVAILABLE")
    return _finish(revision, [{"part": part, "unit": "millimeter", "mm_per_unit": 1.0}], bed, rect, trav, [ctx], [], 0,
                   lims, ctl, repeated_tops=[])


def build_scene_dict(path: str, revision: str | None = None, ctl: Control | None = None) -> dict:
    """Build the scene/1 object for ``path`` (a private snapshot, when called by a job)."""
    ctl = ctl or Control()
    low = str(path).lower()
    if not (low.endswith(".3mf") or low.endswith(".stl")):
        raise SceneError("UNSUPPORTED_FORMAT", "Only .3mf and .stl files can be shown.")
    revision = revision or _sha256_file(path)
    if low.endswith(".stl"):
        return _build_stl(path, revision, ctl)
    return _build_3mf(path, revision, ctl)


def build_scene(path: str, revision: str | None = None, ctl: Control | None = None) -> bytes:
    """The serialized scene (compact UTF-8 JSON), with the whole-body cap enforced."""
    return serialize(build_scene_dict(path, revision, ctl))
