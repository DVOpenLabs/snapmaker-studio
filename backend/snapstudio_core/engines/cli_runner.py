"""Constrained execution for a user-configured local engine executable."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_PLACEHOLDER = re.compile(r"\{(?:job_dir|output_dir|input)\}")
_FORBIDDEN = re.compile(r"[{}\x00\r\n]")


def _template_ok(arg: object) -> bool:
    """Only the three known placeholders may contain braces. Linear time: the previous single pattern had the (a*)+
    shape and backtracked exponentially on a long argument that failed late."""
    return isinstance(arg, str) and not _FORBIDDEN.search(_PLACEHOLDER.sub("", arg))
_SAFE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_KIND = {".3mf": "3mf", ".stl": "stl", ".obj": "obj", ".glb": "glb", ".png": "png", ".json": "json"}
_MAX_SCAN_ENTRIES = 10000
_MAX_SCAN_DEPTH = 32
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_SLICER_NAMES = {"orca", "snapmaker-orca", "bambu", "prusa", "slic3r", "superslicer", "cura", "kiri"}
_WINDOWS_LAUNCHER = (
    "import json,subprocess,sys; command=json.loads(sys.argv[1]); "
    "sys.exit(subprocess.call(command, stdin=subprocess.DEVNULL, shell=False)) "
    "if sys.stdin.buffer.read(1) == b'\\x01' else sys.exit(125)"
)


def _is_own_interpreter(path: Path) -> bool:
    try:
        return path == Path(sys.executable).resolve(strict=True)
    except OSError:
        return False


def _hash_approved(path: Path, approved: Sequence[str]) -> bool:
    """True when the file's SHA-256 is one the caller pinned. Hash comparison is done on the bytes read now."""
    pins = {item.lower() for item in approved if isinstance(item, str) and re.fullmatch(r"[0-9a-fA-F]{64}", item)}
    if not pins:
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() in pins


def _executable_policy_refused(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name in _SLICER_NAMES or "slicer" in name


class _WindowsJob:
    """A kill-on-close Job Object containing this runner's child process tree."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        import ctypes

        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                     ctypes.c_void_p, wintypes.DWORD)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")
        if not kernel32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "AssignProcessToJobObject failed")

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


class RunnerError(Exception):
    """Safe runner refusal or bounded execution failure."""

    def __init__(self, code: str, *, stdout: bytes = b"") -> None:
        self.code = code
        self.stdout = stdout
        super().__init__(code)


@dataclass(frozen=True)
class RunnerResult:
    job_dir: Path
    returncode: int
    stdout: bytes
    artifacts: tuple[dict[str, object], ...]


class _Capture:
    def __init__(self, cap: int, stop: threading.Event, lock: threading.Lock,
                 total: list[int]) -> None:
        self.cap = cap
        self.stop = stop
        self.lock = lock
        self.shared_total = total
        self.data = bytearray()
        self.total = 0

    def drain(self, stream: object) -> None:
        while True:
            try:
                chunk = stream.read(4096)  # type: ignore[attr-defined]
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                room = max(0, self.cap - self.shared_total[0])
                self.shared_total[0] += len(chunk)
                self.total += len(chunk)
                self.data.extend(chunk[:room])
                if self.shared_total[0] > self.cap:
                    self.stop.set()
                    return


class CliRunner:
    """Run a fixed executable and argument template without a shell.

    Every run gets a fresh directory created beneath `job_root`. Processes run in a
    private process group (POSIX) or kill-on-close Job Object (Windows), so stop
    operations only affect the tree this runner started. The executable-name policy
    is a safety rail, not a sandbox or a guarantee.
    """

    def __init__(self, executable: str | os.PathLike[str], job_root: str | os.PathLike[str],
                 argument_template: Sequence[str], *, timeout_s: float = 300.0,
                 output_limit: int = 1024 * 1024,
                 artifact_limit: int = 512 * 1024 * 1024,
                 approved_sha256: Sequence[str] = ()) -> None:
        self.executable = Path(executable).expanduser().resolve(strict=True)
        if not self.executable.is_file():
            raise RunnerError("executable_invalid")
        if self.executable.suffix.lower() in {".bat", ".cmd"}:
            raise RunnerError("executable_script_refused")
        if _executable_policy_refused(self.executable):
            raise RunnerError("executable_policy_refused")
        # Admission is by identity, not by name: the caller pins the SHA-256 of the one executable it approves.
        # Only the interpreter running Studio is admitted without a pin. A renamed copy of anything else has a
        # different path and, unless its bytes were pinned, no approval.
        if not _is_own_interpreter(self.executable) and not _hash_approved(self.executable, approved_sha256):
            raise RunnerError("executable_not_approved")
        self.job_root = Path(job_root).expanduser().resolve(strict=True)
        if not self.job_root.is_dir():
            raise RunnerError("job_root_invalid")
        if not isinstance(argument_template, (tuple, list)) or not all(
                _template_ok(arg) for arg in argument_template):
            raise RunnerError("argument_template_invalid")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 3600:
            raise RunnerError("timeout_invalid")
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 1024 <= output_limit <= 64 * 1024 * 1024:
            raise RunnerError("output_limit_invalid")
        if isinstance(artifact_limit, bool) or not isinstance(artifact_limit, int) \
                or not 1 <= artifact_limit <= 2 * 1024 * 1024 * 1024:
            raise RunnerError("artifact_limit_invalid")
        self.argument_template = tuple(argument_template)
        self.timeout_s = float(timeout_s)
        self.output_limit = output_limit
        self.artifact_limit = artifact_limit
        self._lock = threading.Lock()
        self._active: dict[int, tuple[subprocess.Popen[bytes], _WindowsJob | None]] = {}

    def run(self, *, inputs: Mapping[str, str] | None = None,
            cancel_event: threading.Event | None = None) -> RunnerResult:
        if inputs is None:
            inputs = {}
        if not isinstance(inputs, Mapping) or any(not _SAFE_NAME.fullmatch(k) or not isinstance(v, str) for k, v in inputs.items()):
            raise RunnerError("input_invalid")
        run_id = uuid.uuid4().hex
        job_dir = (self.job_root / run_id).resolve()
        if not job_dir.is_relative_to(self.job_root):
            raise RunnerError("job_path_invalid")
        try:
            return self._run_job(job_dir, inputs, cancel_event)
        except BaseException:
            self._remove_job_dir(job_dir)
            raise

    def _run_job(self, job_dir: Path, inputs: Mapping[str, str],
                 cancel_event: threading.Event | None) -> RunnerResult:
        job_dir.mkdir(mode=0o700)
        output_dir = job_dir / "output"
        output_dir.mkdir()
        input_paths: dict[str, str] = {}
        for name, value in inputs.items():
            source = Path(value).expanduser().resolve(strict=True)
            if not source.is_file():
                raise RunnerError("input_invalid")
            staged = job_dir / "input" / name
            staged.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, staged)
            input_paths[name] = str(staged)
        values = {"job_dir": str(job_dir), "output_dir": str(output_dir),
                  "input": next(iter(input_paths.values()), "")}
        for arg in self.argument_template:
            if "{input}" in arg and len(input_paths) != 1:
                raise RunnerError("input_placeholder_ambiguous")
        rendered = [re.sub(r"\{(job_dir|output_dir|input)\}",
                           lambda match: values[match.group(1)], arg)
                    for arg in self.argument_template]
        command = [str(self.executable), *rendered]
        windows_job: _WindowsJob | None = None
        try:
            launch_command = command
            launch_stdin = subprocess.DEVNULL
            if os.name == "nt":
                # The helper waits before starting the configured engine. This lets
                # the runner assign the helper to its Job Object first, so even a
                # fast engine cannot spawn a descendant outside that job.
                launch_command = [sys.executable, "-c", _WINDOWS_LAUNCHER, json.dumps(command)]
                launch_stdin = subprocess.PIPE
            process = subprocess.Popen(launch_command, cwd=str(job_dir), shell=False,
                                       stdin=launch_stdin, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       start_new_session=(os.name != "nt"))
            if os.name == "nt":
                try:
                    windows_job = _WindowsJob(process)
                except OSError:
                    self._stop_owned(process, windows_job)
                    raise RunnerError("process_job_assignment_failed") from None
                try:
                    assert process.stdin is not None
                    process.stdin.write(b"\x01")
                    process.stdin.flush()
                    process.stdin.close()
                except OSError:
                    self._stop_owned(process, windows_job)
                    raise RunnerError("process_start_failed") from None
        except OSError:
            raise RunnerError("process_start_failed") from None
        try:
            with self._lock:
                self._active[process.pid] = (process, windows_job)
            overflow = threading.Event()
            budget_lock = threading.Lock()
            output_total = [0]
            stdout = _Capture(self.output_limit, overflow, budget_lock, output_total)
            stderr = _Capture(self.output_limit, overflow, budget_lock, output_total)
            readers = [threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
                       threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True)]
            for reader in readers:
                reader.start()
            deadline = time.monotonic() + self.timeout_s
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop_owned(process, windows_job)
                    raise RunnerError("cancelled", stdout=bytes(stdout.data))
                if overflow.is_set():
                    self._stop_owned(process, windows_job)
                    raise RunnerError("output_limit_exceeded", stdout=bytes(stdout.data))
                try:
                    output_size = self._output_size(output_dir)
                except RunnerError:
                    self._stop_owned(process, windows_job)
                    raise
                if output_size > self.artifact_limit:
                    self._stop_owned(process, windows_job)
                    raise RunnerError("artifact_output_limit_exceeded", stdout=bytes(stdout.data))
                if time.monotonic() >= deadline:
                    self._stop_owned(process, windows_job)
                    raise RunnerError("timeout", stdout=bytes(stdout.data))
                time.sleep(0.02)
            # The direct process can exit while a descendant still holds inherited
            # pipes or continues writing. Close the runner-owned tree before scanning.
            self._stop_owned(process, windows_job)
            for reader in readers:
                reader.join(timeout=0.1)
            if overflow.is_set():
                raise RunnerError("output_limit_exceeded", stdout=bytes(stdout.data))
            code = process.returncode
            if code != 0:
                raise RunnerError("process_failed", stdout=bytes(stdout.data))
            return RunnerResult(job_dir, int(code), bytes(stdout.data), self._manifest(output_dir))
        finally:
            self._stop_owned(process, windows_job)
            if windows_job is not None:
                windows_job.close()
            with self._lock:
                self._active.pop(process.pid, None)
            # A descendant may still hold an inherited pipe. Closing its BufferedReader
            # while a daemon reader is blocked in read() waits on that reader's lock.
            # Leave ownership with the reader; it closes when EOF arrives.

    def cancel(self, pid: int) -> bool:
        """Terminate a process only when its PID maps to this runner's live Popen handle."""
        with self._lock:
            active = self._active.get(pid)
        if active is None:
            return False
        self._stop_owned(*active)
        return True

    @staticmethod
    def _stop_owned(process: subprocess.Popen[bytes], windows_job: _WindowsJob | None = None) -> None:
        if os.name == "nt":
            if windows_job is not None:
                windows_job.close()
            if process.poll() is None:
                if windows_job is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                # Cleanup remains bounded even if the OS cannot stop the child.
                pass

    def cleanup(self, result: RunnerResult) -> None:
        """Remove a successful run's job directory after its caller has read artifacts."""
        if not isinstance(result, RunnerResult):
            raise RunnerError("result_invalid")
        self._remove_job_dir(result.job_dir)

    def _remove_job_dir(self, job_dir: Path) -> None:
        try:
            resolved = job_dir.resolve(strict=False)
            if resolved.parent != self.job_root or not re.fullmatch(r"[0-9a-f]{32}", resolved.name):
                return
            shutil.rmtree(resolved, ignore_errors=True)
        except OSError:
            # Cleanup is best effort and must not mask the original engine outcome.
            pass

    @staticmethod
    def _iter_output_files(output_dir: Path):
        stack: list[tuple[Path, int]] = [(output_dir, 0)]
        visited = 0
        try:
            # The root is checked like every entry: an engine that swaps its (initially empty) output
            # directory for a link or junction must not make an outside tree look like job output.
            root = os.lstat(output_dir)
            if (output_dir.is_symlink() or getattr(output_dir, "is_junction", lambda: False)()
                    or getattr(root, "st_file_attributes", 0) & _REPARSE_POINT):
                raise RunnerError("artifact_symlink_refused")
            if not stat.S_ISDIR(root.st_mode):
                raise RunnerError("artifact_scan_failed")
            while stack:
                directory, depth = stack.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > _MAX_SCAN_ENTRIES:
                            raise RunnerError("artifact_scan_limit_exceeded")
                        path = Path(entry.path)
                        try:
                            info = entry.stat(follow_symlinks=False)
                            junction = getattr(path, "is_junction", lambda: False)()
                            symlink = path.is_symlink()
                        except OSError:
                            raise RunnerError("artifact_scan_failed") from None
                        if symlink or junction or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
                            raise RunnerError("artifact_symlink_refused")
                        if stat.S_ISDIR(info.st_mode):
                            if depth >= _MAX_SCAN_DEPTH:
                                raise RunnerError("artifact_scan_limit_exceeded")
                            stack.append((path, depth + 1))
                        elif stat.S_ISREG(info.st_mode):
                            yield path, info.st_size
        except OSError:
            raise RunnerError("artifact_scan_failed") from None

    def _output_size(self, output_dir: Path) -> int:
        total = 0
        for _, size in self._iter_output_files(output_dir):
            total += size
            if total > self.artifact_limit:
                return total
        return total

    def _manifest(self, output_dir: Path) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = []
        total = 0
        try:
            base = output_dir.resolve(strict=True)
        except OSError:
            raise RunnerError("artifact_scan_failed") from None
        for path, observed_size in sorted(self._iter_output_files(output_dir), key=lambda item: item[0]):
            try:
                if not path.resolve(strict=True).is_relative_to(base):
                    raise RunnerError("artifact_path_escape")
            except OSError:
                raise RunnerError("artifact_scan_failed") from None
            name = path.relative_to(output_dir).as_posix()
            parts = name.split("/")
            if any(part in ("", ".", "..") or not _SAFE_NAME.fullmatch(part) for part in parts):
                raise RunnerError("artifact_name_invalid")
            digest = hashlib.sha256()
            size = 0
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        size += len(chunk)
                        total += len(chunk)
                        if size > self.artifact_limit or total > self.artifact_limit:
                            raise RunnerError("artifact_too_large")
                        digest.update(chunk)
            except OSError:
                raise RunnerError("artifact_scan_failed") from None
            if size != observed_size:
                raise RunnerError("artifact_scan_failed")
            entries.append({"name": name, "sha256": digest.hexdigest(), "size_bytes": size,
                            "kind": _KIND.get(path.suffix.lower(), "unknown")})
        return tuple(entries)
