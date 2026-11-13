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
  is read from the handle and checked for network/device locations. A junction cannot be renamed in, but
  it can be set in place on an empty directory, so the final name is created exclusively with sharing
  off, and the file HANDLE's own final path must equal the verified directory plus the name; a mismatch
  discards the empty file before any content is written.

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
    separators = ("/", "\\") if sys.platform == "win32" else ("/",)
    if not name or name in (".", "..") or "\x00" in name or any(sep in name for sep in separators):
        raise UnsafeOutput("the output must be a plain file name")


def _tmp_name() -> str:
    """A bounded temporary name that does not depend on the destination name (NAME_MAX safe)."""
    return f".snapstudio-{secrets.token_hex(8)}.tmp"


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
        try:
            resolved = os.readlink(f"/proc/self/fd/{dfd}")      # fails closed when /proc is unavailable
        except OSError:
            raise UnsafeOutput("this system cannot report the output directory's real path") from None
        if not os.path.isabs(resolved) or resolved.endswith(" (deleted)"):
            raise UnsafeOutput("the output directory's real path could not be verified")
        return resolved
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
        tmp = _tmp_name()
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
    """Pin the directory, then create the FINAL name exclusively and verify where it really landed.

    Holding the directory handle (no FILE_SHARE_DELETE) stops a rename or delete of the directory and its
    ancestors, but an actor with write access to an EMPTY directory can still turn it into a junction in
    place. So the file handle itself is checked: after the exclusive create (CREATE_NEW, share mode none, so
    nobody can read a partial file) its final path must sit directly inside the pinned directory's path;
    otherwise the just-created empty file is deleted through the handle and nothing is written. The residual
    exposure is an empty, immediately removed file in the redirected location; no passport content is written.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                   wintypes.LPVOID]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    FILE_LIST_DIRECTORY = 0x0001
    GENERIC_WRITE = 0x40000000
    DELETE = 0x00010000
    SHARE_READ_WRITE = 0x1 | 0x2                      # deliberately NOT FILE_SHARE_DELETE (0x4)
    OPEN_EXISTING, CREATE_NEW = 3, 1
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_ATTRIBUTE_NORMAL = 0x80
    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    FILE_DISPOSITION_INFO = 4
    ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS = 80, 183
    invalid = wintypes.HANDLE(-1).value

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", FILETIME), ("accessed", FILETIME),
                    ("written", FILETIME), ("volume", wintypes.DWORD), ("size_hi", wintypes.DWORD),
                    ("size_lo", wintypes.DWORD), ("links", wintypes.DWORD), ("index_hi", wintypes.DWORD),
                    ("index_lo", wintypes.DWORD)]

    def final_path(h) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(h, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise UnsafeOutput("a real path could not be read")
        text = buffer.value
        if text.upper().startswith("\\\\?\\UNC\\"):
            raise UnsafeOutput("the output location is not local")
        if text.startswith("\\\\?\\") and len(text) > 6 and text[5] == ":":
            text = text[4:]                           # strip the extended-length prefix from a local drive path
        return text

    def is_reparse(h) -> bool:
        info = BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(h, ctypes.byref(info)):
            raise UnsafeOutput("the output directory could not be inspected")
        return bool(info.attributes & FILE_ATTRIBUTE_REPARSE_POINT)

    directory = kernel32.CreateFileW(parent, FILE_LIST_DIRECTORY, SHARE_READ_WRITE, None, OPEN_EXISTING,
                                     FILE_FLAG_BACKUP_SEMANTICS, None)
    if directory in (None, invalid):
        raise UnsafeOutput("the output directory could not be opened")
    out = None
    try:
        real = final_path(directory)
        if localpath._reaches_network(real):
            raise UnsafeOutput("the output directory is not a local directory")
        _after_pin()
        if is_reparse(directory):                     # turned into a link in place after the pin
            raise UnsafeOutput("the output directory was redirected")
        destination = os.path.join(real, name)
        out = kernel32.CreateFileW(destination, GENERIC_WRITE | DELETE, 0, None, CREATE_NEW,
                                   FILE_ATTRIBUTE_NORMAL, None)
        if out in (None, invalid):
            if ctypes.get_last_error() in (ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS):
                raise FileExistsError(destination)
            raise OSError(ctypes.get_last_error(), "the passport could not be created")

        def discard():
            flag = wintypes.DWORD(1)
            kernel32.SetFileInformationByHandle(out, FILE_DISPOSITION_INFO, ctypes.byref(flag), ctypes.sizeof(flag))

        try:
            landed = final_path(out)
            expected = os.path.normcase(os.path.normpath(destination))
            if os.path.normcase(os.path.normpath(landed)) != expected or localpath._reaches_network(landed):
                raise UnsafeOutput("the output was redirected away from the verified directory")
            view = memoryview(data)
            while len(view):
                written = wintypes.DWORD(0)
                chunk = bytes(view[: 1 << 20])
                if not kernel32.WriteFile(out, chunk, len(chunk), ctypes.byref(written), None):
                    raise OSError(ctypes.get_last_error(), "the passport could not be written")
                view = view[written.value:]
        except BaseException:
            discard()
            raise
    finally:
        if out not in (None, invalid):
            kernel32.CloseHandle(out)
        kernel32.CloseHandle(directory)
