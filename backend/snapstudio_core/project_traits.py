"""Project traits — what a model file actually *is*, read straight from the file.

This is the fact-gathering half of Studio's ecosystem intelligence. It opens a
3MF (or looks at an STL) read-only and answers the questions the rest of the app
needs in order to give advice that is specific to *this* project:

  where did it come from, what printer was it authored for, how many plates and
  objects and colours does it carry, has it already been sliced, does it use
  painted colour or a texture, does it need slicer features Studio has never
  heard of, and what did its author's own slicer predict it would cost?

Two design rules make this trustworthy:

1. **Every trait carries its evidence.** A trait is not just ``True``; it comes
   with the part name or value that proved it and a confidence tier
   (``confirmed`` / ``likely`` / ``informational`` / ``unknown``). A Doctor that
   invents certainty is worse than no Doctor.

2. **It never raises.** A malformed, truncated or hostile file yields traits with
   ``unknown`` confidence, not an exception — the caller is a UI.

The 3MF layout knowledge here comes from the published 3MF core specification and
from the documented, publicly observable file layouts that PrusaSlicer and the
BambuStudio/OrcaSlicer family write. It is an independent implementation of a
container format, not a port of any slicer's code.
"""
from __future__ import annotations

import json
import os
import re

from .container import ThreeMF
from .errors import UnsafeArchive

SCHEMA_VERSION = "traits/1"

# Confidence tiers, most to least certain. Anything Studio cannot prove from the
# bytes in front of it must not claim the top tier.
CONFIRMED = "confirmed"
LIKELY = "likely"
INFORMATIONAL = "informational"
UNKNOWN = "unknown"

MODEL_PART = "3D/3dmodel.model"
BAMBU_SETTINGS = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
SLICE_INFO = "Metadata/slice_info.config"
PRUSA_SETTINGS = "Metadata/Slic3r_PE.config"
CUSTOM_GCODE = "Metadata/custom_gcode_per_layer.xml"

# Only the head of the model part is inspected: the <model> attributes and the
# document metadata sit before <resources>, and the mesh after it can be hundreds
# of megabytes. Reading a bounded prefix keeps this fast on huge projects.
_MODEL_HEAD_BYTES = 96 * 1024

_PLATE_GCODE_RE = re.compile(r"^Metadata/plate_\d+\.gcode$")
_PLATE_PNG_RE = re.compile(r"^Metadata/plate_\d+\.png$")
_MODEL_TAG_RE = re.compile(r"<model\b[^>]*>", re.S)
# Attributes are matched with either quote style: the 3MF spec permits both, and
# tolerating a single-quoted file costs nothing while refusing one loses real data.
_ATTR_RE = re.compile(r"""([A-Za-z_:][\w.:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_METADATA_RE = re.compile(
    r"""<metadata\b[^>]*\bname=(?:"([^"]+)"|'([^']+)')[^>]*>([^<]*)</metadata>""")
_KEY_VALUE_RE = re.compile(
    r"""<metadata\b[^>]*\bkey=(?:"([^"]+)"|'([^']+)')[^>]*\bvalue=(?:"([^"]*)"|'([^']*)')""")


def _attrs(fragment: str) -> dict:
    """Attribute map for one tag, quote-style agnostic."""
    return {name: (dq if dq else sq) for name, dq, sq in _ATTR_RE.findall(fragment)}

# 3MF extension namespaces Studio understands well enough not to warn about.
_KNOWN_EXTENSIONS = {
    "http://schemas.microsoft.com/3dmanufacturing/core/2015/02",
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06",
    "http://schemas.microsoft.com/3dmanufacturing/material/2015/02",
}

# Trait keys every result carries, so callers can rely on the shape even when a
# file is unreadable.
TRAIT_KEYS = (
    "format", "origin_family", "origin_application", "target_printer",
    "is_u1_project", "foreign_printer", "is_sliced", "plate_count",
    "object_count", "filament_count", "has_painted_color", "has_texture",
    "has_custom_per_layer_gcode", "has_support_enforcers", "unit", "non_mm_unit",
    "nozzle_diameters", "nozzle_diameters_by_toolhead", "mixed_nozzle_sizes", "required_extensions",
    "unknown_required_extensions", "likely_makerworld", "expects_object_exclusion",
)


def _tier(value, confidence: str, evidence: str | None = None) -> dict:
    return {"value": value, "confidence": confidence, "evidence": evidence}


def _model_head(tm: ThreeMF) -> tuple[dict, dict]:
    """Return (<model> attributes, document metadata) from the model part head."""
    if not tm.has_part(MODEL_PART):
        return {}, {}
    try:
        head = tm.read_part(MODEL_PART)[:_MODEL_HEAD_BYTES].decode("utf-8", "ignore")
    except Exception:
        return {}, {}
    tag = _MODEL_TAG_RE.search(head)
    attrs = _attrs(tag.group(0)) if tag else {}
    meta = {(dq or sq).strip(): text.strip()
            for dq, sq, text in _METADATA_RE.findall(head)}
    return attrs, meta


# The two names the same per-facet painting goes by. Studio reads both; see
# painted_color for what the data behind them means.
_PAINT_MARKERS = (b"paint_color", b"slic3rpe:mmu_segmentation")


def _painted_marker(tm: ThreeMF) -> tuple[bool, str | None]:
    """Whether any mesh in this project carries painted colour, and where."""
    for part in tm.list_parts():
        if not part.lower().endswith(".model"):
            continue
        try:
            blob = tm.read_part(part)
        except Exception:
            continue
        if any(marker in blob for marker in _PAINT_MARKERS):
            return True, part
    return False, None


def _json_settings(tm: ThreeMF, part: str) -> dict:
    try:
        out = json.loads(tm.read_part(part).decode("utf-8", "ignore"))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def _float_or_none(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _plate_predictions(tm: ThreeMF) -> list[dict]:
    """Per-plate time/weight the *author's own slicer* already computed.

    A sliced Bambu-family 3MF records what the slicer predicted for each plate.
    That is a real number produced by a real slicing run — better than any
    estimate Studio could invent without slicing — so Cost Doctor should prefer
    it and say where it came from.
    """
    if not tm.has_part(SLICE_INFO):
        return []
    try:
        raw = tm.read_part(SLICE_INFO).decode("utf-8", "ignore")
    except Exception:
        return []
    plates = []
    for block in re.findall(r"<plate\b.*?</plate>", raw, re.S):
        entry: dict = {"filaments": []}
        for kd, ks, vd, vs in _KEY_VALUE_RE.findall(block):
            entry[kd or ks] = vd if vd else vs
        for fm in re.finditer(r"<filament\b[^>]*/?>", block):
            f = _attrs(fm.group(0))
            entry["filaments"].append({
                "id": f.get("id"), "type": f.get("type"), "color": f.get("color"),
                "used_m": _float_or_none(f.get("used_m")),
                "used_g": _float_or_none(f.get("used_g")),
            })
        entry["predicted_seconds"] = _float_or_none(entry.get("prediction"))
        entry["predicted_weight_g"] = _float_or_none(entry.get("weight"))
        plates.append(entry)
    return plates


def _stl_traits() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "readable": True,
        "format": _tier("stl", CONFIRMED, "file extension"),
        "origin_family": _tier("none", CONFIRMED, "an STL carries no slicer data"),
        "origin_application": _tier(None, UNKNOWN, None),
        "target_printer": _tier(None, UNKNOWN, "an STL has no printer profile"),
        "is_u1_project": _tier(False, CONFIRMED, "an STL is not a slicer project"),
        "foreign_printer": _tier(False, CONFIRMED, "an STL targets no printer"),
        "is_sliced": _tier(False, CONFIRMED, "an STL contains no toolpaths"),
        "plate_count": _tier(1, INFORMATIONAL, "a bare mesh is treated as one plate"),
        "object_count": _tier(1, LIKELY, "one mesh per STL file"),
        "filament_count": _tier(0, CONFIRMED, "an STL assigns no filaments"),
        "has_painted_color": _tier(False, CONFIRMED, "an STL stores no colour"),
        "has_texture": _tier(False, CONFIRMED, "an STL stores no texture"),
        "has_custom_per_layer_gcode": _tier(False, CONFIRMED, None),
        "has_support_enforcers": _tier(False, CONFIRMED, None),
        "unit": _tier(None, UNKNOWN, "STL files do not record their unit"),
        "non_mm_unit": _tier(False, UNKNOWN, "STL files do not record their unit"),
        "nozzle_diameters": _tier([], UNKNOWN, None),
        "nozzle_diameters_by_toolhead": _tier([], UNKNOWN, None),
        "mixed_nozzle_sizes": _tier(False, UNKNOWN, None),
        "required_extensions": _tier([], CONFIRMED, None),
        "unknown_required_extensions": _tier(False, CONFIRMED, None),
        "likely_makerworld": _tier(False, CONFIRMED, None),
        "expects_object_exclusion": _tier(False, CONFIRMED,
                                          "an STL carries no slicer settings"),
        "plate_predictions": [],
        "notes": ["An STL is geometry only — colours, materials and print settings "
                  "are chosen later in the slicer."],
    }


def _unreadable(reason: str) -> dict:
    out = {
        "schema_version": SCHEMA_VERSION,
        "readable": False,
        "format": _tier("unknown", UNKNOWN, reason),
        "plate_predictions": [],
        "notes": [reason],
    }
    for k in TRAIT_KEYS:
        out.setdefault(k, _tier(None, UNKNOWN, reason))
    return out


def _detect_family(parts: set[str]) -> tuple[str, str, str]:
    if BAMBU_SETTINGS in parts:
        return "bambu-family", CONFIRMED, BAMBU_SETTINGS
    if PRUSA_SETTINGS in parts:
        return "prusa", CONFIRMED, PRUSA_SETTINGS
    if any(p.startswith("Cura") or p.startswith("Metadata/Cura") for p in parts):
        return "cura", CONFIRMED, "a Cura folder in the archive"
    return "generic", CONFIRMED, "no slicer project data in the archive"


def _prusa_printer_model(tm: ThreeMF) -> str | None:
    try:
        ini = tm.read_part(PRUSA_SETTINGS).decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r"^\s*(?:;\s*)?printer_model\s*=\s*(.+)$", ini, re.M)
    return m.group(1).strip() if m else None


_OBJECT_NAME_RE = re.compile(r'key="name"\s+value="([^"]+)"')


def _filament_slots(cfg: dict, prusa: dict) -> list[dict]:
    """One entry per filament slot the project defines, whatever wrote it."""
    if prusa.get("filaments"):
        return [{"tool": s["tool"], "type": s.get("type"), "color": s.get("color"),
                 "name": s.get("name")} for s in prusa["filaments"]]
    colours = _as_list(cfg.get("filament_colour")) if cfg else []
    types = _as_list(cfg.get("filament_type")) if cfg else []
    names = _as_list(cfg.get("filament_settings_id")) if cfg else []
    count = max(len(colours), len(types), len(names))
    out = []
    for index in range(count):
        colour = str(colours[index]).strip() if index < len(colours) else ""
        out.append({
            "tool": index,
            "type": str(types[index]).strip() if index < len(types) else None,
            "color": ("#" + colour.lstrip("#")[:6].upper()) if colour else None,
            "name": str(names[index]).strip() if index < len(names) else None,
        })
    return out


def _name_digest(model_settings_raw: str, prusa: dict) -> str | None:
    """A stable fingerprint of the project's object names — never the names.

    Two files that contain the same set of object names are very likely the same
    project, which makes this the strongest single piece of provenance evidence
    available. Carrying the names themselves would put the user's model names in
    every report and diagnostics bundle, so this carries sixteen hex characters
    instead.
    """
    from .gcode import _digest_of

    return _digest_of(_object_names(model_settings_raw, prusa))


def _object_names(model_settings_raw: str, prusa: dict) -> list[str]:
    """The project's object names, normalised the way a sliced job writes them.

    A project stores `Left bracket`; its slice labels the same object
    `Left_bracket.stl_id_0_copy_0`. Normalising both ends the same way is what
    makes a project recognisable in its own G-code — comparing them literally
    would report a mismatch between a project and its own slice, which is the
    worst answer provenance can give.
    """
    from .gcode import _clean_name

    names = []
    if model_settings_raw:
        names = _OBJECT_NAME_RE.findall(model_settings_raw)
    elif prusa.get("objects"):
        names = [o["name"] for o in prusa["objects"] if o.get("name")]
    return sorted({_clean_name(n) for n in names if n and str(n).strip()} - {""})


def _name_hashes(model_settings_raw: str, prusa: dict) -> list[str]:
    """One hash per object name — never a name.

    Lets a job that prints *some* of a project's objects — one plate of several,
    or a big file Studio could only read the ends of — be recognised as part of
    that project instead of mistaken for a different one.
    """
    from .gcode import _digest_of

    return [_digest_of([name]) for name in _object_names(model_settings_raw, prusa)]


def _prusa_summary(tm: ThreeMF, parts: set[str]) -> dict:
    """Everything the Prusa reader can establish, or an empty dict."""
    from . import prusa

    if prusa.SETTINGS_PART not in parts:
        return {}
    try:
        settings_raw = tm.read_part(prusa.SETTINGS_PART)
    except Exception:
        return {}
    model_raw = None
    if prusa.MODEL_CONFIG_PART in parts:
        try:
            model_raw = tm.read_part(prusa.MODEL_CONFIG_PART)
        except Exception:
            model_raw = None
    try:
        return prusa.summarise(settings_raw, model_raw)
    except Exception:
        return {}


def extract(path: str) -> dict:
    """Read a model file and return its traits. Never raises."""
    low = (path or "").lower()
    if low.endswith(".stl"):
        if not os.path.exists(path):
            return _unreadable("Studio could not find that file.")
        return _stl_traits()

    try:
        tm = ThreeMF.open(path)
    except UnsafeArchive as e:
        return _unreadable(str(e))
    except Exception:
        return _unreadable("Studio could not read this file as a 3MF project.")

    parts = set(tm.list_parts())
    attrs, meta = _model_head(tm)

    # --- origin -----------------------------------------------------------
    family, fam_conf, fam_ev = _detect_family(parts)
    app = meta.get("Application")
    cfg = _json_settings(tm, BAMBU_SETTINGS) if family == "bambu-family" else {}

    printer_model = _first(cfg.get("printer_model")) if cfg else None
    printer_ev = f"{BAMBU_SETTINGS} printer_model" if printer_model else None

    # A PrusaSlicer project carries the same information as a Bambu-family one,
    # in a different dialect. Reading it properly is what turns "detected" into
    # supported: without this every downstream check saw zero filaments and no
    # layer height, and had nothing to say about a perfectly ordinary project.
    prusa_summary: dict = {}
    if family == "prusa":
        prusa_summary = _prusa_summary(tm, parts)
        printer_model = prusa_summary.get("printer_model") or _prusa_printer_model(tm)
        printer_ev = f"{PRUSA_SETTINGS} printer_model" if printer_model else None
        if prusa_summary.get("application"):
            app = " ".join(x for x in (prusa_summary["application"],
                                       prusa_summary.get("application_version")) if x)

    is_u1 = bool(isinstance(printer_model, str) and printer_model.strip() == "Snapmaker U1")
    foreign = bool(printer_model) and not is_u1

    # --- plates, objects, filaments ---------------------------------------
    plate_gcode = sorted(p for p in parts if _PLATE_GCODE_RE.match(p))
    is_sliced = bool(plate_gcode)

    model_settings_raw = ""
    if MODEL_SETTINGS in parts:
        try:
            model_settings_raw = tm.read_part(MODEL_SETTINGS).decode("utf-8", "ignore")
        except Exception:
            model_settings_raw = ""

    plate_blocks = len(re.findall(r"<plate\b", model_settings_raw))
    plate_thumbs = len({p for p in parts if _PLATE_PNG_RE.match(p)})
    plate_count = plate_blocks or plate_thumbs or (1 if MODEL_PART in parts else 0)
    if plate_blocks:
        plate_conf, plate_ev = CONFIRMED, MODEL_SETTINGS
    elif plate_thumbs:
        plate_conf, plate_ev = LIKELY, "plate thumbnails in the archive"
    else:
        plate_conf, plate_ev = INFORMATIONAL, "no plate records; treated as a single plate"

    build_items = 0
    if MODEL_PART in parts:
        try:
            raw = tm.read_part(MODEL_PART)
            # <build> sits at the end of the model part, so search the tail.
            tail = raw[-_MODEL_HEAD_BYTES:].decode("utf-8", "ignore")
            build_items = len(re.findall(r"<item\b", tail))
        except Exception:
            build_items = 0
    ms_objects = len(re.findall(r"<object\b", model_settings_raw))
    object_count = ms_objects or prusa_summary.get("object_count") or build_items
    if ms_objects:
        obj_conf, obj_ev = CONFIRMED, MODEL_SETTINGS
    elif build_items:
        obj_conf, obj_ev = CONFIRMED, f"{build_items} build item(s) in {MODEL_PART}"
    else:
        obj_conf, obj_ev = UNKNOWN, None

    colours = _as_list(cfg.get("filament_colour")) if cfg else []
    ftypes = _as_list(cfg.get("filament_type")) if cfg else []
    filament_count = len(colours) or len(ftypes)
    fil_source = BAMBU_SETTINGS
    if not filament_count and prusa_summary.get("filament_count"):
        filament_count = prusa_summary["filament_count"]
        fil_source = PRUSA_SETTINGS
    if filament_count:
        fil_conf = CONFIRMED
        fil_ev = f"{filament_count} filament slot(s) in {fil_source}"
    elif family in ("generic", "none"):
        fil_conf, fil_ev = CONFIRMED, "no slicer settings in this file"
    else:
        fil_conf, fil_ev = UNKNOWN, None

    nozzles = [str(n).strip() for n in (_as_list(cfg.get("nozzle_diameter")) if cfg else [])
               if str(n).strip()]
    if not nozzles and prusa_summary.get("nozzle_diameters"):
        nozzles = [str(n).strip() for n in prusa_summary["nozzle_diameters"] if str(n).strip()]
    distinct_nozzles = sorted(set(nozzles))

    # --- colour / texture / advanced feature signals ----------------------
    # Painting lives on the mesh triangles, not in the settings file. Looking for
    # it in model_settings.config found it in no real project ever written, which
    # is why this reads the mesh parts themselves. Only the marker is looked for
    # here — decoding it is painted_color's job, and traits stay cheap.
    painted, painted_part = _painted_marker(tm)
    textured = any(p.startswith("3D/Textures/") for p in parts)
    enforcers = model_settings_raw.count("support_enforcer")

    unit = attrs.get("unit")
    req_prefixes = [p for p in re.split(r"\s+", attrs.get("requiredextensions", "").strip()) if p]
    # requiredextensions lists namespace *prefixes*; resolve each to its URI.
    declared = {k.split(":", 1)[1]: v for k, v in attrs.items() if k.startswith("xmlns:")}
    req_uris = [declared.get(p, p) for p in req_prefixes]
    unknown_ext = [u for u in req_uris if u not in _KNOWN_EXTENSIONS]

    # MakerWorld exports carry Bambu-family settings plus the auxiliary folder the
    # site's own packaging adds. Neither proves the origin on its own, so this
    # stays "likely" rather than claiming certainty.
    exclude_raw = _first(cfg.get("exclude_object")) if cfg else None
    exclude_object = str(exclude_raw).strip().lower() in {"1", "true", "yes", "on"}         if exclude_raw is not None else False

    aux = any(p.startswith("Auxiliaries/") for p in parts)
    makerworld = bool(family == "bambu-family" and aux and foreign)

    notes: list[str] = []
    if is_sliced:
        notes.append("This project already contains sliced toolpaths from its author's slicer.")
    if unknown_ext:
        notes.append("This project requires 3MF extensions Studio does not recognise; "
                     "some detail may not be visible to Studio.")

    return {
        "schema_version": SCHEMA_VERSION,
        "readable": True,
        "format": _tier("3mf", CONFIRMED, "OPC/ZIP container opened"),
        "origin_family": _tier(family, fam_conf, fam_ev),
        "origin_application": _tier(app, CONFIRMED if app else UNKNOWN,
                                    f"{MODEL_PART} metadata Application" if app else None),
        "target_printer": _tier(printer_model, CONFIRMED if printer_model else UNKNOWN,
                                printer_ev),
        "is_u1_project": _tier(is_u1, CONFIRMED if printer_model else UNKNOWN,
                               f"printer_model = {printer_model}" if printer_model else None),
        "foreign_printer": _tier(foreign, CONFIRMED if printer_model else UNKNOWN,
                                 f"printer_model = {printer_model}" if printer_model else None),
        "is_sliced": _tier(is_sliced, CONFIRMED,
                           f"{len(plate_gcode)} plate g-code part(s)" if is_sliced
                           else "no plate g-code parts in the archive"),
        "plate_count": _tier(plate_count, plate_conf, plate_ev),
        "object_count": _tier(object_count, obj_conf, obj_ev),
        "filament_count": _tier(filament_count, fil_conf, fil_ev),
        # Per-slot detail, so the material plan can work before slicing too and
        # provenance has something specific to compare against a sliced job.
        "filament_slots": _tier(_filament_slots(cfg, prusa_summary), fil_conf, fil_ev),
        # A digest, never the names. Object names are the user's model names; the
        # digest is enough to recognise the same set of objects in a sliced job.
        "object_name_digest": _tier(_name_digest(model_settings_raw, prusa_summary),
                                    CONFIRMED if model_settings_raw or prusa_summary else UNKNOWN,
                                    "object names in the project"),
        "object_name_hashes": _tier(_name_hashes(model_settings_raw, prusa_summary),
                                    CONFIRMED if model_settings_raw or prusa_summary else UNKNOWN,
                                    "one hash per object name, so a job that prints part of "
                                    "this project can be recognised as part of it"),
        "has_painted_color": _tier(painted, CONFIRMED,
                                   f"per-facet colour painting data in {painted_part}"
                                   if painted else None),
        "has_texture": _tier(textured, CONFIRMED,
                             "texture parts under 3D/Textures/" if textured else None),
        "has_custom_per_layer_gcode": _tier(CUSTOM_GCODE in parts, CONFIRMED,
                                            CUSTOM_GCODE if CUSTOM_GCODE in parts else None),
        "has_support_enforcers": _tier(bool(enforcers),
                                       CONFIRMED if model_settings_raw else UNKNOWN,
                                       f"{enforcers} support-enforcer reference(s)"
                                       if enforcers else None),
        "unit": _tier(unit, CONFIRMED if unit else UNKNOWN,
                      f"{MODEL_PART} unit attribute" if unit else None),
        "non_mm_unit": _tier(bool(unit and unit != "millimeter"),
                             CONFIRMED if unit else UNKNOWN,
                             f"unit = {unit}" if unit else None),
        "nozzle_diameters": _tier(distinct_nozzles, CONFIRMED if nozzles else UNKNOWN,
                                  f"{BAMBU_SETTINGS} nozzle_diameter" if nozzles else None),
        # One entry per toolhead, in the order the slicer wrote them — unlike
        # nozzle_diameters above, this is deliberately NOT deduplicated or
        # sorted, because preflight needs to compare toolhead 2's size against
        # toolhead 2's size, not just check whether the same sizes exist
        # somewhere in each set. A project with [0.4, 0.6, 0.4, 0.4] and a
        # printer reporting [0.4, 0.4, 0.6, 0.4] have identical sizes but on
        # different toolheads — a real mismatch nozzle_diameters' deduplicated
        # form cannot express.
        "nozzle_diameters_by_toolhead": _tier(nozzles, CONFIRMED if nozzles else UNKNOWN,
                                              f"{BAMBU_SETTINGS} nozzle_diameter" if nozzles else None),
        "mixed_nozzle_sizes": _tier(len(distinct_nozzles) > 1,
                                    CONFIRMED if nozzles else UNKNOWN,
                                    ", ".join(distinct_nozzles) if len(distinct_nozzles) > 1
                                    else None),
        "required_extensions": _tier(req_uris, CONFIRMED,
                                     ", ".join(req_uris) if req_uris else None),
        "unknown_required_extensions": _tier(bool(unknown_ext), CONFIRMED,
                                             ", ".join(unknown_ext) if unknown_ext else None),
        "likely_makerworld": _tier(makerworld, LIKELY if makerworld else INFORMATIONAL,
                                   "Bambu-family settings plus an Auxiliaries/ folder"
                                   if makerworld else None),
        # Whether the project relies on the printer being able to cancel one object
        # mid-print. Preflight only raises the firmware question when it does.
        "expects_object_exclusion": _tier(
            exclude_object, CONFIRMED if cfg else UNKNOWN,
            f"{BAMBU_SETTINGS} exclude_object" if cfg else None),
        "plate_predictions": _plate_predictions(tm),
        "notes": notes,
    }


def values(traits: dict) -> dict:
    """Flatten graded traits to plain values for rule matching."""
    return {k: v["value"] for k, v in traits.items()
            if isinstance(v, dict) and "value" in v and "confidence" in v}
