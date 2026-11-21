"""Explicit local handoff for generated Lumina models. No service request or writes."""
from __future__ import annotations
import hashlib
import io
import zipfile
import os
import re
import stat
from . import local_input
from ..creative.container import ContainerError, MAX_ARCHIVE_BYTES, MAX_MEMBER_BYTES, read_3mf

NAME = re.compile(r'lumina-[0-9a-f]{12}(?:-[2-9][0-9]*|-[1-9][0-9]+)?\.3mf\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')


def verified_model(directory, name, expected):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('Choose a generated 3MF model, not a preview image or arbitrary file.')
    if not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise ValueError('The generated file identity is missing.')
    if not name.startswith('lumina-' + expected[:12]):
        raise ValueError('The generated name does not match its identity.')
    if not local_input.is_local_directory(directory):
        raise ValueError('The output folder is no longer a local directory.')
    target = os.path.join(directory, name)
    if not local_input.is_local_regular_file(target, max_bytes=MAX_ARCHIVE_BYTES) or os.path.islink(target):
        raise ValueError('The generated model is missing, redirected or too large.')
    resolved = os.path.realpath(target)
    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('The generated model is not a regular file.')
        opened = os.fstat(handle.fileno())
        data = handle.read(MAX_ARCHIVE_BYTES + 1)
        current = os.stat(resolved)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("The generated model path changed while opening.")
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('The generated model changed since it was saved. Generate or inspect it again.')
    try:
        # Enforce UTF-8 before the legacy container reader can sniff another XML
        # encoding. Model XML entities are never evaluated at this boundary.
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo('3D/3dmodel.model')
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError('Model XML exceeds reader limits.')
            with archive.open(info) as model:
                xml = model.read(MAX_MEMBER_BYTES + 1).decode('utf-8-sig')
            if len(xml) > MAX_MEMBER_BYTES or '\x00' in xml or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
                raise ValueError('Unsafe model XML.')
        read_3mf(data)
    except (ContainerError, zipfile.BadZipFile, KeyError, UnicodeError):
        raise ValueError('The service output is not a supported 3MF container. Nothing was opened.') from None
    return resolved
