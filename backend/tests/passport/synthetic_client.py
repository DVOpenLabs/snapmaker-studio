"""Two synthetic clients of the `u1convert` command line. Neither is a real third-party program.

`CliClient` behaves the way an external program that shells out to Studio does: it runs the
command, parses stdout, and treats anything it cannot parse as a failure. `ManifestClient`
keeps passports nested inside its own manifest file and round-trips them through Studio.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# The passport group is attached here, in the child interpreter, until `u1convert/cli.py`
# registers it itself (a two-line change that is outside this package's file scope).
_WIRED = ("from u1convert.cli import cli; from snapstudio_core.passport_cli import passport; "
          "cli.add_command(passport); cli()")


def run_cli(*args, timeout=120):
    exe = os.environ.get("SNAPSTUDIO_CLI_EXE")
    cmd = [exe] if exe else [sys.executable, "-c", _WIRED]
    return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout)


def parse_strict(stdout: str):
    """Studio's contract: the whole of stdout is one JSON object. None when it is not."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def parse_last_brace(stdout: str):
    """What a naive caller does: take the text from the last "{" to the last "}". NOT guaranteed by Studio."""
    text = stdout.strip()
    start, end = text.rfind("{"), text.rfind("}")
    if not 0 <= start < end:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class CliClient:
    """Asks Studio about a file. Absent or invalid JSON is a failure, never a success."""

    def doctor(self, path: str) -> dict:
        proc = run_cli("doctor", path, "--json")
        data = parse_strict(proc.stdout)
        if data is None:
            return {"ok": False, "reason": f"no usable JSON (exit {proc.returncode})", "exit": proc.returncode}
        return {"ok": True, "exit": proc.returncode, "verdict": data.get("verdict"), "score": data.get("score"),
                "keys": sorted(data)}

    def passport_verify(self, passport_file: str, base_dir: str) -> dict:
        proc = run_cli("passport", "verify", passport_file, "--base-dir", base_dir)
        data = parse_strict(proc.stdout)
        if data is None:
            return {"ok": False, "reason": "no usable JSON", "exit": proc.returncode}
        return {"ok": data.get("ok") is True and proc.returncode == 0, "exit": proc.returncode, "json": data}


class ManifestClient:
    """A generic tool whose manifest nests Studio passports: {"manifest": 1, "jobs": [{"name", "passport"}]}."""

    def pack(self, jobs: dict) -> dict:
        return {"manifest": 1, "jobs": [{"name": name, "passport": doc} for name, doc in sorted(jobs.items())]}

    def unpack_through_studio(self, manifest: dict, workdir: str) -> list:
        out = []
        for job in manifest["jobs"]:
            target = os.path.join(workdir, f"{job['name']}.passport.json")
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(job["passport"], handle)
            proc = run_cli("passport", "import", target)
            data = parse_strict(proc.stdout)
            out.append({"name": job["name"], "exit": proc.returncode, "json": data})
        return out
