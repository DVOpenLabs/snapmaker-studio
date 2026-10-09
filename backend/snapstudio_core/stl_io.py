from __future__ import annotations
import re
import struct
from .errors import SnapStudioError


def detect_stl_format(data: bytes) -> str:
    if len(data) >= 84:
        (n,) = struct.unpack_from("<I", data, 80)
        if 84 + n * 50 == len(data):
            return "binary"
    head = data[:512].lstrip().lower()
    if head.startswith(b"solid") or b"facet" in data[:4096].lower():
        return "ascii"
    raise SnapStudioError("unrecognized STL (not binary-size-consistent or ASCII)")


def _add(vmap: dict, verts: list, p: tuple[float, float, float]) -> int:
    i = vmap.get(p)
    if i is None:
        i = len(verts); vmap[p] = i; verts.append(p)
    return i


def parse_stl(data: bytes):
    fmt = detect_stl_format(data)
    verts: list[tuple] = []
    tris: list[tuple] = []
    vmap: dict = {}
    if fmt == "binary":
        (n,) = struct.unpack_from("<I", data, 80)
        off = 84
        for _ in range(n):
            vals = struct.unpack_from("<12f", data, off)
            off += 50  # 12 floats (48) + 2-byte attribute
            p1, p2, p3 = vals[3:6], vals[6:9], vals[9:12]
            tris.append((_add(vmap, verts, p1), _add(vmap, verts, p2), _add(vmap, verts, p3)))
    else:
        cur: list[tuple] = []
        for line in data.decode("utf-8", "replace").splitlines():
            s = line.strip()
            if s.startswith("vertex"):
                _, x, y, z = s.split()[:4]
                cur.append((float(x), float(y), float(z)))
                if len(cur) == 3:
                    tris.append(tuple(_add(vmap, verts, p) for p in cur)); cur = []
    if not tris:
        raise SnapStudioError("STL contained no triangles")
    return verts, tris


# --- bounded, incremental decoder (additive; parse_stl above is unchanged) -----------------------------

class StlTooLarge(SnapStudioError):
    """The file declares or contains more triangles (or vertices) than the caller allows."""

    def __init__(self, triangles: int, limit: int, what: str = "triangles") -> None:
        self.triangles, self.limit, self.what = triangles, limit, what
        super().__init__(f"{triangles} {what}; limit {limit}")


_BATCH = 5000


def _decode_binary_batch(raw: bytes, vmap: dict, verts: list, tris: list) -> None:
    for rec in struct.iter_unpack("<12fH", raw):
        tris.append((_add(vmap, verts, rec[3:6]), _add(vmap, verts, rec[6:9]), _add(vmap, verts, rec[9:12])))


_CHUNK = 1024 * 1024
_MAX_LINE = 4096
_LINE_SPLIT = re.compile(rb"\r\n|\n|\r")          # \n, \r\n and a lone \r, like parse_stl's splitlines


def _plain_text(head: bytes) -> bool:
    """Plausibly TEXT: no NUL in the first KB and valid UTF-8 (a multi-byte character cut by the end of the
    window is fine). A name such as ``solid Würfel`` is text; random binary is not."""
    first = head[:1024]
    if b"\x00" in first:
        return False
    try:
        first.decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc.reason == "unexpected end of data" and exc.end >= len(first)
    return True


def _looks_like_ascii_stl(head: bytes) -> bool:
    """A "solid"/"facet" start on a file that is plausibly TEXT."""
    if not _plain_text(head):
        return False
    low = head.lstrip().lower()
    return low.startswith(b"solid") or b"facet" in head.lower()


def decode_stl_stream(fh, size: int, *, max_triangles: int, max_vertices: int, check=lambda: None,
                      batch: int = _BATCH):
    """Decode an STL from an open binary file without ever holding more than the caller's budget.

    The kind is decided from the 84-byte header AND the file size: a size equal to ``84 + 50 * N`` is
    binary; so is a file whose first KB is not plausible text, and for those a declared ``N`` over
    ``max_triangles`` is rejected IMMEDIATELY, before any triangle (or any large buffer) exists, whether or
    not the size matches. Only plausible ASCII goes down the text path, which reads <= 1 MiB at a time,
    refuses any line over 4 KiB, splits on LF, CRLF and a lone CR, keeps a running triangle counter and
    calls ``check()`` (the cancel/deadline hook) per chunk. Binary decoding runs in batches of ``batch``
    triangles with ``check()`` between them. Vertices are de-duplicated exactly as ``parse_stl`` does.
    Raises ``StlTooLarge`` or ``SnapStudioError``.
    """
    head = fh.read(84)
    verts: list[tuple] = []
    tris: list[tuple] = []
    vmap: dict = {}
    if len(head) >= 84:
        (n,) = struct.unpack_from("<I", head, 80)
        consistent = 84 + n * 50 == size
        first = head + fh.read(1024 - 84) if not consistent else head
        if consistent or not _plain_text(first):
            if n > max_triangles:
                raise StlTooLarge(n, max_triangles)
            if not consistent:
                raise SnapStudioError("STL size does not match its header")
            remaining = n
            while remaining:
                check()
                take = min(batch, remaining)
                raw = fh.read(take * 50)
                if len(raw) != take * 50:
                    raise SnapStudioError("STL ended early")
                _decode_binary_batch(raw, vmap, verts, tris)
                if len(verts) > max_vertices:
                    raise StlTooLarge(len(verts), max_vertices, "vertices")
                remaining -= take
            if not tris:
                raise SnapStudioError("STL contained no triangles")
            return verts, tris
        fh.seek(0)
        head_for_text = first
    else:
        fh.seek(0)
        head_for_text = head
    if not _looks_like_ascii_stl(head_for_text):
        raise SnapStudioError("unrecognized STL (not binary-size-consistent or ASCII)")
    fh.seek(0)
    cur: list[tuple] = []
    carry = b""

    def feed(line: bytes) -> None:
        nonlocal cur
        if len(line) > _MAX_LINE:
            raise SnapStudioError("STL has a line longer than 4096 bytes")
        s = line.strip()
        if s.startswith(b"vertex"):
            _, x, y, z = s.split()[:4]
            cur.append((float(x), float(y), float(z)))
            if len(cur) == 3:
                tris.append(tuple(_add(vmap, verts, p) for p in cur))
                cur = []
                if len(tris) > max_triangles:
                    raise StlTooLarge(len(tris), max_triangles)
                if len(verts) > max_vertices:
                    raise StlTooLarge(len(verts), max_vertices, "vertices")

    while True:
        check()
        chunk = fh.read(_CHUNK)
        if not chunk:
            break
        parts = _LINE_SPLIT.split(carry + chunk)
        carry = parts.pop()
        if len(carry) > _MAX_LINE:
            raise SnapStudioError("STL has a line longer than 4096 bytes")
        for line in parts:
            feed(line)
    if carry:
        feed(carry)
    if not tris:
        raise SnapStudioError("STL contained no triangles")
    return verts, tris
