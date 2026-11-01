"""`u1convert passport export | import | verify` - the connector contract for other programs.

Contract (see docs/internal/PASSPORT.md):

* stdout is exactly ONE top-level JSON object and nothing else, in every outcome Studio handles.
  Studio does not promise that taking the text between the last "{" and "}" works: string
  values (file names, for one) may contain braces. Parse the whole of stdout.
* exit 0 = the command did what it was asked and the JSON says `"ok": true`;
  exit 1 = a handled failure or a negative answer, still with a JSON object (`"ok": false`).
* a path that does not exist is rejected by the command-line layer before any of this runs:
  exit 2, usage text on stderr, NO JSON. A caller must treat absent or invalid JSON as failure.

Nothing here writes next to or over an input: `export -o` refuses an existing file and any
path that is one of the inputs.

Known limit (accepted for the unmerged development branches): path validation and the filesystem
operations that follow it are separate steps. Another process or principal able to modify the output
directory, or any of its ancestors, after validation could redirect `export -o` (for example by
swapping the directory for a link to a network share). Use an output directory whose ancestors other
actors cannot modify. The UNC/device/link refusals and the no-overwrite rule are best-effort checks,
not a filesystem sandbox and not an absolute no-network guarantee. See docs/internal/PASSPORT.md.
"""
from __future__ import annotations

import json
import os
import tempfile
from functools import wraps
from typing import Any

import click

from snapstudio_core import localpath
from snapstudio_core.passport import build_passport, import_passport, verify_passport
from snapstudio_core.passport.model import decode_passport

MAX_PASSPORT_BYTES = 2 * 1024 * 1024
MAX_SIDE_BYTES = 1024 * 1024


class _LocalPath(click.Path):
    """click.Path that refuses network and device locations before it touches the filesystem."""

    def convert(self, value, param, ctx):
        text = os.fspath(value) if isinstance(value, (str, os.PathLike)) else ""
        if localpath._reaches_network(text):
            self.fail("Studio reads local files only.", param, ctx)
        return super().convert(value, param, ctx)


_FILE = _LocalPath(exists=True, dir_okay=False)
_DIR = _LocalPath(exists=True, file_okay=False)


def _emit(obj: dict, code: int) -> None:
    click.echo(json.dumps(obj, indent=2, ensure_ascii=True))
    raise SystemExit(code)


def _error(code: str, message: str) -> None:
    _emit({"ok": False, "error": {"code": code, "message": message}}, 1)


def _handled(fn):
    """Any failure Studio did not foresee is still one JSON object and exit 1, never a traceback."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SystemExit, click.ClickException, click.exceptions.Exit):
            raise
        except Exception:                                 # noqa: BLE001 - the contract is "always JSON"
            _error("internal", "The passport command failed unexpectedly.")
    return wrapper


def _read_json(path: str, limit: int, what: str) -> Any:
    if not localpath.is_local_regular_file(path, max_bytes=limit):
        _error("unreadable", f"The {what} file could not be read.")
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        _error("unreadable", f"The {what} file could not be read.")
    if len(data) > limit:
        _error("too_large", f"The {what} file is too large.")
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        _error("malformed_json", f"The {what} file is not valid JSON.")


def _locations(pairs: tuple) -> dict:
    out = {}
    for item in pairs:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            _error("bad_path_option", "--path takes NAME=PATH.")
        out[name] = path
    return out


@click.group()
def passport():
    """Job passport: record, import and check which files a job came from."""


@passport.command("export")
@click.option("--original", type=_FILE, default=None)
@click.option("--prepared", type=_FILE, default=None)
@click.option("--sliced", type=_FILE, default=None)
@click.option("--recipes", "recipes_file", type=_FILE, default=None, help="JSON list of virtual_recipe/1 documents")
@click.option("--mappings", "mappings_file", type=_FILE, default=None, help="JSON list of material mappings")
@click.option("-o", "--out", default=None, help="write the passport here (refuses an existing file)")
@_handled
def export_cmd(original, prepared, sliced, recipes_file, mappings_file, out):
    chain = [(role, path) for role, path in (("original", original), ("prepared", prepared), ("sliced", sliced))
             if path]
    if not chain:
        _error("no_files", "Give at least one of --original, --prepared, --sliced.")
    recipes = _read_json(recipes_file, MAX_SIDE_BYTES, "recipes") if recipes_file else None
    mappings = _read_json(mappings_file, MAX_SIDE_BYTES, "mappings") if mappings_file else None
    built = build_passport([{"path": p, "role": r, "producer": {"tool": "user"}} for r, p in chain],
                           recipes=recipes, material_mappings=mappings)
    if built.passport is None:
        _emit({"ok": False, "error": {"code": built.diagnostics[0].code, "message": "The passport could not be built."},
               "diagnostics": [d.to_dict() for d in built.diagnostics]}, 1)
    document = built.passport.to_dict()
    written = None
    if out:
        # The raw text is checked as well as its absolute form: on POSIX abspath would turn a backslash UNC
        # string into a harmless-looking relative name, so the guard must see what the user typed.
        if localpath._reaches_network(out):
            _error("bad_output", "Studio writes local files only.")
        if out.endswith(("/", os.sep)) or os.path.isdir(out):
            _error("bad_output", "The output must be a file name, not a folder.")
        target = os.path.abspath(out)
        if any(os.path.normcase(target) == os.path.normcase(os.path.abspath(p)) for _r, p in chain):
            _error("output_is_input", "The output path is one of the input files.")
        if os.path.exists(target):
            _error("output_exists", "The output file already exists.")
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target) or ".", suffix=".tmp")
        except OSError:
            _error("write_failed", "The passport could not be written.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
            try:
                os.link(tmp, target)                        # fails if the destination appeared meanwhile
            except FileExistsError:
                raise
            except OSError:
                if os.name != "nt":
                    raise                                   # POSIX rename would replace; refuse rather than risk it
                os.rename(tmp, target)                      # Windows rename is atomic and refuses an existing file
        except FileExistsError:
            _error("output_exists", "The output file already exists.")
        except OSError:
            _error("write_failed", "The passport could not be written.")
        finally:
            try:
                os.remove(tmp)                              # the passport is already published or refused
            except OSError:
                pass
        written = os.path.basename(target)
    _emit({"ok": True, "passport_id": document["passport_id"], "written": written, "passport": document,
           "diagnostics": [d.to_dict() for d in built.diagnostics], "losses": document["losses"]}, 0)


def _load_passport(path: str) -> Any:
    return _read_json(path, MAX_PASSPORT_BYTES, "passport")


@passport.command("import")
@click.argument("file", type=_FILE)
@click.option("--base-dir", type=_DIR, default=None)
@click.option("--path", "paths", multiple=True, help="NAME=PATH of a local copy of an artifact")
@_handled
def import_cmd(file, base_dir, paths):
    result = import_passport(_load_passport(file), base_dir=base_dir, paths=_locations(paths))
    ok = result["passport"] is not None
    _emit({"ok": ok, **result}, 0 if ok else 1)


@passport.command("verify")
@click.argument("file", type=_FILE)
@click.option("--base-dir", type=_DIR, default=None)
@click.option("--path", "paths", multiple=True, help="NAME=PATH of a local copy of an artifact")
@_handled
def verify_cmd(file, base_dir, paths):
    decoded = decode_passport(_load_passport(file))
    if decoded.value is None:
        _emit({"ok": False, "error": {"code": "unusable_passport", "message": "The passport could not be read."},
               "diagnostics": [d.to_dict() for d in decoded.diagnostics]}, 1)
    report = verify_passport(decoded.value, base_dir=base_dir, paths=_locations(paths))
    ok = report["summary"]["all_intact"]
    _emit({"ok": ok, "verification": report, "diagnostics": [d.to_dict() for d in decoded.diagnostics]},
          0 if ok else 1)
