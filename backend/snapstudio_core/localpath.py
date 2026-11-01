"""One guard for every user-supplied file path the Studio+ tracks open.

Studio is meant to read local files only. A network (UNC) path in any slash style, a Windows device path, a symlink or
junction that points at one of those, and anything that is not a regular file under the size cap is refused
before the engine opens, hashes or lists it. The checks are lexical first; the link walk then looks at each path
component with `lstat` (which never follows the component being examined) and reads a link's target text with
`readlink`, so a link to a network share is rejected without the engine ever connecting to it.

These are best-effort checks, not a filesystem sandbox or an absolute no-network guarantee: the check and the
later open are separate steps, so a process that can modify the path or its ancestors in between can redirect
the operation. Callers that write (`passport export -o`) document that limit for their own output.

Known limit: a mapped network drive letter looks like a local volume to the operating system, so it is allowed.
That is the user's own storage, chosen by them; Studio does not look behind a drive letter. On Linux and macOS a
mounted network filesystem looks local in the same way, and only UNC-style strings and link targets are refused.
"""
from __future__ import annotations

import os
import stat

MAX_LOCAL_FILE_BYTES = 2 * 1024 ** 3
_MAX_LINK_DEPTH = 8
# Windows reparse tags that redirect a path elsewhere: symlink and junction. Cloud placeholders are not links.
_REDIRECTING_REPARSE_TAGS = {0xA000000C, 0xA0000003}


def is_network_or_device_path(path: str) -> bool:
    """UNC shares and the `\\\\?\\` / `\\\\.\\` device namespaces, in any mix of slash styles."""
    return isinstance(path, str) and path.replace("/", "\\").startswith("\\\\")


def _plain_drive_target(target: str) -> str:
    r"""Windows readlink returns a link to C:\x as \\?\C:\x; that is a local drive, not a device namespace.

    The UNC form (\\?\UNC\...), the \\.\ form and volume-GUID forms keep their prefix and stay refused."""
    if len(target) >= 7 and target[:4] == "\\\\?\\" and "A" <= target[4].upper() <= "Z" and target[5:7] == ":\\":
        return target[4:]
    return target


def _is_redirect(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) in _REDIRECTING_REPARSE_TAGS


def _reaches_network(path: str, depth: int = 0) -> bool:
    """True when the path, or any link on the way to it, names a network or device location."""
    if is_network_or_device_path(path):
        return True
    if depth > _MAX_LINK_DEPTH:
        return True                                          # too many links to follow safely: refuse
    absolute = os.path.abspath(path)                         # no filesystem access
    if is_network_or_device_path(absolute):
        return True
    drive, rest = os.path.splitdrive(absolute)
    current = drive + os.sep
    for part in [piece for piece in rest.split(os.sep) if piece]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return False                                     # nothing further exists to follow
        except (OSError, ValueError):
            return True
        if _is_redirect(info):
            try:
                target = os.readlink(current)
            except (OSError, ValueError):
                return True
            target = _plain_drive_target(target)
            if not os.path.isabs(target) and not is_network_or_device_path(target):
                target = os.path.join(os.path.dirname(current), target)
            if _reaches_network(target, depth + 1):
                return True
    return False


def is_local_regular_file(path: object, *, max_bytes: int = MAX_LOCAL_FILE_BYTES) -> bool:
    """True only for a regular file on a local volume no larger than `max_bytes`. Never raises."""
    if not isinstance(path, str) or not path or "\x00" in path or _reaches_network(path):
        return False
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= max_bytes


def is_local_directory(path: object) -> bool:
    """True only for an existing directory that is not a network or device location. Never raises."""
    if not isinstance(path, str) or not path or "\x00" in path or _reaches_network(path):
        return False
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def usable_path(path: str | None, *, max_bytes: int = MAX_LOCAL_FILE_BYTES) -> str | None:
    """`path` unless opening it could leave the machine or hash an oversize file; None means treat as unverified.

    A missing path is returned as is, so callers still report it as missing.
    """
    if not isinstance(path, str) or not path or "\x00" in path or _reaches_network(path):
        return None
    try:
        if os.path.isfile(path) and os.path.getsize(path) > max_bytes:
            return None
    except (OSError, ValueError):
        return None
    return path
