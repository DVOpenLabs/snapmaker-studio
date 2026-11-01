"""Best-effort guard for a user-supplied local input file or output folder.

Interim private helper for the engines track. The shared guard lives in the #140 work
(`snapstudio_core.localpath`); this module should be replaced by it once both land.

It refuses a network (UNC) path in any slash style, a Windows device path, a symlink or
junction chain that reaches one of those, anything that is not a regular file, and a file
over the caller's size cap. The checks are lexical first; the link walk then `lstat`s each
component (never following the one being examined) and reads a link's target text with
`readlink`, so a link to a network share is rejected without connecting to it.

This is best-effort, not a sandbox: the check and the later open are separate steps, so a
process that can change the path in between can redirect the operation. A mapped network
drive letter looks like a local volume and is allowed; it is the user's own storage.
"""
from __future__ import annotations

import os
import stat

_MAX_LINK_DEPTH = 8
_REDIRECTING_REPARSE_TAGS = {0xA000000C, 0xA0000003}  # symlink, junction


def is_network_or_device_path(path: object) -> bool:
    """UNC shares and the device namespaces, in any mix of slash styles."""
    if not isinstance(path, str):
        return False
    normal = path.replace("/", "\\")
    # `\\host\share`, `\\?\...`, `\\.\...` and the NT passthrough prefix `\??\...` (one leading backslash).
    return normal.startswith("\\\\") or normal.startswith("\\??\\")


def _plain_drive_target(target: str) -> str:
    # Windows readlink returns a link to C:\x as \\?\C:\x: a local drive, not a device namespace.
    if len(target) >= 7 and target[:4] == "\\\\?\\" and "A" <= target[4].upper() <= "Z" and target[5:7] == ":\\":
        return target[4:]
    return target


def _is_redirect(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in _REDIRECTING_REPARSE_TAGS


def reaches_network(path: str, depth: int = 0) -> bool:
    """True when the path, or any link on the way to it, names a network or device location."""
    if is_network_or_device_path(path):
        return True
    if depth > _MAX_LINK_DEPTH:
        return True
    absolute = os.path.abspath(path)
    if is_network_or_device_path(absolute):
        return True
    drive, rest = os.path.splitdrive(absolute)
    current = drive + os.sep
    for part in [piece for piece in rest.split(os.sep) if piece]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return False
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
            if reaches_network(target, depth + 1):
                return True
    return False


def is_local_regular_file(path: object, *, max_bytes: int) -> bool:
    """True only for a regular local file no larger than `max_bytes`. Never raises."""
    if not isinstance(path, str) or not path or "\x00" in path or reaches_network(path):
        return False
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= max_bytes


def is_local_directory(path: object) -> bool:
    """True only for an existing local directory. Never raises."""
    if not isinstance(path, str) or not path or "\x00" in path or reaches_network(path):
        return False
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False
