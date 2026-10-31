"""Constrained execution for a user-configured local engine executable."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_TOKEN = re.compile(r"\A(?:[^{}\x00\r\n]*|\{(?:job_dir|output_dir|input)\})+\Z")
_SAFE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_KIND = {".3mf": "3mf", ".stl": "stl", ".obj": "obj", ".glb": "glb", ".png": "png", ".json": "json"}
_MAX_SCAN_ENTRIES = 10000
_MAX_SCAN_DEPTH = 32
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


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

    Every run gets a fresh directory created beneath `job_root`; process cancellation
    targets only the exact Popen object created by this runner.
    """

    def __init__(self, executable: str | os.PathLike[str], job_root: str | os.PathLike[str],
                 argument_template: Sequence[str], *, timeout_s: float = 300.0,
                 output_limit: int = 1024 * 1024,
                 artifact_limit: int = 512 * 1024 * 1024) -> None:
        self.executable = Path(executable).expanduser().resolve(strict=True)
        if not self.executable.is_file():
            raise RunnerError("executable_invalid")
        if self.executable.suffix.lower() in {".bat", ".cmd"}:
            raise RunnerError("executable_script_refused")
        self.job_root = Path(job_root).expanduser().resolve(strict=True)
        if not self.job_root.is_dir():
            raise RunnerError("job_root_invalid")
        if not isinstance(argument_template, (tuple, list)) or not all(
                isinstance(arg, str) and _TOKEN.fullmatch(arg) for arg in argument_template):
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
        self._active: dict[int, subprocess.Popen[bytes]] = {}

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
        try:
            process = subprocess.Popen(command, cwd=str(job_dir), shell=False,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        except OSError:
            raise RunnerError("process_start_failed") from None
        try:
            with self._lock:
                self._active[process.pid] = process
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
                    self._stop_owned(process)
                    raise RunnerError("cancelled", stdout=bytes(stdout.data))
                if overflow.is_set():
                    self._stop_owned(process)
                    raise RunnerError("output_limit_exceeded", stdout=bytes(stdout.data))
                try:
                    output_size = self._output_size(output_dir)
                except RunnerError:
                    self._stop_owned(process)
                    raise
                if output_size > self.artifact_limit:
                    self._stop_owned(process)
                    raise RunnerError("artifact_output_limit_exceeded", stdout=bytes(stdout.data))
                if time.monotonic() >= deadline:
                    self._stop_owned(process)
                    raise RunnerError("timeout", stdout=bytes(stdout.data))
                time.sleep(0.02)
            for reader in readers:
                reader.join(timeout=0.1)
            if overflow.is_set():
                raise RunnerError("output_limit_exceeded", stdout=bytes(stdout.data))
            code = process.returncode
            if code != 0:
                raise RunnerError("process_failed", stdout=bytes(stdout.data))
            return RunnerResult(job_dir, int(code), bytes(stdout.data), self._manifest(output_dir))
        finally:
            if process.poll() is None:
                self._stop_owned(process)
            with self._lock:
                self._active.pop(process.pid, None)
            # A descendant may still hold an inherited pipe. Closing its BufferedReader
            # while a daemon reader is blocked in read() waits on that reader's lock.
            # Leave ownership with the reader; it closes when EOF arrives.

    def cancel(self, pid: int) -> bool:
        """Terminate a process only when its PID maps to this runner's live Popen handle."""
        with self._lock:
            process = self._active.get(pid)
        if process is None or process.poll() is not None:
            return False
        self._stop_owned(process)
        return True

    @staticmethod
    def _stop_owned(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                if process.poll() is not None:
                    return
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    if process.poll() is not None:
                        return
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    # The runner has made a bounded terminate/kill attempt. Never let
                    # cleanup itself turn the configured deadline into an unbounded wait.
                    return

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
