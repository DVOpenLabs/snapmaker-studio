"""What identifies a file's CONTENT for anything that remembers a result about it.

A remembered result is only as good as its key. Size and modification time alone miss a same-size
replacement that kept its timestamp (a copy that preserves times, a tool that rewrites in place), so the
key also carries a fingerprint of the bytes, and a result is only stored if the file is unchanged after it
was computed.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def stat_identity(path: str):
    """``(resolved path, mtime, size)`` or None."""
    try:
        resolved = Path(path).resolve()
        st = resolved.stat()
    except OSError:
        return None
    return (str(resolved), st.st_mtime_ns, st.st_size)


def file_identity(path: str):
    """The stat identity PLUS a fingerprint of the content, or None if the file cannot be read.

    For a zip (every 3MF) the fingerprint is taken from the archive's own directory: each member's name,
    size and CRC-32, which changes whenever any member's bytes do and costs a read of the directory only,
    not of a 40 MB project. Anything else is hashed whole."""
    base = stat_identity(path)
    if base is None:
        return None
    digest = hashlib.blake2b(digest_size=16)
    try:
        try:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    digest.update(f"{info.filename}|{info.file_size}|{info.CRC}|".encode("utf-8", "replace"))
        except zipfile.BadZipFile:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
    except OSError:
        return None
    return base + (digest.hexdigest(),)
