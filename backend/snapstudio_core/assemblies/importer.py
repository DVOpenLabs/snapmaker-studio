"""Bounded read-only assembly imports. Usage is reported by the slicer, never estimated."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from pathlib import Path
import tempfile
import zipfile
import zlib
import lzma

from lxml import etree

from snapstudio_core import gcode, localpath
from .model import AssemblyInputError, read_assembly

MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2048


def _member(archive, name):
    matches = [info for info in archive.infolist() if info.filename == name]
    if not matches:
        return None
    if len(matches) != 1 or matches[0].file_size > MAX_MEMBER_BYTES:
        raise AssemblyInputError("The project metadata is duplicated or too large to import.")
    with archive.open(matches[0]) as stream:
        raw = stream.read(MAX_MEMBER_BYTES + 1)
    if len(raw) > MAX_MEMBER_BYTES:
        raise AssemblyInputError("The project metadata is too large to import.")
    return raw


def _xml(raw):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in root.iter()):
        raise AssemblyInputError("XML declarations and entities are not accepted in slice summaries.")
    return root


def _tile(index, name, usage, source, sha, plate=None):
    return {"tile_id": f"import-{sha[:12]}-{index}", "name": name[:200], "plate": plate,
            "roles": {f"Filament {int(slot.split(':')[1]) + 1}": slot for slot in usage},
            "usage": usage, "usage_source": source, "scale": None,
            "attribution": {"source_sha256": sha, "usage_origin": source}}


def _gcode_comment_ends(raw):
    """The same bounded, complete-line comment windows used for positional data."""
    if len(raw) <= gcode.HEAD_BYTES + gcode.TAIL_BYTES:
        ends = raw
    else:
        head = raw[:gcode.HEAD_BYTES]
        tail = raw[-gcode.TAIL_BYTES:]
        # Partial boundary lines cannot establish a complete positional vector.
        head = head.rsplit(b'\n', 1)[0] if b'\n' in head else b''
        tail = tail.split(b'\n', 1)[1] if b'\n' in tail else b''
        ends = head + b'\n' + tail
    return ends.decode('utf-8', errors='replace')


def _declared_positions(raw):
    # Even the general reader compacts malformed mm/nozzle fields. Count their
    # positions independently, without using any of their numeric values.
    pattern = r'^\s*;\s*(?:filament used \[(?:mm|g)\]|filament_(?:type|colour|color|settings_id|vendor|diameter)|nozzle_diameter)\s*=([^\r\n]*)'
    count = 0
    for match in re.finditer(pattern, _gcode_comment_ends(raw), re.I | re.M):
        count = max(count, len(re.split(r'[,;]', match.group(1))))
        if count > 64:
            raise AssemblyInputError("A G-code declares more than 64 material slots.")
    return count


def _gram_vector(raw, available):
    """Keep every vector position, including unknowns; never use _floats' compaction."""
    if not available:
        return {}
    found = re.search(r'^\s*;\s*filament used \[g\]\s*=([^\r\n]*)', _gcode_comment_ends(raw), re.I|re.M)
    if found is None:
        return {}
    pieces = re.split(r'[,;]', found.group(1))
    if len(pieces) > 64:
        raise AssemblyInputError('A G-code gram vector has more than 64 entries.')
    usage = {}
    for i, piece in enumerate(pieces):
        try:
            value = float(piece.strip().strip('"'))
            if not math.isfinite(value) or not 0 <= value <= 1_000_000:
                value = None
        except (ValueError, OverflowError):
            value = None
        usage[f'slot:{i}'] = value
    return usage


def import_file(path: str) -> dict:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    if suffix not in (".3mf", ".gcode", ".g", ".gco", ".stl", ".obj"):
        raise AssemblyInputError("Choose a 3MF, G-code, STL or OBJ file.")
    if not localpath.is_local_regular_file(path, max_bytes=MAX_FILE_BYTES):
        raise AssemblyInputError("Choose an existing local file no larger than 128 MiB.")
    try:
        with candidate.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise AssemblyInputError("The selected file could not be read.") from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise AssemblyInputError("The selected file is empty or larger than 128 MiB.")
    sha = hashlib.sha256(raw).hexdigest()
    name = candidate.name
    notes = []
    if suffix in (".gcode", ".g", ".gco"):
        # Count complete bounded declaration positions before the general reader
        # can compact malformed values (or allocate a very large slot list).
        declared_count = _declared_positions(raw)
        # Parse exactly the bytes hashed above, not a path that may change mid-read.
        with tempfile.TemporaryDirectory(prefix="studio-assembly-import-") as directory:
            snapshot = Path(directory) / "input.gcode"
            snapshot.write_bytes(raw)
            try:
                facts = gcode.read_facts(snapshot)
            except (ValueError, OverflowError):
                facts = {'available': False}
        # Slot existence and gram positions are separate evidence. read_facts
        # can establish slots from types, millimetres or nozzle metadata even
        # when the gram vector is absent/short. Its compacted grams are NEVER
        # used: overlay only the position-preserving vector read above.
        declared = facts.get("slots") or []
        if not isinstance(declared, list) or len(declared) > 64:
            raise AssemblyInputError("A G-code declares more than 64 material slots.")
        usage = {f"slot:{i}": None for i in range(declared_count)}
        seen_tools = set()
        for entry in declared:
            tool = entry.get("tool") if isinstance(entry, dict) else None
            if type(tool) is not int or not 0 <= tool < 64 or tool in seen_tools:
                raise AssemblyInputError("A G-code has duplicate or invalid material slot IDs.")
            seen_tools.add(tool)
            usage[f"slot:{tool}"] = None
        usage.update(_gram_vector(raw, facts.get('available', False)))
        tiles = [_tile(1, name, usage or {"slot:0": None}, "gcode_facts", sha)]
        notes.append("Usage comes from bounded slicer comments, not a fresh slice.")
    elif suffix == ".3mf":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist()) > MAX_ARCHIVE_ENTRIES:
                    raise AssemblyInputError("The project contains too many archive entries.")
                config_raw = _member(archive, "Metadata/project_settings.config")
                config = json.loads(config_raw.decode("utf-8-sig")) if config_raw else {}
                colors = config.get("filament_colour", []) if isinstance(config, dict) else []
                if not isinstance(colors, list) or len(colors) > 64:
                    raise AssemblyInputError("The project has an unsupported filament list.")
                slice_raw = _member(archive, "Metadata/slice_info.config")
                plates = _xml(slice_raw).findall(".//plate") if slice_raw else []
                if len(plates) > 64:
                    raise AssemblyInputError("The project contains more than 64 plates.")
                tiles = []
                plate_ids = set()
                for index, plate in enumerate(plates, 1):
                    usage = {f"slot:{i}": None for i in range(len(colors))}
                    seen = set()
                    for filament in plate.findall("filament"):
                        try:
                            slot = int(filament.get("id", "")) - 1
                            if not 0 <= slot < 64 or slot in seen:
                                raise ValueError()
                            seen.add(slot)
                        except ValueError:
                            raise AssemblyInputError("A slice summary has duplicate or invalid filament IDs.") from None
                        value = filament.get("used_g")
                        try:
                            grams = float(value) if value is not None else None
                        except (ValueError, OverflowError):
                            grams = None
                        if grams is not None and (not math.isfinite(grams) or not 0 <= grams <= 1_000_000):
                            grams = None
                        usage[f"slot:{slot}"] = grams
                    identifiers = [entry.get("value") for entry in plate.findall("metadata") if entry.get("key") == "index"]
                    plate_id = identifiers[0] if len(identifiers) == 1 and identifiers[0] and len(identifiers[0]) <= 200 else str(index)
                    if plate_id in plate_ids:
                        raise AssemblyInputError('The slice summary repeats a plate identifier.')
                    plate_ids.add(plate_id)
                    tiles.append(_tile(index, f"{name} · plate {plate_id}", usage or {"slot:0": None}, "slice_info", sha, plate_id))
                if not tiles:
                    tiles = [_tile(1, name, {f"slot:{i}": None for i in range(max(1, len(colors)))}, "unsliced", sha)]
                    notes.append("No sliced usage was found. Remaining material need is unknown.")
        except AssemblyInputError:
            raise
        except (ValueError, RecursionError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, lzma.LZMAError, EOFError, etree.XMLSyntaxError):
            raise AssemblyInputError("The 3MF metadata could not be imported safely.") from None
    else:
        tiles = [_tile(1, name, {"slot:0": None}, "unsliced", sha)]
        notes.append("Model file added as a tile reference only. Geometry and material use were not measured; usage is unknown.")
    # Validate the same document contract used by evaluate/save. Internal provenance
    # remains alongside it; `usage` is the only arithmetic input.
    result = read_assembly({"name": name[:200], "tiles": tiles}).to_dict()
    return {"assembly": result, "file_name": name, "sha256": sha, "notes": notes,
            "evidence": "slicer-reported usage or unknown; original file unchanged"}
