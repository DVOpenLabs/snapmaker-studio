"""Self-check — run the real pipeline end to end and report what worked.

Written for someone evaluating Studio who does not want to install a desktop app
first. It exercises production code paths on a real 3MF: the same parser, the same
Doctors, the same prepare pipeline, the same fidelity audit. Nothing is stubbed
and nothing is compared against a stored constant — each check asserts a property
of the result, so a check can only pass if the feature genuinely worked.

The fixture is built at runtime rather than shipped, so this works from a frozen
install with no `examples/` directory. It is a real project archive: an object
placed at a larger printer's coordinates, authored for another machine, with two
extra colours introduced part-way up.

Everything is written to a temporary directory. The check verifies the input file
is byte-identical afterwards, which is the one property that would matter most if
it were ever wrong.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

SCHEMA_VERSION = "selfcheck/1"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

# A 10 mm cube. Small on purpose: the point of the fixture is where it sits, not
# how big it is.
_CUBE_VERTS = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
               (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
_CUBE_TRIS = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 5, 1), (0, 4, 5),
              (2, 6, 7), (2, 7, 3), (1, 5, 6), (1, 6, 2), (0, 3, 7), (0, 7, 4)]


# A 3MF is an Open Packaging Convention zip: the root relationships part is what points a
# reader at the model. Empty stubs here make Snapmaker Orca 2.4.1 refuse the file
# ("Loading of model file failed"), so the fixtures carry the real minimal parts.
CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>")
ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>")


def _model_xml(x: float, y: float) -> str:
    verts = "".join(f'<vertex x="{vx}" y="{vy}" z="{vz}"/>' for vx, vy, vz in _CUBE_VERTS)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in _CUBE_TRIS)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US"'
        ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<metadata name="Application">SelfCheckFixture-1</metadata>'
        f'<resources><object id="1" type="model"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        "</mesh></object></resources>"
        f'<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 {x} {y} 0"/></build>'
        "</model>"
    )


def build_fixture(directory: Path) -> Path:
    """A foreign project with a real problem in it: authored for a 350 mm bed and
    placed near that bed's right edge, so it lands off a U1 plate."""
    settings = {
        "printer_model": "Bambu Lab H2D",
        "printer_settings_id": "Bambu Lab H2D 0.4 nozzle",
        "printable_area": ["0x0", "350x0", "350x350", "0x350"],
        "printable_height": "325",
        "filament_colour": ["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#111111", "#EEEE00"],
        "filament_type": ["PLA"] * 6,
        "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
        "layer_height": "0.12",
        "initial_layer_print_height": "0.2",
        "exclude_object": "0",
        "brim_type": "auto_brim",
    }
    model_settings = (
        "<config>"
        '<object id="1"><metadata key="extruder" value="1"/></object>'
        '<object id="2"><metadata key="extruder" value="2"/></object>'
        '<object id="3"><metadata key="extruder" value="3"/></object>'
        '<object id="4"><metadata key="extruder" value="4"/></object>'
        '<plate><metadata key="plater_id" value="1"/></plate>'
        "</config>"
    )
    custom_gcode = (
        "<custom_gcodes_per_layer><plate>"
        '<layer top_z="8.2" type="2" extruder="5" color="#111111"/>'
        '<layer top_z="19.4" type="2" extruder="6" color="#EEEE00"/>'
        "</plate></custom_gcodes_per_layer>"
    )
    path = directory / "selfcheck_sample.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        z.writestr("_rels/.rels", ROOT_RELS_XML)
        z.writestr("3D/3dmodel.model", _model_xml(305.0, 175.0))
        z.writestr("Metadata/project_settings.config", json.dumps(settings, indent=2))
        z.writestr("Metadata/model_settings.config", model_settings)
        z.writestr("Metadata/custom_gcode_per_layer.xml", custom_gcode)
        z.writestr("Metadata/plate_1.gcode", "; toolpaths from the original printer\nG1 X0\n")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _Runner:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def check(self, name: str, fn) -> object:
        """Run one check. A raised exception is a failure with its reason, never a
        crash — the whole point is to produce a report even when something breaks."""
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - the report is the error channel
            self.checks.append({"name": name, "status": FAIL,
                                "detail": f"{type(exc).__name__}: {exc}"})
            return None
        if detail is False:
            self.checks.append({"name": name, "status": FAIL, "detail": "check returned false"})
            return None
        self.checks.append({"name": name, "status": PASS,
                            "detail": detail if isinstance(detail, str) else ""})
        return detail


def run(sample: str | None = None) -> dict:
    """Execute the pipeline and return a structured report. Never raises."""
    from . import (color_plan, ecosystem, fidelity, geometry, plate_placement,
                   project_cost, project_traits)
    from .container import ThreeMF
    from .convert import convert_to_u1
    from .errors import UnsafeArchive

    runner = _Runner()
    workdir = Path(tempfile.mkdtemp(prefix="snapstudio-selfcheck-"))
    fixture_source = "generated"
    try:
        if sample:
            source = workdir / Path(sample).name
            shutil.copy2(sample, source)
            fixture_source = str(Path(sample).name)
        else:
            source = build_fixture(workdir)
        before_hash = _sha(source)

        def parse():
            tm = ThreeMF.open(source)
            assert "3D/3dmodel.model" in tm.list_parts()
            return f"{len(tm.list_parts())} parts read"

        runner.check("Project parsing", parse)

        def geom():
            items = geometry.build_item_dims(str(source))
            assert items, "no placed objects found"
            return f"{len(items)} placed object(s) measured"

        runner.check("Geometry analysis", geom)

        def traits():
            t = project_traits.extract(str(source))
            assert t["readable"] is True
            graded = [k for k in project_traits.TRAIT_KEYS
                      if isinstance(t.get(k), dict) and t[k].get("confidence")]
            assert len(graded) == len(project_traits.TRAIT_KEYS)
            return f"{len(graded)} traits, each with a confidence tier"

        runner.check("Project traits", traits)

        placement = runner.check(
            "Placement diagnosis",
            lambda: _placement_detects(plate_placement, source))

        prepared = runner.check("Safe prepared copy",
                                lambda: _prepare(convert_to_u1, source, workdir))

        runner.check("Orca import compatibility",
                     lambda: _compat_applied(prepared))

        runner.check("Fidelity audit", lambda: _fidelity(fidelity, source, prepared))

        runner.check("Painted colour read",
                     lambda: _painted(workdir))
        runner.check("Painted colour survives preparing a copy",
                     lambda: _painted_survives(convert_to_u1, fidelity, workdir))

        moved = runner.check("Placement fix",
                             lambda: _placement_fix(plate_placement, source, workdir))

        runner.check("Cost evidence", lambda: _cost(project_cost, source))

        runner.check("Colour planning", lambda: _colors(color_plan, source))

        runner.check("Ecosystem recommendation", lambda: _ecosystem(ecosystem, source))

        runner.check("Preflight without a printer", lambda: _preflight(source))

        runner.check("Untrusted archive limits",
                     lambda: _archive_limits(ThreeMF, UnsafeArchive, workdir))

        runner.check("Original unchanged",
                     lambda: _unchanged(source, before_hash))

        runner.check("Sliced job read", lambda: _gcode_read(workdir))
        runner.check("Post-slice check", lambda: _post_slice(workdir))
        runner.check("Cost from a sliced job", lambda: _sliced_cost(workdir))
        runner.check("Print plan timeline", lambda: _print_plan(workdir))
        runner.check("What to load", lambda: _material_plan(workdir))
        runner.check("Ready to send", lambda: _send_check(workdir))
        runner.check("Sliced job recognised", lambda: _round_trip(workdir))
        runner.check("Material providers", lambda: _providers())
        runner.check("Nothing moved since the check",
                     lambda: _send_state(workdir))
        runner.check("What happened to an upload", _upload_outcomes)
        runner.check("API schema", _api_schema)

        passed = sum(1 for c in runner.checks if c["status"] == PASS)
        total = len(runner.checks)
        return {
            "schema_version": SCHEMA_VERSION,
            "sample": fixture_source,
            "checks": runner.checks,
            "passed": passed,
            "total": total,
            "ok": passed == total,
            "summary": f"{passed}/{total} checks passed",
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --- individual checks ------------------------------------------------------

def _placement_detects(plate_placement, source: Path) -> str:
    report = plate_placement.assess(str(source))
    assert report["available"], report.get("reason")
    assert report["off_plate"], "the off-plate object was not detected"
    edge = report["off_plate"][0]["edges"]
    return f"{len(report['off_plate'])} object(s) off the plate, past the {edge} edge"


def _prepare(convert_to_u1, source: Path, workdir: Path):
    result = convert_to_u1(str(source), out_dir=str(workdir / "prepared"))
    assert result.output_path, "no prepared file was written"
    assert Path(result.output_path).exists()
    assert Path(result.output_path).resolve() != Path(source).resolve()
    return result


def _compat_applied(prepared) -> str:
    assert prepared is not None, "prepare did not run"
    with zipfile.ZipFile(prepared.output_path) as z:
        names = z.namelist()
        cfg = json.loads(z.read("Metadata/project_settings.config"))
    assert cfg.get("exclude_object") == "1", "object exclusion was not enabled"
    assert cfg.get("brim_type") == "no_brim", "the automatic brim was not suppressed"
    assert not any(n.endswith(".gcode") for n in names), "stale toolpaths survived"
    assert cfg.get("print_settings_id", "").startswith("0.12"), \
        "the preset label does not describe the project's layer height"
    return "exclusion on, auto-brim off, stale toolpaths removed, preset label matches"


def _fidelity(fidelity, source: Path, prepared) -> str:
    assert prepared is not None, "prepare did not run"
    report = fidelity.audit(str(source), prepared.output_path)
    assert report["available"], report.get("reason")
    assert not report["unverified"], f"unaccounted elements: {report['unverified']}"
    assert report["claims"]["fully_accounted"] is True
    kept = len(report["kept"])
    return f"{kept} element(s) accounted for, none unverified"


def _placement_fix(plate_placement, source: Path, workdir: Path) -> str:
    result = plate_placement.prepare_placed_copy(str(source), out_dir=str(workdir / "placed"))
    assert result["ok"], result.get("reason")
    assert not result["after"]["off_plate"], "objects are still off the plate"
    return f"{result['objects_moved']} object(s) moved, re-checked clean"


def _cost(project_cost, source: Path) -> str:
    """The fixture carries stale toolpaths but no material figures, so the correct
    behaviour is a refusal that says which of the two situations it is — the fix
    differs. A number here would be the bug."""
    report = project_cost.estimate(str(source))
    assert report["available"] is False, "a cost was invented for a project with no figures"
    reason = report["reason"]
    assert ("not been sliced" in reason) or ("does not record how much" in reason), reason
    assert report["basis"] == project_cost.BASIS_NONE

    # And the other half: a project that *does* carry figures must be costed from
    # them rather than refused.
    priced = project_cost.from_traits({
        "is_sliced": {"value": True, "confidence": "confirmed", "evidence": "selfcheck"},
        "plate_predictions": [{
            "index": "1", "predicted_seconds": 3600.0, "predicted_weight_g": 100.0,
            "filaments": [{"id": "1", "type": "PLA", "used_g": 100.0, "used_m": 33.5}],
        }],
    }, price_per_kg=20.0)
    assert priced["available"] is True and priced["cost"] == 2.0, priced
    return "no figures: refused with a reason; real figures: costed from them"


def _colors(color_plan, source: Path) -> str:
    report = color_plan.analyse(str(source), toolheads=4)
    assert report["available"], report.get("reason")
    assert report["color_count"] == 6
    assert len(report["simultaneous"]) == 4
    assert len(report["layer_based"]) == 2
    assert report["verdict"] == color_plan.POSSIBLE_WITH_SWAPS
    heights = ", ".join(f"{c['from_z_mm']:g} mm" for c in report["layer_based"])
    return f"6 colours on 4 toolheads; 2 arrive at {heights}"


def _ecosystem(ecosystem, source: Path) -> str:
    advice = ecosystem.advise(str(source))
    assert advice["primary"], "no tool was recommended"
    assert advice["primary"]["why"], "the recommendation carried no reason"
    assert advice["primary"]["installed"] is False, \
        "a tool was claimed installed without a path being found"
    return f"{advice['primary']['name']} — {advice['primary']['why'][0][:60]}…"


def _preflight(source: Path) -> str:
    from snapstudio_api import service

    report = service.preflight(str(source), host=None)
    assert report["printer_reachable"] is False
    assert report["unknowns"], "no printer, yet nothing was reported as unknown"
    for check in report["unknowns"]:
        blob = f"{check['title']} {check['consequence']}".lower()
        assert "not supported" not in blob, "an undetected capability was called unsupported"
    return f"{len(report['unknowns'])} check(s) correctly reported as unknown"


def _archive_limits(ThreeMF, UnsafeArchive, workdir: Path) -> str:
    from . import container

    bomb = workdir / "bomb.3mf"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.bin", b"\0" * (64 * 1024 * 1024))
    original = container.MAX_TOTAL_UNCOMPRESSED
    container.MAX_TOTAL_UNCOMPRESSED = 4 * 1024 * 1024
    try:
        try:
            ThreeMF.open(bomb)
        except UnsafeArchive:
            return "a highly compressible archive was refused, not buffered"
        raise AssertionError("an oversized archive was accepted")
    finally:
        container.MAX_TOTAL_UNCOMPRESSED = original


def _unchanged(source: Path, before_hash: str) -> str:
    assert _sha(source) == before_hash, "the input file was modified"
    return "input file is byte-identical after every operation"


def _api_schema() -> str:
    """Start the real loopback service and call the documented routes."""
    import http.client
    import threading

    from snapstudio_api.server import build_server

    # Binding an ephemeral port can fail on a machine that has run out of them —
    # this one had 14,000 sockets open when it first happened. That is a fact
    # about the machine, not about Studio, so it is worth a couple of retries and
    # a sentence that says so rather than an OSError the reader has to decode.
    httpd = token = None
    for attempt in range(3):
        try:
            httpd, token = build_server(port=0)
            break
        except OSError as exc:
            if attempt == 2:
                raise AssertionError(
                    "this machine would not give Studio a port to listen on "
                    f"({exc}). Nothing is wrong with the engine; close some "
                    "network-heavy applications and run the check again.") from exc
            time.sleep(0.5)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        routes = {
            "/project_traits": ({"path": "none"}, ["schema_version", "readable"]),
            "/ecosystem_advice": ({"path": "none"}, ["primary", "summary", "traits"]),
            "/project_cost": ({"path": "none"}, ["available", "basis"]),
            "/placement_check": ({"path": "none"}, ["available", "items"]),
            "/color_plan": ({"path": "none"}, ["verdict", "headline"]),
            "/fidelity": ({"original": "none", "prepared": "none"}, ["rows", "claims"]),
            "/fix_history": ({}, ["entries"]),
            "/gcode_facts": ({"path": "none"}, ["schema_version", "available"]),
            "/post_slice": ({"path": "none"}, ["schema_version", "available", "summary"]),
            "/sliced_cost": ({"path": "none"}, ["schema_version", "available", "summary"]),
            "/print_plan": ({"path": "none"}, ["schema_version", "available"]),
            "/material_plan": ({"path": "none"}, ["schema_version", "available"]),
            "/send_check": ({"path": "none"}, ["schema_version", "available", "verdict"]),
            "/watch_folder": ({"folder": "none"}, ["schema_version", "available"]),
            "/slice_provenance": ({"project_path": "none", "gcode_path": "none"},
                                  ["schema_version", "verdict"]),
        }
        # One connection for all of them, kept open. A fresh socket per route
        # left fifteen in TIME_WAIT every run, and on a machine that has been
        # busy that is how a self-check fails for a reason that has nothing to do
        # with Studio: "only one usage of each socket address is normally
        # permitted", which reads like a bug in the thing being checked.
        # Connecting needs a source port, and a machine whose dynamic range is
        # exhausted has none to give — one machine here had 14,000 connections
        # held open by Docker Desktop. That is a fact about the machine, so it is
        # worth waiting through rather than reporting as a fault in Studio.
        connection = None
        for attempt in range(4):
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                connection.connect()
                break
            except OSError as exc:
                if attempt == 3:
                    raise AssertionError(
                        "this machine would not give Studio a port to connect from "
                        f"({exc}). Something is holding a very large number of network "
                        "connections open; nothing is wrong with the engine.") from exc
                time.sleep(1.0)
        try:
            for route, (payload, required) in routes.items():
                connection.request(
                    "POST", route, body=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", "X-Auth-Token": token})
                response = connection.getresponse()
                body = json.loads(response.read())
                missing = [field for field in required if field not in body]
                assert not missing, f"{route} is missing {missing}"
        finally:
            connection.close()
        return f"{len(routes)} documented routes answered with their fields"
    finally:
        httpd.shutdown()
        httpd.server_close()


def format_table(report: dict) -> str:
    """The human-readable form. Deliberately plain so it pastes into an issue."""
    lines = ["Snapmaker Studio self-check", ""]
    width = max((len(c["name"]) for c in report["checks"]), default=20) + 4
    for check in report["checks"]:
        lines.append(f"{check['name'].ljust(width)}{check['status']}")
        if check["detail"]:
            lines.append(f"{'':{width}}  {check['detail']}")
    lines.append("")
    lines.append(report["summary"])
    return "\n".join(lines)


# --- the post-slice half of the loop ----------------------------------------

_SAMPLE_GCODE = """; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 12
; max_z_height: 2.40
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
SET_PRINT_STATS_INFO TOTAL_LAYER=12 CURRENT_LAYER=0
G1 X10 Y10 Z0.2 F1200
T1
G1 X20 Y20 E1.0
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [mm] = 0.00, 120.00, 0.00, 0.00
; filament used [g] = 0.00, 0.36, 0.00, 0.00
; total filament used [g] = 0.36
; total layers count = 12
; estimated printing time (normal mode) = 4m 10s

; CONFIG_BLOCK_START
; filament_type = PLA;PLA;PLA;PLA
; layer_height = 0.2
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
"""


def _write_sample_gcode(workdir: Path) -> Path:
    target = workdir / "selfcheck_job.gcode"
    target.write_text(_SAMPLE_GCODE, encoding="utf-8")
    return target


def _gcode_read(workdir: Path) -> str:
    from . import gcode
    facts = gcode.read_facts(_write_sample_gcode(workdir))
    if not facts.get("available"):
        raise AssertionError(facts.get("error", "the reader refused a valid job"))
    if facts.get("printer_model") != "Snapmaker U1" or facts.get("layer_count") != 12:
        raise AssertionError("the reader did not recover the job's own facts")
    if facts.get("tools_used") != [1]:
        raise AssertionError("tool use was not read from per-slot filament")
    return "slicer, machine, layers, time and per-slot filament read from a sliced job"


def _post_slice(workdir: Path) -> str:
    """The join, and the refusal. With no printer, printer-dependent checks must
    be unknown — never a failure."""
    from . import gcode, post_slice
    facts = gcode.read_facts(_write_sample_gcode(workdir))

    offline = post_slice.analyse(facts, {"reachable": False})
    results = {c["id"]: c["result"] for c in offline["checks"]}
    if post_slice.BLOCKED in results.values() or post_slice.ATTENTION in results.values():
        raise AssertionError("an unreachable printer produced a failure instead of an unknown")

    empty_slot = post_slice.analyse(facts, {
        "reachable": True, "toolhead_count": 4,
        "bed_mm": {"x": 271, "y": 335},
        "loaded_filaments": [{"material": "PLA"}, None, None, None],
    })
    loaded = next(c for c in empty_slot["checks"] if c["id"] == "gcode.loaded")
    if loaded["result"] != post_slice.ATTENTION or "slot 2" not in (loaded["action"] or ""):
        raise AssertionError("an empty slot the job needs was not reported")
    return "job joined to a printer; empty slot caught, unreachable printer stays unknown"


def _sliced_cost(workdir: Path) -> str:
    from . import gcode, sliced_cost
    facts = gcode.read_facts(_write_sample_gcode(workdir))
    cost = sliced_cost.estimate(facts, price_per_kg=20.0)
    if not cost.get("available") or cost.get("total_grams") != 0.36:
        raise AssertionError("cost did not use the slicer's measured filament")
    if cost["waste"]["separable"]:
        raise AssertionError("cost claimed a purge split the file does not provide")
    return f"costed from measured grams and time: {cost['summary']}"


_MULTI_GCODE = """; HEADER_BLOCK_START
; generated by Snapmaker Orca 2.3.4 on 2026-08-23 at 10:00:00
; total layer number: 4
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
PRINT_START
M140 S60
M104 T0 S220
T0
;LAYER_CHANGE
;Z:0.2
G1 X10 Y10 E1
T1
;LAYER_CHANGE
;Z:0.4
G1 X10 Y10 E1
M600
;LAYER_CHANGE
;Z:0.6
T0
;LAYER_CHANGE
;Z:0.8
PRINT_END
; EXECUTABLE_BLOCK_END

; filament used [g] = 2.00, 1.50, 0.00, 0.00
; total filament used [g] = 3.50
; total layers count = 4
; estimated printing time (normal mode) = 22m 5s

; CONFIG_BLOCK_START
; filament_type = PLA;PETG;PLA;PLA
; filament_colour = #FF0000;#00FF00;#0000FF;#FFFFFF
; nozzle_diameter = 0.4,0.4,0.4,0.4
; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271
; printer_model = Snapmaker U1
; CONFIG_BLOCK_END
"""


def _write_multi_gcode(workdir: Path) -> Path:
    target = workdir / "selfcheck_multi.gcode"
    target.write_text(_MULTI_GCODE, encoding="utf-8")
    return target


def _print_plan(workdir: Path) -> str:
    from . import gcode, print_plan
    job = _write_multi_gcode(workdir)
    plan = print_plan.scan(job)
    if not plan.get("available"):
        raise AssertionError(plan.get("error", "the timeline could not be built"))
    if plan["tools_seen"] != [0, 1] or plan["tool_changes"] != 3 or plan["pauses"] != 1:
        raise AssertionError(f"the timeline misread the job: {print_plan.summary(plan)}")
    lines = print_plan.narrate(plan, gcode.read_facts(job))
    if not any("pauses and waits" in line["text"] for line in lines):
        raise AssertionError("a pause was found but never explained to the user")
    if not all(line.get("evidence") for line in lines):
        raise AssertionError("a timeline line was produced without its evidence")
    return f"{len(lines)} plain-language steps, each with its G-code evidence"


def _material_plan(workdir: Path) -> str:
    """The question a person at the printer actually asks, and the refusal when
    there is no printer to ask about."""
    from . import gcode, material_plan
    facts = gcode.read_facts(_write_multi_gcode(workdir))

    loaded = [{"color": "#FF0000", "material": "PLA Basic"}, None,
              {"color": "#0000FF", "material": "PLA"}, None]
    plan = material_plan.plan(facts["slots"], loaded, facts["tools_used"])
    if plan["to_change"] != [1]:
        raise AssertionError(f"the empty slot the job uses was not flagged: {plan['summary']}")
    if 2 not in [s["tool"] for s in plan["slots"] if s["state"] == "unused"]:
        raise AssertionError("a slot the job never uses was not left alone")

    blind = material_plan.plan(facts["slots"], None, facts["tools_used"])
    if blind["printer_known"] or blind["to_change"]:
        raise AssertionError("no printer produced a shopping list instead of an unknown")
    return "empty slot caught, unused slot left alone, no printer stays unknown"


def _send_check(workdir: Path) -> str:
    from . import gcode, print_plan, send_check
    job = _write_multi_gcode(workdir)
    facts = gcode.read_facts(job)
    timeline = print_plan.scan(job)

    printer = {"reachable": True, "toolhead_count": 4, "bed_mm": {"x": 271, "y": 335},
               "print_state": "standby", "klipper_objects": ["exclude_object"],
               "loaded_filaments": [{"color": "#FF0000", "material": "PLA"}, None, None, None]}
    report = send_check.evaluate(facts, printer, timeline=timeline)
    if report["verdict"] != send_check.BLOCKER:
        raise AssertionError("an empty slot the job prints from did not block the send")

    offline = send_check.evaluate(facts, {"reachable": False}, timeline=timeline)
    if offline["counts"]["blocker"]:
        raise AssertionError("an unreachable printer produced a blocker")
    text = (report["headline"] + report["disclaimer"]).lower()
    if any(p in text for p in ("will print", "guaranteed", "100%")):
        raise AssertionError("the send confirmation promised a successful print")
    return "empty slot blocks the send; no printer blocks nothing; no success promise"


def _round_trip(workdir: Path) -> str:
    """The step that used to be manual: notice the sliced job and know whose it is."""
    from . import gcode, provenance, watch_folder

    folder = workdir / "orca-output"
    folder.mkdir(exist_ok=True)
    job = folder / "selfcheck_round_trip.gcode"
    job.write_text(_MULTI_GCODE.replace(
        "PRINT_START",
        "PRINT_START" + chr(10)
        + "EXCLUDE_OBJECT_DEFINE NAME=Bracket_left CENTER=10,10" + chr(10)
        + "EXCLUDE_OBJECT_DEFINE NAME=Bracket_right CENTER=40,40"), encoding="utf-8")

    facts = gcode.read_facts(job)
    digest = (facts.get("exclude_object") or {}).get("name_digest")
    if not digest:
        raise AssertionError("the job's object names were not fingerprinted")

    traits = {
        "readable": True,
        "object_name_digest": {"value": digest},
        "filament_slots": {"value": [{"tool": 0, "type": "PLA", "color": "#FF0000"},
                                      {"tool": 1, "type": "PETG", "color": "#00FF00"}]},
        "filament_count": {"value": 2},
        "target_printer": {"value": "Snapmaker U1"},
    }
    match = provenance.compare(traits, facts)
    if match["verdict"] != provenance.CONFIRMED:
        raise AssertionError(f"a job from the same project was not recognised: {match['verdict']}")

    other = provenance.compare({**traits, "object_name_digest": {"value": "deadbeefdeadbeef"}}, facts)
    if other["verdict"] != provenance.NO_MATCH:
        raise AssertionError("a job from a different project was not ruled out")

    # A file written a moment ago is still being written as far as anything
    # outside the slicer can tell, and is deliberately not offered yet.
    fresh = watch_folder.scan(folder)
    if not fresh.get("available") or not fresh["candidates"]:
        raise AssertionError("the watcher found nothing in a folder containing a job")
    if fresh["candidates"][0]["complete"]:
        raise AssertionError("a job written a moment ago was offered as finished")

    import os as _os
    settled = time.time() - 60
    _os.utime(job, (settled, settled))
    found = watch_folder.scan(folder)
    if not found["candidates"][0]["complete"]:
        raise AssertionError("a finished job was reported as still being written")

    part_way = folder / "selfcheck_part_way.gcode"
    part_way.write_text(_MULTI_GCODE.split("; CONFIG_BLOCK_START")[0], encoding="utf-8")
    _os.utime(part_way, (settled, settled))
    cut_short = next(c for c in watch_folder.scan(folder)["candidates"]
                     if c["name"] == part_way.name)
    if cut_short["complete"]:
        raise AssertionError("a job cut off before its end was offered as finished")
    return ("job recognised by its objects, a different project ruled out, "
            "unfinished and cut-short files refused")


def _send_state(workdir: Path) -> str:
    """The gap between reading the checks and pressing send."""
    from . import gcode, send_state

    job = workdir / "selfcheck_send_state.gcode"
    job.write_text(_MULTI_GCODE, encoding="utf-8")
    facts = gcode.read_facts(job)
    loaded = [{"material": "PLA", "color": "#FF0000"}, {"material": "PETG", "color": "#00FF00"}]
    printer = {"reachable": True, "print_state": "ready", "toolhead_count": 4,
               "klipper_objects": ["extruder", "exclude_object"], "loaded_filaments": loaded}

    def stat_of(path):
        from snapstudio_api.service import _file_stat

        return _file_stat(str(path))

    before = send_state.fingerprint(facts, printer, file_stat=stat_of(job))
    unchanged = send_state.fingerprint(facts, printer, file_stat=stat_of(job))
    if send_state.changes(before, unchanged):
        raise AssertionError("an unchanged printer was reported as having changed")

    emptied = dict(printer, loaded_filaments=[None, loaded[1]])
    moved = send_state.changes(before, send_state.fingerprint(facts, emptied,
                                                              file_stat=stat_of(job)))
    if [item["part"] for item in moved] != ["materials"]:
        raise AssertionError("a slot emptied between check and send went unnoticed")

    # Re-slicing to the same filename is ordinary, and the file that comes back is
    # a different job with the same name.
    job.write_text(_MULTI_GCODE.replace("G1 X10 Y10 E1", "G1 X20 Y20 E2"), encoding="utf-8")
    again = send_state.fingerprint(gcode.read_facts(job), printer, file_stat=stat_of(job))
    if not any(item["part"] == "job" for item in send_state.changes(before, again)):
        raise AssertionError("the job being written again went unnoticed")
    return "an unchanged world passes; an emptied slot and a re-sliced file both stop the send"


def _upload_outcomes() -> str:
    """Four different situations that used to read as one failure."""
    from snapstudio_api.service import _upload_state

    expected = {
        "verified": {"present": True, "metadata_ready": True, "size_matches": True,
                     "fresh": True},
        "pending_verification": {"present": True, "metadata_ready": False,
                                 "size_matches": True, "fresh": True},
        "not_listed": {"present": False, "metadata_ready": False},
        "mismatch": {"present": True, "metadata_ready": True, "size_matches": False},
    }
    for state, confirmation in expected.items():
        got = _upload_state(confirmation)
        if got != state:
            raise AssertionError(f"an upload that was {state} was reported as {got}")
    stale = _upload_state({"present": True, "metadata_ready": True, "size_matches": True,
                           "fresh": False})
    if stale != "mismatch":
        raise AssertionError("the printer still describing the previous file was called fine")
    return "accepted, pending, not listed, mismatched and stale are told apart"


def _providers() -> str:
    """The seam: optional sources add what the printer cannot know, and never
    override what it can see."""
    from . import material_plan, material_providers as mp

    printer = {"source": mp.STOCK, "available": True, "remaining_known": False,
               "slots": [mp._slot(0, material="PLA", subtype="Matte", color="#000000")]}
    # A tracked figure now has to say when it was last true before it may stop a
    # send. A weight nothing has updated in a fortnight is bookkeeping, and
    # refusing a print over it teaches people to ignore the refusals that matter.
    import datetime as _dt
    recent = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)).isoformat()
    tracker = {"source": mp.SPOOLMAN, "available": True, "remaining_known": True,
               "slots": [mp._slot(0, material="PETG", color="#FFFFFF", spool_id=7,
                                  remaining_g=40.0, source=mp.SPOOLMAN,
                                  remaining_quality=mp.TRACKED,
                                  remaining_as_of=recent)]}
    combined = mp.combine(printer, tracker)
    slot = combined["slots"][0]
    if slot["material"] != "PLA" or slot["color"] != "#000000":
        raise AssertionError("a provider overrode what the printer itself reported")
    if slot["remaining_g"] != 40.0:
        raise AssertionError("the tracked remaining weight was not carried through")

    loaded = mp.as_loaded_filaments(combined)
    plan = material_plan.plan([{"tool": 0, "used": True, "grams": 87.0, "type": "PLA",
                                "color": "#000000"}], loaded, [0])
    if plan["slots"][0]["state"] != "not_enough":
        raise AssertionError("87 g needed against 40 g tracked was not reported as short")

    blind = material_plan.plan([{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}],
                               [{"material": "PLA"}], [0])
    if blind["slots"][0]["sufficiency"]["verdict"] != "unknown":
        raise AssertionError("a spool with no tracked weight was not reported as unknown")

    # The same shortfall, on a figure that will not say where it came from, is a
    # caution rather than a refusal.
    vague = material_plan.plan([{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}],
                               [{"material": "PLA", "remaining_g": 40.0}], [0])
    if vague["slots"][0]["state"] != "maybe_not_enough":
        raise AssertionError("an unlabelled remaining weight was treated as a fact")

    # And the same shortfall again on a tracked figure nobody has touched for a
    # fortnight. Stale bookkeeping warns; it never refuses.
    old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=14)).isoformat()
    stale = material_plan.plan(
        [{"tool": 0, "used": True, "grams": 87.0, "type": "PLA"}],
        [{"material": "PLA", "remaining_g": 40.0, "remaining_quality": mp.TRACKED,
          "remaining_as_of": old}], [0])
    if stale["slots"][0]["state"] != "maybe_not_enough":
        raise AssertionError("a stale tracked weight was treated as grounds for a refusal")

    # A provider mapping on a printer that reports no filament of its own is the
    # user's note, not the machine's observation, and must not read as one.
    assumed = mp.as_loaded_filaments(mp.combine(
        {"source": mp.SPOOLMAN, "available": True, "remaining_known": True,
         "slots": [mp._slot(0, material="PLA", source=mp.SPOOLMAN, spool_id=7,
                            confirmed_by=mp.BY_PROVIDER)]}))
    if assumed[0].get("confirmed_by") != mp.BY_PROVIDER:
        raise AssertionError("a provider mapping was presented as printer-confirmed")

    return ("printer stays authoritative; a fresh tracked weight can block; stale, "
            "derived and unlabelled weights only warn; untracked stays unknown; a "
            "provider mapping is never presented as an observation")


def _painted_fixture(workdir: Path) -> Path:
    """A project painted the way a slicer paints one: a low band in one filament,
    a high band in another, and a facet split between two more."""
    from . import paint_codec

    low, high = paint_codec.encode_leaf(2), paint_codec.encode_leaf(3)
    split = paint_codec.encode_tree((0, [4, 5]))
    vertices = "".join(
        f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in
        [(0, 0, 0), (10, 0, 0), (0, 10, 0),
         (0, 0, 30), (10, 0, 30), (0, 10, 30),
         (0, 0, 5), (10, 0, 5), (0, 10, 5)])
    triangles = (
        f'<triangle v1="0" v2="1" v3="2" paint_color="{low}"/>'
        f'<triangle v1="3" v2="4" v3="5" paint_color="{high}"/>'
        f'<triangle v1="6" v2="7" v3="8" paint_color="{split}"/>')
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<metadata name="BambuStudio:MmPaintingVersion">1</metadata>'
        '<resources><object id="1" type="model"><mesh>'
        f"<vertices>{vertices}</vertices><triangles>{triangles}</triangles>"
        "</mesh></object></resources>"
        '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build></model>')
    settings = {
        "printer_model": "Snapmaker U1",
        "filament_colour": ["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#111111"],
        "filament_type": ["PLA"] * 5,
        "nozzle_diameter": ["0.4"] * 4,
        "layer_height": "0.2",
        "initial_layer_print_height": "0.2",
    }
    path = workdir / "selfcheck_painted.3mf"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        z.writestr("_rels/.rels", ROOT_RELS_XML)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/project_settings.config", json.dumps(settings, indent=2))
        z.writestr("Metadata/model_settings.config",
                   '<config><object id="1"><part id="1" subtype="normal_part">'
                   '<metadata key="extruder" value="1"/></part></object>'
                   '<plate><metadata key="plater_id" value="1"/></plate></config>')
    return path


def _painted(workdir: Path) -> str:
    """Painted colour, decoded from the project rather than guessed at."""
    from . import color_plan, painted_color

    source = _painted_fixture(workdir)
    result = painted_color.read(str(source))
    assert result["available"], result.get("reason")
    assert result["slots_referenced"] == [2, 3, 4, 5], result["slots_referenced"]
    assert result["painted_triangle_count"] == 3
    assert not result["malformed_triangle_count"], "a facet failed to decode"

    together = painted_color.coexistence(result)
    verdicts = {tuple(pair["slots"]): pair["verdict"] for pair in together["pairs"]}
    assert verdicts[(2, 3)] == "separate", verdicts
    assert verdicts[(4, 5)] == "overlaps", verdicts

    plan = color_plan.analyse(str(source), toolheads=4)
    assert plan["painted"]["painted"] is True
    assert plan["painted"]["slots"] == [2, 3, 4, 5]
    slots = ", ".join(str(slot) for slot in result["slots_referenced"])
    return (f"4 painted slots read ({slots}); one pair proven separate in Z, "
            "one proven to overlap")


def _painted_survives(convert_to_u1, fidelity, workdir: Path) -> str:
    """Painting is exactly what a converter can destroy quietly, so preparing a
    copy is checked against the painting itself, not against the mesh."""
    source = _painted_fixture(workdir)
    result = convert_to_u1(str(source), out_dir=str(workdir / "painted-prepared"))
    assert result.output_path, "no prepared file was written"
    report = fidelity.audit(str(source), result.output_path)
    rows = [row for row in report["rows"] if row["element"] == "Painted colour"]
    assert rows, "the fidelity audit did not look at the painting"
    status = rows[0]["status"]
    assert status in (fidelity.PRESERVED_EXACT, fidelity.PRESERVED_SEMANTIC),         f"painting was {status}: {rows[0]['detail']}"
    return f"painting {status.replace('_', ' ')} in the prepared copy"
