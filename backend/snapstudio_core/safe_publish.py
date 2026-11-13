"""Publish a new local file without a validate-then-write race on the output directory.

`publish_new_file(target, data)` writes `data` to `target` only if `target` does not exist, and
never replaces anything. The directory that will hold the file is opened ONCE ("pinned") and every
later operation goes through that pin, so a later swap of the directory, or of any ancestor, cannot
redirect the write:

* POSIX: the directory is held as a file descriptor and the temporary file, the no-replace link and
  the cleanup are all `dir_fd`-relative. The pinned directory's real path is checked for
  network/device locations after the pin, from the descriptor (`/proc/self/fd`, or `F_GETPATH` on macOS).
* Windows: the directory is opened with a share mode that omits FILE_SHARE_DELETE, so the directory
  and its ancestors cannot be renamed, replaced or removed while the handle is held. The final path
  is read from the handle and checked for network/device locations; the file operations then use that
  final path.

Remaining limits (stated, not hidden): this is not a sandbox. Anyone who can already write inside the
pinned directory can still create or remove entries there, and a platform that can neither report the
pinned directory's path nor pin it is refused (`UnsafeOutput`) rather than written best-effort.
"""
from __future__ import annotations

import os
import secrets
import sys

from snapstudio_core import localpath


class UnsafeOutput(Exception):
    """The output location could not be pinned and verified as a local directory."""


def _after_pin() -> None:
    """Seam for tests: runs after the directory is pinned and verified, before any file is created."""


def _check_name(name: str) -> None:
    if not name or name in (".", "..") or "\x00" in name or any(sep in name for sep in ("/", "\\")):
        raise UnsafeOutput("the output must be a plain file name")


def _tmp_name(name: str) -> str:
    return f".{name}.{secrets.token_hex(6)}.tmp"


def publish_new_file(target: str, data: bytes, mode: int = 0o600) -> None:
    """Create `target` with `data`; FileExistsError if it exists; UnsafeOutput if not pinnable/local."""
    absolute = os.path.abspath(target)
    parent, name = os.path.split(absolute)
    _check_name(name)
    if sys.platform == "win32":
        _publish_windows(parent, name, data)
    else:
        _publish_posix(parent, name, data, mode)


# ---------------------------------------------------------------- POSIX

def _pinned_path_posix(dfd: int) -> str:
    if sys.platform.startswith("linux"):
        return os.path.realpath(f"/proc/self/fd/{dfd}")
    try:
        import fcntl
        raw = fcntl.fcntl(dfd, getattr(fcntl, "F_GETPATH"), b"\0" * 1024)
        return os.fsdecode(raw.split(b"\0", 1)[0])
    except (ImportError, AttributeError, OSError):
        raise UnsafeOutput("this platform cannot report the output directory's real path") from None


def _publish_posix(parent: str, name: str, data: bytes, mode: int) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        dfd = os.open(parent, flags)
    except OSError as error:
        raise UnsafeOutput("the output directory could not be opened") from error
    tmp = None
    try:
        real = _pinned_path_posix(dfd)
        if not real or localpath._reaches_network(real):
            raise UnsafeOutput("the output directory is not a local directory")
        _after_pin()
        tmp = _tmp_name(name)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=dfd)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)   # refuses an existing name
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
        os.close(dfd)


# ---------------------------------------------------------------- Windows

def _publish_windows(parent: str, name: str, data: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    FILE_LIST_DIRECTORY = 0x0001
    SHARE_READ_WRITE = 0x1 | 0x2                      # deliberately NOT FILE_SHARE_DELETE (0x4)
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    invalid = wintypes.HANDLE(-1).value

    handle = kernel32.CreateFileW(parent, FILE_LIST_DIRECTORY, SHARE_READ_WRITE, None, OPEN_EXISTING,
                                  FILE_FLAG_BACKUP_SEMANTICS, None)
    if handle in (None, invalid):
        raise UnsafeOutput("the output directory could not be opened")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise UnsafeOutput("the output directory's real path could not be read")
        real = buffer.value
        if real.upper().startswith("\\\\?\\UNC\\"):
            raise UnsafeOutput("the output directory is not a local directory")
        if real.startswith("\\\\?\\") and len(real) > 6 and real[5] == ":":
            real = real[4:]                           # \\?\C:\dir -> C:\dir (a plain local drive path)
        if localpath._reaches_network(real):
            raise UnsafeOutput("the output directory is not a local directory")
        _after_pin()
        destination = os.path.join(real, name)
        tmp = os.path.join(real, _tmp_name(name))
        try:
            with open(tmp, "xb") as out:
                out.write(data)
            os.rename(tmp, destination)               # atomic and refuses an existing name on Windows
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    finally:
        kernel32.CloseHandle(handle)
