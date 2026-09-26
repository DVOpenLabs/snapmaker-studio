"""Adapter functions — delegate to the pure engine, return JSON-ready dicts.

The adapter (not the pure engine) is where side effects live: wall-clock
timestamps and the on-disk library index. The engine stays pure and testable.
"""
from __future__ import annotations
import datetime
import os
import threading
import uuid
from snapstudio_core.doctor import diagnose_path
from snapstudio_core.convert import convert_to_u1
from snapstudio_core.diff import diff_projects
from snapstudio_core.container import ThreeMF
from snapstudio_core import library
from snapstudio_core import fix_ledger
from snapstudio_core.batch import run_batch
from snapstudio_core import compatibility
from snapstudio_core import model_search
from snapstudio_core import scale_doctor
from snapstudio_core import print_failure
from snapstudio_core import print_quality
from snapstudio_core import first_layer_doctor
from snapstudio_core.paths import data_dir as _resolve_data_dir

API_VERSION = "api/1"


# --- library index (local-first SQLite of what the user has opened) ----------

def _data_dir() -> str:
    return _resolve_data_dir()


def _db_path() -> str:
    return os.path.join(_data_dir(), "library.db")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conn():
    # One connection per request: ThreadingHTTPServer hands each request its own
    # thread, and SQLite connections must not be shared across threads.
    return library.connect(_db_path())


def _record_fix(operation: str, source: str, output: str, *, changes=None,
                findings=None, validated=None, notes=None) -> None:
    """Write one ledger entry for a file Studio just produced.

    Never raises: a bookkeeping failure must not fail the fix the user asked for.
    """
    try:
        fix_ledger.record(_data_dir(), fix_ledger.build_entry(
            operation=operation, source=source, output=output, timestamp=_now(),
            changes=changes, findings=findings, validated=validated,
            engine_version=API_VERSION, notes=notes))
    except Exception:
        pass


def fix_history(source: str | None = None, limit: int = 50) -> dict:
    """What Studio changed, newest first. With `source`, only for that project."""
    return {"schema_version": fix_ledger.SCHEMA_VERSION,
            "entries": fix_ledger.entries(_data_dir(), source=source, limit=limit)}


def fix_original(output: str) -> dict:
    """Where to go back to for a Studio-generated file, and whether it is still there."""
    return fix_ledger.original_for(_data_dir(), output)


def fix_history_export(limit: int = 50) -> dict:
    """The same history with file locations removed, for a bug report."""
    return fix_ledger.export_all(_data_dir(), limit=limit)


def health() -> dict:
    return {"status": "ok", "api_version": API_VERSION}


def doctor(path: str) -> dict:
    """Read-only U1 compatibility diagnosis for a file path. Never modifies the file."""
    return diagnose_path(path).to_dict()


def compatibility_check(path: str) -> dict:
    """Read-only Compatibility Doctor: detect common U1/Orca project issues.
    Never modifies the file."""
    return compatibility.check(path)


def model_search_query(query: str, filters: dict | None = None) -> dict:
    """Model Discovery Hub v1: metadata search across sanctioned providers.
    No scraping; no import. Returns {results, providers_queried, warnings}."""
    return model_search.search(query, filters)


def scale_preview(path: str, scale_percent: float) -> dict:
    """Scale Doctor: analysis-only uniform-scale preview. Writes nothing."""
    return scale_doctor.preview(path, float(scale_percent))


def scale_options(path: str, printer: str = "snapmaker_u1", margin_mm: float = 5.0) -> dict:
    """Scale Doctor size-options ladder. Analysis-only; writes nothing."""
    return scale_doctor.scale_options(path, printer, margin_mm)


def print_failure_troubleshoot(path: str, symptom: str = "fails_even_with_supports",
                               known_good_print: bool | None = None, known_good_material: str | None = None,
                               failed_material: str | None = None, failure_stage: str = "unknown") -> dict:
    """Print Failure Troubleshooter (known-good aware). Read-only; writes nothing."""
    return print_failure.troubleshoot(path, symptom, known_good_print,
                                      known_good_material, failed_material, failure_stage)


def quality_check(symptom: str, path: str | None = None) -> dict:
    """Print Quality Doctor: advisory checklist for a symptom. Read-only.

    When a file path is given, enrich the advice with file-specific *evidence* from the
    other doctors (mesh, insights, bed-fit, first-layer) so the guidance is grounded in
    this model. Each evidence fetch is best-effort: a doctor that errors is skipped and
    the advisory result is still returned. Advisory only — no guarantees, no auto-fix."""
    resp = dict(print_quality.lookup(symptom))
    if path and resp.get("result"):
        from snapstudio_core import quality_evidence

        def _safe(fn):
            try:
                return fn()
            except Exception:
                return None

        ev = quality_evidence.evidence_for(
            symptom,
            _safe(lambda: mesh(path)),
            _safe(lambda: insights(path)),
            _safe(lambda: bed_fit(path)),
            _safe(lambda: first_layer(path)),
        )
        resp["result"] = {**resp["result"], "evidence": ev, "evidence_available": bool(ev)}
    return resp


def source_compatibility(path: str) -> dict:
    """File/source ecosystem detection: what kind of file/project this is, what Studio
    can read, what it can't convert yet, and the recommended next step. Read-only."""
    from snapstudio_core import source_compatibility as sc
    return sc.detect_detailed(path)


def first_layer_check(symptom: str) -> dict:
    """First Layer Doctor: advisory checklist for a first-layer symptom. Static."""
    return first_layer_doctor.lookup(symptom)


def convert(path: str, out_dir: str | None = None, prepare_mode: str = "preserve",
            dry_run: bool = False) -> dict:
    """Make a file U1-ready and save it next to the source. Returns the result."""
    result = convert_to_u1(path, out_dir, prepare_mode=prepare_mode, dry_run=dry_run).to_dict()
    if not dry_run and result.get("output_path"):
        summary = result.get("settings_summary") or {}
        _record_fix(
            fix_ledger.PREPARE, path, result["output_path"],
            changes=(summary.get("compat_changed") or []) + (summary.get("mapped_to_u1") or []),
            findings=[{"title": item.get("key"), "detail": item.get("reason")}
                      for item in (summary.get("could_not_carry") or [])],
            validated=result.get("validated_ok"),
            notes=list(summary.get("warnings") or []))
    return result


def prepare_scaled(path: str, scale_percent: float, out_dir: str | None = None) -> dict:
    """Create a new uniformly-scaled U1 copy (STL input). Original never modified."""
    from snapstudio_core.convert import prepare_scaled_copy
    result = prepare_scaled_copy(path, scale_percent, out_dir).to_dict()
    if result.get("output_path"):
        _record_fix(fix_ledger.SCALE, path, result["output_path"],
                    changes=[{"key": "scale", "old": "100%", "new": f"{scale_percent:g}%",
                              "reason": "you chose this size"}],
                    validated=result.get("validated_ok"))
    return result


def diff(a: str, b: str) -> dict:
    """Compare two projects (read-only): what changed between A and B."""
    return diff_projects(ThreeMF.open(a), ThreeMF.open(b)).to_dict()


def insights(path: str) -> dict:
    """Rich read-only Project Intelligence (geometry, materials, readiness)."""
    from snapstudio_core.intelligence import project_info
    return project_info(path)


def report(path: str) -> dict:
    """Read-only Validation Center report: checks + preserved/changes/at-risk."""
    from snapstudio_core.validation_report import readiness_report
    return readiness_report(path)


def canonical(path: str) -> dict:
    """Read-only source-neutral view of a design (multi-ecosystem foundation)."""
    from snapstudio_core.canonical import to_canonical
    return to_canonical(path).to_dict()


def mesh(path: str) -> dict:
    """Read-only mesh diagnostics: integrity, overhang/supports, stability, volume."""
    from snapstudio_core.mesh_diagnostics import analyze
    return analyze(path)


def strategies() -> dict:
    """List the intent-based print strategies (read-only). Orca still slices."""
    from snapstudio_core.strategies import list_strategies
    return list_strategies()


def strategy_recommend(path: str) -> dict:
    """Recommend a print strategy from REAL design signals (read-only). Never fabricates
    duration, tool-change count, or purge volume."""
    from snapstudio_core import strategies as strat
    from snapstudio_core.intelligence import project_info
    info = project_info(path)
    signals = {
        "colors": info.get("colors"),
        "source_family": info.get("source_family"),
        "dimensions_mm": info.get("dimensions_mm"),
        "triangles": info.get("triangles"),
        "complexity": info.get("complexity"),
        "issues": info.get("issues"),
    }
    # Enrich with real mesh diagnostics when available (best-effort, read-only).
    try:
        from snapstudio_core.mesh_diagnostics import analyze as _mesh
        md = _mesh(path)
        if md.get("available"):
            signals["tip_risk"] = md["stability"]["tip_risk"]
            signals["supports_likely"] = md["overhang"]["supports_likely"]
    except Exception:
        pass
    rec = strat.recommend(signals)
    rec["signals"] = {k: signals[k] for k in ("colors", "source_family", "dimensions_mm", "complexity")}
    return rec


def project_cost(path: str, price_per_kg: float = 20.0, currency: str = "$",
                 prices: dict | None = None) -> dict:
    """Material cost from the slicing result the project already carries.

    Returns available=False with an explanation when the file has no real
    figures — the UI shows that instead of a fabricated number.
    """
    from snapstudio_core import project_cost as pc
    return pc.estimate(path, price_per_kg=price_per_kg, currency=currency, prices=prices)


def placement_check(path: str) -> dict:
    """Read-only: where each object sits relative to the U1's printable area."""
    from snapstudio_core import plate_placement
    return plate_placement.assess(path)


def prepare_placed(path: str, out_dir: str | None = None) -> dict:
    """Write a new copy with the whole arrangement moved onto the U1 plate.

    Refuses without writing when one move cannot honestly fix the project. The
    original is never modified.
    """
    from snapstudio_core import plate_placement
    result = plate_placement.prepare_placed_copy(path, out_dir=out_dir)
    if result.get("ok") and result.get("output_path"):
        before = result.get("before") or {}
        _record_fix(
            fix_ledger.PLACEMENT, path, result["output_path"],
            changes=[{"key": "object placement", "old": "off the U1 plate",
                      "new": change.get("detail"), "reason": change.get("kept")}
                     for change in (result.get("changes") or [])],
            findings=[{"title": f"Object {item.get('object_id')} outside the plate",
                       "detail": item.get("edges") and f"past the {item['edges']} edge"}
                      for item in (before.get("off_plate") or [])],
            validated=not ((result.get("after") or {}).get("off_plate")))
    return result


def printer_facts(host: str | None = None, port: int = 7125) -> dict:
    """Everything Studio can honestly say about a printer right now.

    Gathers only read-only endpoints, and reports `reachable: False` with the
    reason rather than raising when the printer is not there. Fields the firmware
    does not expose stay absent — Preflight turns those into "unknown", never into
    "not supported".
    """
    import time as _time

    from snapstudio_core import moonraker, printer_profiles

    if not host:
        return {"reachable": False, "error": "no printer address configured",
                "hint": moonraker.not_found_hint(), "observed_at": _time.time()}
    probe = moonraker.probe(host, port)
    # Every live fact is only true as of the moment it was read. Stamping that
    # here is what lets the send path say "this was checked four minutes ago"
    # instead of presenting it as though it were still being observed.
    facts: dict = {"reachable": bool(probe.get("reachable")), "host": host,
                   "port": probe.get("port", port), "observed_at": _time.time()}
    if not facts["reachable"]:
        facts["error"] = probe.get("error")
        # The address came from the user, so Studio does not know what is at it.
        facts["hint"] = moonraker.not_found_hint(host)
        return facts
    try:
        caps = moonraker.capabilities(host, port)
        facts["toolhead_count"] = caps.get("toolhead_count")
        facts["bed_mm"] = caps.get("bed_mm")
        facts["klipper_objects"] = caps.get("klipper_objects") or []
    except Exception:
        facts["klipper_objects"] = []
    try:
        # The temperature channels follow the printer's own extruder count rather
        # than a list sized for four toolheads.
        facts["print_state"] = moonraker.status(
            host, port, tool_count=facts.get("toolhead_count")).get("print_state")
    except Exception:
        pass
    try:
        loaded = moonraker.loaded_filaments(host, port)
    except moonraker.PrinterUnavailable as exc:
        # Asking failed. That is not the printer saying it has no filament state,
        # and reporting it as such would be a claim about the user's machine made
        # on no evidence.
        facts["loaded_filaments_error"] = str(exc)
        loaded = None
    if loaded is not None:
        # The printer looked, so say so on every entry. Provenance was added with
        # the provider work and stamped inside `material_providers`, but a stock
        # setup never goes through that module — `loaded_filaments` is read here
        # directly — so the most common configuration of all carried no
        # provenance at all, and anything asking "did the printer confirm this?"
        # got no for the one case where the answer is unambiguously yes.
        facts["loaded_filaments"] = [
            dict(entry, confirmed_by="printer") if isinstance(entry, dict) else entry
            for entry in loaded
        ]

    # Identification is inference from what the machine reported, and it is
    # deliberately the last thing done rather than the first: every check above
    # works on a printer Studio cannot name, and nothing below is allowed to
    # override a live fact. `identify` returns no match far more often than a
    # match, which is the correct answer — Moonraker publishes no model name.
    identity = printer_profiles.identify(facts)
    facts["identity"] = identity
    profile = None
    if identity.get("printer_id"):
        try:
            profile = printer_profiles.load(identity["printer_id"])
        except KeyError:
            profile = None
    facts["profile"] = printer_profiles.summarise(profile)
    facts["resolved"] = printer_profiles.resolve(facts, profile)
    return facts


def color_plan(path: str, toolheads: int | None = None) -> dict:
    """Classify a project's colours against the toolheads available.

    Reports which colours share layers (and so need a toolhead each), which are
    introduced at a height (and may be planned swaps), and which Studio cannot
    classify. Painted colour is decoded from the project's own facet data — the
    slots it uses, the area each covers and the heights each spans — and a
    painted colour is only offered as a swap when its separation from every other
    colour is proven.
    """
    from snapstudio_core import color_plan as cp
    return cp.analyse(path, toolheads=toolheads)


def fidelity_audit(original: str, prepared: str) -> dict:
    """What survived preparing a copy, element by element, with the reason for
    anything changed or dropped — and an explicit list of what Studio could not
    verify."""
    from snapstudio_core import fidelity
    return fidelity.audit(original, prepared)


def preflight(path: str, host: str | None = None, port: int = 7125) -> dict:
    """Join what this project needs to what this printer reports.

    When a printer is reachable, object placement is re-checked against the
    printer's *real* bed rather than the published U1 volume.
    """
    from snapstudio_core import preflight as pf
    from snapstudio_core import plate_placement, project_traits

    project = project_traits.extract(path)
    facts = printer_facts(host, port)

    bed = None
    dims = facts.get("bed_mm") or {}
    if dims.get("x") and dims.get("y"):
        bed = {"min_x": 0.0, "min_y": 0.0,
               "max_x": float(dims["x"]), "max_y": float(dims["y"])}
    try:
        # Name the plate after whatever supplied it, so a summary never describes a
        # live bed as though it were the U1's.
        placement = plate_placement.assess(
            path, bed=bed,
            bed_name=("this printer's" if bed else None))
    except Exception:
        placement = None

    out = pf.evaluate(project, facts, placement=placement)
    out["printer"] = {k: v for k, v in facts.items() if k != "klipper_objects"}
    return out


def gcode_facts(path: str) -> dict:
    """Read what a sliced G-code file states about itself."""
    from snapstudio_core import gcode
    return gcode.read_facts(path)


def post_slice(path: str, host: str | None = None, port: int = 7125,
               project_path: str | None = None) -> dict:
    """Join a sliced job to the printer it will run on.

    This is the second half of the preflight. The first half asks whether a
    *project* suits a printer; this asks whether the *job the slicer produced*
    suits the printer as it is right now — which is where the interesting
    failures live: a tool the job needs with an empty slot, a material that does
    not match, a job sliced for another machine.
    """
    from snapstudio_core import gcode, post_slice as ps

    facts = gcode.read_facts(path)
    printer = printer_facts(host, port) if host else {"reachable": False}

    project = None
    if project_path:
        from snapstudio_core import project_traits
        try:
            traits = project_traits.extract(project_path)
            project = {"filament_slots": _trait_value(traits, "filament_count")}
        except Exception:
            project = None

    out = ps.analyse(facts, printer, project)
    out["printer"] = {k: v for k, v in printer.items() if k != "klipper_objects"}
    return out


def _trait_value(traits: dict, key: str):
    entry = (traits or {}).get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def watch_folder(folder: str, project_path: str | None = None) -> dict:
    """Look in the folder the user chose for a sliced job that just appeared.

    Polled by the app while the user is on the page that cares. The engine keeps
    no background watcher, and nothing outside this folder is ever read.
    """
    from snapstudio_core import watch_folder as wf
    return wf.match_project(folder, project_path)


def slice_provenance(project_path: str, gcode_path: str) -> dict:
    """Is this G-code the slice of that project?"""
    from snapstudio_core import gcode, project_traits, provenance
    from pathlib import Path as _Path

    return provenance.compare(
        project_traits.extract(project_path),
        gcode.read_facts(gcode_path),
        project_name=_Path(project_path).name,
        gcode_name=_Path(gcode_path).name)


def _provider_choice(provider: str | None, provider_url: str | None,
                     spoolman: str | None) -> tuple[str, str | None]:
    """Which provider, and at what address.

    `spoolman=` is the older parameter, from when Spoolman was the only thing
    this could read. It still works and means exactly what it did, so nothing
    that already calls this has to change; the named pair is what the app sends
    now, because an address field called after one product is a seam that only
    looks generic.
    """
    from snapstudio_core import material_providers as providers

    url = (provider_url or "").strip() or (spoolman or "").strip() or None
    kind = (provider or "").strip().lower()
    if not kind:
        kind = providers.SPOOLMAN
    return kind, url


def _local_spool_rows(host: str) -> list[dict]:
    """This printer's local/manual spool notes, or nothing if the library DB
    cannot be read. A bookkeeping read must never break a printer report."""
    try:
        conn = _conn()
        try:
            return library.list_spools(conn, host)
        finally:
            conn.close()
    except Exception:
        return []


def _with_providers(printer: dict, host: str | None, port: int,
                    provider_url: str | None, slot_map: dict | None,
                    slot_base: int | None = None,
                    provider: str | None = None) -> dict:
    """Fold optional material providers into the printer's own report.

    The printer stays authoritative about what is in a slot; a provider can only
    add what the machine cannot know, such as a spool identity or a remaining
    weight. None of them is required for anything here to work — including the
    person's own local spool notes, which are offered even when no Spoolman or
    Bambuddy is configured, because that is the whole point of them existing.

    `provider` names which network provider to read and is not consulted again
    after the read returns: everything below this line is handed normalised
    facts.
    """
    if not host:
        return printer
    local_rows = _local_spool_rows(host)
    if not provider_url and not local_rows:
        return printer
    from snapstudio_core import material_providers as providers

    states = [providers.stock_u1(host, port)]
    if provider_url:
        # Whether the user counted their slots from 0 or from 1 is a fact only
        # they have. Guessing it puts every spool one slot out and then reports
        # the wrong material with complete confidence, so the app states it
        # rather than leaving the engine to infer it from the shape of the map.
        states.append(providers.read(provider or providers.SPOOLMAN, provider_url,
                                     slot_map, slot_base=slot_base))
    if local_rows:
        states.append(providers.local_spools(local_rows))
    combined = providers.combine(*states)
    loaded = providers.as_loaded_filaments(combined)
    if loaded is not None:
        printer = dict(printer)
        printer["loaded_filaments"] = loaded
        # The normalised slots as well as the flattened list. `loaded` drops a
        # slot that holds nothing, which loses the difference between a printer
        # reporting an empty slot and a mapping pointing at a spool that no
        # longer exists.
        printer["slot_facts"] = combined.get("slots")
        printer["material_sources"] = combined.get("sources")
        printer["remaining_known"] = combined.get("remaining_known", False)
    return printer


# --- local / manual spools (the fallback with no Spoolman or Bambuddy) -------

def local_spools(host: str) -> dict:
    """This printer's own local spool notes, one per slot the person has told
    Studio about — the fallback for a printer with no Spoolman or Bambuddy, or
    for a slot neither of them tracks."""
    from snapstudio_core import material_providers as providers
    conn = _conn()
    try:
        rows = library.list_spools(conn, host)
    finally:
        conn.close()
    return providers.local_spools(rows)


def save_local_spool(host: str, slot: int, *, material: str | None = None,
                     subtype: str | None = None, color: str | None = None,
                     vendor: str | None = None, starting_g: float | None = None,
                     remaining_g: float | None = None, notes: str | None = None) -> dict:
    """Record what a person says is on a spool, in their own words, right now.

    A partial update: any field left as None keeps whatever was already on
    record for this slot, so editing the colour cannot wipe out a remaining
    weight nobody touched. remaining_g is the one field with two real edges —
    only ever stamped USER_CONFIRMED, with a fresh timestamp, when THIS call
    explicitly gives a new figure; otherwise the existing weight, quality and
    timestamp are carried through, UNLESS this same call also changes the
    material or vendor to something different from what was on record. A
    changed material or vendor means a different physical spool went into
    this slot, and whatever was known about the OLD spool's remaining weight
    says nothing about this one — carrying it over would report a made-up
    material's weight under the new material's name. That case resets the
    remaining weight to unknown rather than either guessing or blocking the
    rest of the edit. Without the general carry-through rule, resending an
    old, already-DERIVED figure just to change something else would silently
    turn Studio's own arithmetic back into a claim the person just
    reconfirmed it.
    """
    from snapstudio_core import material_providers as providers
    now = _now()
    conn = _conn()
    try:
        existing = library.get_spool(conn, host, slot) or {}
        material_changed = (material is not None and existing.get("material") is not None
                            and material != existing.get("material"))
        vendor_changed = (vendor is not None and existing.get("vendor") is not None
                          and vendor != existing.get("vendor"))
        if remaining_g is not None:
            merged_remaining_g = remaining_g
            remaining_quality = providers.USER_CONFIRMED
            remaining_as_of = now
        elif material_changed or vendor_changed:
            merged_remaining_g = None
            remaining_quality = None
            remaining_as_of = None
        else:
            merged_remaining_g = existing.get("remaining_g")
            remaining_quality = existing.get("remaining_quality")
            remaining_as_of = existing.get("remaining_as_of")
        library.upsert_spool(
            conn, host=host, slot=slot,
            material=material if material is not None else existing.get("material"),
            subtype=subtype if subtype is not None else existing.get("subtype"),
            color=color if color is not None else existing.get("color"),
            vendor=vendor if vendor is not None else existing.get("vendor"),
            starting_g=starting_g if starting_g is not None else existing.get("starting_g"),
            remaining_g=merged_remaining_g, remaining_quality=remaining_quality,
            remaining_as_of=remaining_as_of,
            notes=notes if notes is not None else existing.get("notes"),
            updated_at=now)
        row = library.get_spool(conn, host, slot)
    finally:
        conn.close()
    return row or {}


def delete_local_spool(host: str, slot: int) -> None:
    conn = _conn()
    try:
        library.delete_spool(conn, host, slot)
    finally:
        conn.close()


def mark_local_spool_used(host: str, slot: int, used_g: float) -> dict:
    """Subtract a confirmed amount from a local spool's remaining weight.

    Only ever reached from an explicit "mark N g as used?" confirmation a
    person made after a print — never a side effect of slicing, sending or
    printing. The result is stamped DERIVED (estimated), not USER_CONFIRMED:
    Studio did the subtraction, the person did not just weigh the spool and
    tell it a fresh number.
    """
    from snapstudio_core import material_providers as providers
    conn = _conn()
    try:
        row = library.apply_spool_usage(
            conn, host=host, slot=slot, used_g=used_g,
            remaining_quality=providers.DERIVED, at=_now())
    finally:
        conn.close()
    if row is None:
        raise ValueError(
            "no local spool record for that slot with a remaining weight to subtract from — "
            "give it a remaining weight first")
    return row


def provider_test(url: str, provider: str | None = None) -> dict:
    """Can Studio read this material provider, and what does it see?

    The one thing a person needs before trusting any of this: press a button, get
    a straight answer. It reports the number of spools and how many of them carry
    a remaining weight something is actually keeping — because "connected" and
    "useful" are different, and a provider full of spools nothing has printed from
    answers no question about whether a print will finish.

    Read-only, and it never raises: a provider that is not there is an answer.
    """
    from snapstudio_core import freshness, material_providers as providers

    kind = (provider or providers.SPOOLMAN).strip().lower()
    name = providers.PROVIDER_NAMES.get(kind, kind)
    try:
        normalised = providers.validate_provider_url(url)
    except providers.InvalidProviderAddress as exc:
        return {"schema_version": providers.SCHEMA_VERSION, "ok": False,
                "reason": str(exc), "spools": 0, "provider": kind}

    state = providers.read(kind, normalised)
    if not state.get("available"):
        return {"schema_version": providers.SCHEMA_VERSION, "ok": False,
                "reason": state.get("error") or f"{name} did not answer.", "spools": 0,
                "provider": kind}

    spools = state.get("spools") or []
    tracked = [s for s in spools
               if s.get("remaining_quality") == providers.TRACKED
               and freshness.assess(s.get("remaining_as_of"))["trustworthy"]]
    return {
        "schema_version": providers.SCHEMA_VERSION,
        "ok": True,
        "provider": kind,
        "spools": len(spools),
        "with_tracked_weight": len(tracked),
        "archived": sum(1 for s in spools if s.get("archived")),
        # Deliberately not the address: this response is rendered in the app and
        # can end up in a screenshot.
        "detail": _provider_detail(name, len(spools), len(tracked)),
        "choices": [
            {"id": s.get("id"),
             "label": " ".join(x for x in (s.get("vendor"), s.get("name") or s.get("material"))
                               if x) or f"spool {s.get('id')}",
             "material": s.get("material"),
             "color": s.get("color"),
             "remaining_g": s.get("remaining_g"),
             "remaining_quality": s.get("remaining_quality"),
             "archived": bool(s.get("archived"))}
            for s in spools
        ],
    }


def _provider_detail(name: str, total: int, tracked: int) -> str:
    """Two numbers, because "connected" and "useful" are genuinely different.

    The same sentence fits both providers because both have the same shape of
    answer: a spool nobody has printed from reports what it started with, and
    that is a declared size rather than a record of anything.
    """
    if not total:
        return (f"{name} answered, but has no spools in it yet. Add your spools there "
                "and Studio will see them.")
    plural = "s" if total != 1 else ""
    if not tracked:
        return (f"{name} answered with {total} spool{plural}. None of them has a weight "
                f"{name} is keeping track of yet — it reports what a spool started with "
                "until something prints from it, so Studio will treat those figures as "
                "estimates rather than facts.")
    return (f"{name} answered with {total} spool{plural}, {tracked} of them with a "
            "recent tracked weight Studio can use.")


def print_plan(path: str) -> dict:
    """The ordered account of what a sliced job actually does.

    Separate from `post_slice` because it costs a full pass over the file — a few
    seconds on a 300 MB job — while the post-slice checks answer immediately.
    """
    from snapstudio_core import gcode, print_plan as pp

    plan = pp.scan(path)
    facts = gcode.read_facts(path)
    plan["narration"] = pp.narrate(plan, facts)
    plan["summary"] = pp.summary(plan)

    # The scan can hold twenty thousand events; the app shows the narration and the
    # counts. Sending all of them was a megabyte over the loopback and a megabyte
    # held in the page for nothing.
    events = plan.get("events") or []
    plan["event_count"] = len(events)
    plan["events"] = events[:EVENT_SAMPLE]
    plan["events_sampled"] = len(events) > EVENT_SAMPLE
    return plan


#: How many raw events to hand to the app. Enough to show a slice of the timeline
#: if anything ever wants to; not the whole scan.
EVENT_SAMPLE = 200


def material_plan(path: str, host: str | None = None, port: int = 7125,
                  spoolman: str | None = None, slot_map: dict | None = None,
                  slot_base: int | None = None, provider: str | None = None,
                  provider_url: str | None = None) -> dict:
    """What to load, and what can stay, for this sliced job."""
    from snapstudio_core import gcode, material_plan as mp

    kind, url = _provider_choice(provider, provider_url, spoolman)
    facts = gcode.read_facts(path)
    printer = printer_facts(host, port) if host else {"reachable": False}
    printer = _with_providers(printer, host, port, url, slot_map, slot_base, kind)
    out = mp.from_facts(facts, printer)
    out["printer"] = {k: v for k, v in printer.items() if k != "klipper_objects"}
    return out


def send_check(path: str, host: str | None = None, port: int = 7125,
               include_timeline: bool = False, project_path: str | None = None,
               spoolman: str | None = None, slot_map: dict | None = None,
               slot_base: int | None = None, provider: str | None = None,
               provider_url: str | None = None) -> dict:
    """Ready to send? Blockers, warnings and unknowns, kept apart."""
    from snapstudio_core import gcode, send_check as sc

    kind, url = _provider_choice(provider, provider_url, spoolman)
    facts = gcode.read_facts(path)
    printer = printer_facts(host, port) if host else {"reachable": False}
    printer = _with_providers(printer, host, port, url, slot_map, slot_base, kind)

    timeline = None
    if include_timeline:
        from snapstudio_core import print_plan as pp
        timeline = pp.scan(path)

    origin = None
    if project_path:
        from pathlib import Path as _Path

        from snapstudio_core import project_traits
        from snapstudio_core import provenance as pv
        try:
            origin = pv.compare(project_traits.extract(project_path), facts,
                                project_name=_Path(project_path).name,
                                gcode_name=_Path(path).name)
        except Exception:
            origin = None

    out = sc.evaluate(facts, printer, timeline=timeline, provenance=origin)
    out["provenance"] = origin
    # What this answer rests on, so the send itself can check the world has not
    # moved on since. Without it the upload would be acting on what was true when
    # the page was drawn.
    from snapstudio_core import send_state
    out["state"] = send_state.fingerprint(facts, printer, origin, file_stat=_file_stat(path))
    out["printer"] = {k: v for k, v in printer.items() if k != "klipper_objects"}
    return out


def _file_stat(path: str) -> dict:
    """What identifies *this* file, so one rewritten in place is not mistaken for
    the one that was checked.

    Size and modification time are not enough on their own: a re-slice that lands
    on the same byte count, written within the same timestamp tick, looks
    identical to both. So this also fingerprints the ends of the file - bounded,
    a few hundred kilobytes at most, and the ends are where a slicer writes
    everything that distinguishes one job from another.
    """
    import hashlib
    from pathlib import Path as _Path

    target = _Path(path)
    try:
        stat = target.stat()
    except OSError:
        return {}

    window = 64 * 1024
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    try:
        with target.open("rb") as handle:
            digest.update(handle.read(window))
            if stat.st_size > window * 2:
                # The middle as well as the ends. A re-slice almost always changes
                # the summary at the end, but "almost always" is not a property to
                # rest a send decision on, and a third window costs another 64 KB.
                handle.seek(max(window, (stat.st_size // 2) - (window // 2)))
                digest.update(handle.read(window))
                handle.seek(stat.st_size - window)
                digest.update(handle.read(window))
    except OSError:
        return {"size_bytes": stat.st_size, "modified": round(stat.st_mtime, 3)}

    return {"size_bytes": stat.st_size, "modified": round(stat.st_mtime, 3),
            "content": digest.hexdigest()[:16]}


def sliced_cost(path: str, price_per_kg: float = 20.0, currency: str = "$",
                prices: dict | None = None) -> dict:
    """Cost a job from the figures the slicer measured."""
    from snapstudio_core import gcode, sliced_cost as sc
    return sc.estimate(gcode.read_facts(path), price_per_kg=price_per_kg,
                       currency=currency, prices=prices)


def ecosystem_advice(path: str, installed: dict | None = None) -> dict:
    """Read a project and say which open tool is the right next step for it.

    `installed` is supplied by the desktop shell: a map of tool id to the
    executable it actually found on disk. Anything not in that map is offered as
    a link, never claimed to be installed.
    """
    from snapstudio_core import ecosystem
    return ecosystem.advise(path, installed=installed)


def project_traits(path: str) -> dict:
    """The graded facts Studio read out of a project file, with evidence."""
    from snapstudio_core import project_traits as pt
    return pt.extract(path)


def printer_discover(hosts: list[str] | None = None) -> dict:
    """Read-only: probe candidate U1 hosts over Moonraker."""
    from snapstudio_core import moonraker
    return {"printers": moonraker.discover(hosts or None), "schema_version": "printer/1"}


def printer_status(host: str, port: int = 7125) -> dict:
    """Read-only: live U1 status (print state, bed + toolhead temps)."""
    from snapstudio_core import moonraker
    return moonraker.status(host, port)


def printer_history(host: str, port: int = 7125, limit: int = 20) -> dict:
    """Read-only: recent prints + failures + totals (Moonraker history)."""
    from snapstudio_core import moonraker
    return moonraker.history(host, port, limit)


def printer_file_metadata(host: str, filename: str, port: int = 7125) -> dict:
    """Read-only: the slicer's own estimates for a file on the printer (time, filament,
    layers, slicer) — extracted by Moonraker, no slicing done here."""
    from snapstudio_core import moonraker
    return moonraker.file_metadata(host, filename, port)


def printer_diagnostics(host: str, port: int = 7125) -> dict:
    """Read-only: klippy health + Moonraker warnings."""
    from snapstudio_core import moonraker
    return moonraker.diagnostics(host, port)


def printer_capabilities(host: str, port: int = 7125) -> dict:
    """Read-only: the U1's real bed volume + toolhead count."""
    from snapstudio_core import moonraker
    return moonraker.capabilities(host, port)


def printer_bed_mesh(host: str, port: int = 7125) -> dict:
    """Read-only: the printer's measured bed surface reduced to flatness insight stats."""
    from snapstudio_core import moonraker
    return moonraker.bed_mesh(host, port)


# ---- Printer Hub Phase B: control (user-initiated; UI confirms start/cancel/e-stop) ----

def printer_pause(host: str, port: int = 7125) -> dict:
    """Pause the running print (safe, reversible)."""
    from snapstudio_core import moonraker
    return moonraker.pause(host, port)


def printer_resume(host: str, port: int = 7125) -> dict:
    """Resume a paused print."""
    from snapstudio_core import moonraker
    return moonraker.resume(host, port)


def printer_cancel(host: str, port: int = 7125) -> dict:
    """Cancel the running print (the UI must confirm before calling this)."""
    from snapstudio_core import moonraker
    return moonraker.cancel(host, port)


def printer_start(host: str, filename: str, port: int = 7125) -> dict:
    """Start printing a gcode file already on the printer (the UI must confirm + show
    the filename before calling this)."""
    from snapstudio_core import moonraker
    if not filename:
        raise ValueError("missing 'filename'")
    return moonraker.start(host, filename, port)


def printer_emergency_stop(host: str, port: int = 7125) -> dict:
    """Emergency stop — cut heaters + halt motion (the UI must confirm on a dedicated
    screen before calling this)."""
    from snapstudio_core import moonraker
    return moonraker.emergency_stop(host, port)


def printer_job_queue(host: str, port: int = 7125) -> dict:
    """Read-only: the Moonraker job queue."""
    from snapstudio_core import moonraker
    return moonraker.job_queue(host, port)


def printer_upload_gcode(host: str, path: str, port: int = 7125,
                         confirm: bool = True, expect_state: dict | None = None,
                         project_path: str | None = None, spoolman: str | None = None,
                         slot_map: dict | None = None, slot_base: int | None = None,
                         provider: str | None = None,
                         provider_url: str | None = None) -> dict:
    """Upload a sliced gcode file (chosen by the user) to the printer.

    Two things happen before any bytes are sent. The file is checked against what
    Studio last checked, and the printer is asked what it is doing now — because
    the send confirmation a person read describes a moment that has since passed.
    A slot emptied, a spool swapped, a print started, the job re-sliced in place:
    each of those makes the answer on screen wrong, and none of them looks any
    different from the outside.

    When something has moved, this uploads nothing and says what changed. The user
    can look again and send if they still want to; what they cannot do is send on
    the strength of a check that no longer holds.
    """
    from snapstudio_core import moonraker, send_state
    if not path:
        raise ValueError("missing 'path'")

    if expect_state:
        fresh = send_check(path, host=host, port=port, project_path=project_path,
                           spoolman=spoolman, slot_map=slot_map, slot_base=slot_base,
                           provider=provider, provider_url=provider_url)
        moved = send_state.changes(expect_state, fresh.get("state"))
        if moved:
            return {
                "ok": False,
                "action": "upload",
                "state": "changed",
                "changed": moved,
                "detail": send_state.describe(moved),
                "check": fresh,
                "uploaded": False,
            }

    try:
        result = moonraker.upload_gcode(host, path, port)
    except moonraker.UploadRefused as exc:
        # The printer answered, and said no. That is a different problem from not
        # finding the printer at all, and it has a different fix.
        return {"ok": False, "action": "upload", "state": "refused_by_printer",
                "uploaded": False, "status": exc.status, "detail": str(exc)}
    except OSError as exc:
        return {"ok": False, "action": "upload", "state": "not_accepted", "uploaded": False,
                "detail": ("Studio could not finish sending the file to the printer: "
                           f"{getattr(exc, 'strerror', None) or exc}. Nothing on the printer "
                           "has been started.")}

    # An accepted POST is not a finished upload. Moonraker parses metadata
    # asynchronously, so a file can be on the printer and not yet readable by it —
    # which is how a tool ends up starting a job the machine cannot describe. Ask
    # the printer what it actually has before reporting success.
    if not confirm:
        result["state"] = "pending_verification"
        return result
    try:
        confirmation = moonraker.confirm_upload(
            host, result.get("filename") or "", expected_size=result.get("size"), port=port)
        result["confirmation"] = confirmation
        result["ok"] = bool(confirmation.get("ok"))
        result["state"] = _upload_state(confirmation)
    except Exception as exc:  # noqa: BLE001 — the upload happened; the check did not
        result["confirmation"] = {"ok": False, "error": f"{type(exc).__name__}",
                                  "detail": ("The file was sent, but Studio could not confirm "
                                             "the printer finished reading it.")}
        result["ok"] = False
        result["state"] = "unknown"
    return result


def _upload_state(confirmation: dict) -> str:
    """Which of the five things that can be true after an upload is true.

    Collapsing these into "upload failed" is how a person deletes and re-sends a
    file that is already on the printer, or starts one the printer has not finished
    reading. They are different situations with different next steps.
    """
    if not confirmation.get("present"):
        # The bytes were accepted and the printer does not list the file. Studio
        # cannot say where they went, and must not imply the job is ready.
        return "not_listed"
    if confirmation.get("size_matches") is False or confirmation.get("fresh") is False:
        return "mismatch"
    if not confirmation.get("metadata_ready"):
        return "pending_verification"
    return "verified"


def first_layer(path: str, host: str | None = None, port: int = 7125) -> dict:
    """First-Layer Intelligence: fuse the design's footprint/stability with the printer's
    REAL measured bed (when a host is reachable) into plain-language first-layer findings.
    Read-only end to end. Works design-only when no printer is connected."""
    from snapstudio_core.mesh_diagnostics import analyze
    from snapstudio_core import first_layer as fl
    md = analyze(path)
    if not md.get("available"):
        return {"schema_version": fl.SCHEMA_VERSION, "available": False,
                "reason": "geometry unavailable", "bed_aware": False}
    bed = None
    bed_dim = 270.0
    if host:
        from snapstudio_core import moonraker
        bed = moonraker.bed_mesh(host, port)            # never raises
        try:
            caps = moonraker.capabilities(host, port)   # can raise when unreachable
            if caps.get("bed_mm") and caps["bed_mm"].get("x"):
                bed_dim = caps["bed_mm"]["x"]
        except Exception:
            pass
    out = fl.assess(md.get("footprint"), md.get("stability"), bed, bed_dim)
    out["available"] = True
    return out


def cost_estimate(path: str, price_per_kg: float = 20.0, currency: str = "$") -> dict:
    """Material Cost Estimation: real material weight (from mesh geometry) x the user's
    filament price. Read-only; returns unavailable when geometry has no weight."""
    from snapstudio_core.mesh_diagnostics import analyze
    from snapstudio_core import cost_estimate as ce
    md = analyze(path)
    grams = md.get("material_estimate_g") if md.get("available") else None
    return ce.estimate(grams, price_per_kg, currency, basis="design estimate (PLA)")


def cost_to_price(path: str, host: str | None = None, filename: str | None = None,
                  port: int = 7125, currency: str = "$", **factors) -> dict:
    """Cost-to-Price Intelligence: true cost (material + power + machine wear +
    labour + failed-print buffer) and a suggested selling price with margin.

    Weight + print time come from the slicer's OWN metadata already on the U1 when
    a host + filename are given (most accurate); otherwise the design's geometry
    estimate is used for weight and time is left unknown. Read-only; never raises."""
    from snapstudio_core import pricing
    grams = None
    print_hours = None
    basis = "design estimate (PLA)"
    if host and filename:
        from snapstudio_core import moonraker
        try:
            md = moonraker.file_metadata(host, filename, port)
            if md.get("available"):
                grams = md.get("filament_weight_g")
                secs = md.get("estimated_time_s")
                print_hours = (secs / 3600.0) if secs else None
                basis = "printer slicer metadata"
        except Exception:
            pass
    if grams is None:
        from snapstudio_core.mesh_diagnostics import analyze
        mdg = analyze(path)
        grams = mdg.get("material_estimate_g") if mdg.get("available") else None
        if grams is not None:
            basis = "geometry estimate (volume × density)"
            # When grams are estimated from volume, scale by the chosen material's density.
            # The geometry estimate assumes PLA (1.24 g/cm³); the ratio re-bases it.
            dens = factors.get("material_density")
            try:
                if dens is not None and float(dens) > 0:
                    grams = grams * (float(dens) / 1.24)
                    basis = "geometry estimate (volume × material density)"
            except (TypeError, ValueError):
                pass
    # Explicit user overrides typed in the assumptions panel win over auto values.
    g_over = factors.get("grams_override")
    if g_over is not None:
        try:
            grams = float(g_over); basis = "your entered weight"
        except (TypeError, ValueError):
            pass
    h_over = factors.get("print_hours")
    if h_over is not None:
        try:
            print_hours = float(h_over)
        except (TypeError, ValueError):
            pass
    # Only forward known pricing factors; ignore unrelated keys defensively.
    allowed = {"price_per_kg", "power_w", "electricity_per_kwh", "machine_price",
               "machine_life_hours", "labor_hours", "labor_rate",
               "failure_rate_pct", "markup_pct", "marketplace_fee_pct",
               "packaging", "shipping_cost", "shipping_charged"}
    kw = {k: float(v) for k, v in factors.items() if k in allowed and v is not None}
    return pricing.price(grams, print_hours, currency=currency, basis=basis, **kw)


def printer_failure_insights(host: str, port: int = 7125, limit: int = 50) -> dict:
    """Failure-Pattern Learning: read the printer's OWN Moonraker history and surface
    failure patterns (rate, repeat-offender files, dominant cause, recent streak) as
    plain-language insight. Read-only; never raises on an empty/unreachable history."""
    from snapstudio_core import moonraker
    from snapstudio_core import failure_patterns as fp
    hist = moonraker.history(host, port, limit)
    return fp.assess(hist.get("jobs"), hist.get("totals"))


def batch_pricing(paths: list[str], currency: str = "$", **factors) -> dict:
    """Business Mode: price every part in a batch and roll them into one P&L —
    total cost, total suggested price, total profit across the whole job. Reuses
    cost_to_price per part (geometry weight); read-only; never raises on one part."""
    from snapstudio_core import pricing
    priced = []
    for p in (paths or []):
        try:
            priced.append(cost_to_price(p, currency=currency, **factors))
        except Exception:
            priced.append({"available": False})
    return pricing.aggregate(priced)


def mm_doctor(path: str, host: str | None = None, port: int = 7125) -> dict:
    """Multi-Material Doctor: one verdict for a multicolour U1 print — colours vs
    toolheads, filament-settings consistency, painted-region mapping. Uses the
    connected U1's real toolhead count when reachable, else the U1's 4. Read-only."""
    from snapstudio_core.intelligence import project_info
    from snapstudio_core import mm_doctor as mmd
    info = project_info(path)
    issues = info.get("issues") or []
    metadata_issues = [i for i in issues if "filament metadata inconsistent" in str(i)]
    heads = None
    heads_known = False
    if host:
        from snapstudio_core import moonraker
        try:
            caps = moonraker.capabilities(host, port)
            if caps.get("toolhead_count"):
                heads, heads_known = caps["toolhead_count"], True
        except Exception:
            pass
    return mmd.assess(info.get("colors"), heads=heads, heads_known=heads_known,
                      painted=bool(info.get("painted")), metadata_issues=metadata_issues,
                      object_count=info.get("objects") or 1)


def bed_fit(path: str, host: str | None = None, port: int = 7125) -> dict:
    """Bed-Fit / Out-of-Bounds Doctor: does the model fit the U1 bed, and if not,
    WHY (the cryptic 'out of bounds' error) and HOW to fix it. Uses the connected
    U1's real bed when reachable, else the known U1 bed. Read-only; works offline."""
    from snapstudio_core.intelligence import project_info
    from snapstudio_core import bed_fit as bf
    info = project_info(path)
    dims = info.get("dimensions_mm")
    object_count = info.get("objects") or 1
    multi = (info.get("colors") or 0) > 1
    bed = None
    bed_known = False
    if host:
        from snapstudio_core import moonraker
        try:
            caps = moonraker.capabilities(host, port)
            bm = caps.get("bed_mm")
            if bm and bm.get("x"):
                bed, bed_known = bm, True
        except Exception:
            pass
    return bf.assess(dims, bed=bed, bed_known=bed_known,
                     object_count=object_count, multi_material=multi)


def predict_success(path: str, host: str | None = None, port: int = 7125) -> dict:
    """Print Success Prediction: synthesise design readiness + toolhead fit +
    first-layer risk + (when a printer is reachable) its health score and this
    file's prior-failure count into one pre-print likelihood. Read-only; the
    printer-side signals are simply skipped when no host is given."""
    from snapstudio_core import success_predict as sp
    from snapstudio_core.validation_report import readiness_report
    import os
    readiness = toolfit = fl = health = None
    prior = 0
    try:
        readiness = readiness_report(path)
    except Exception:
        pass
    try:
        toolfit = toolhead_fit(path, host, port)
    except Exception:
        pass
    try:
        fl = first_layer(path, host, port)
    except Exception:
        pass
    if host:
        try:
            health = printer_health(host, port)
        except Exception:
            pass
        try:
            from snapstudio_core import moonraker
            base = os.path.basename(path).lower()
            hist = moonraker.history(host, port, 50)
            from snapstudio_core import failure_patterns as fp
            fa = fp.assess(hist.get("jobs"), hist.get("totals"))
            for ro in (fa.get("repeat_offenders") or []):
                if (ro.get("filename") or "").lower() == base:
                    prior = int(ro.get("failures") or 0)
        except Exception:
            pass
    return sp.predict(readiness=readiness, toolfit=toolfit, first_layer=fl,
                      health=health, prior_failures=prior)


def pricing_doctor(path: str, host: str | None = None, filename: str | None = None,
                   port: int = 7125, currency: str = "$", **factors) -> dict:
    """Pricing Doctor: hobby / marketplace / premium selling prices for a print,
    built on the Cost Doctor's true cost. Read-only."""
    from snapstudio_core import pricing
    cost = cost_to_price(path, host, filename, port, currency, **factors)
    if not cost.get("available"):
        return {"schema_version": "pricing/1", "available": False,
                "reason": cost.get("reason", "no cost available")}
    fee = float(factors.get("marketplace_fee_pct") or 0.0)
    out = pricing.tiers(cost.get("true_cost"), currency=currency, marketplace_fee_pct=fee)
    out["true_cost_basis"] = cost.get("basis")
    return out


def profit_doctor(path: str, host: str | None = None, filename: str | None = None,
                  port: int = 7125, currency: str = "$", prints_per_month: int = 20,
                  fixed_cost: float | None = None, batch_count: int = 10,
                  **factors) -> dict:
    """Profit Doctor: profit per print, margin, batch, monthly projection and
    break-even — built on the Cost Doctor's cost and suggested price. Read-only."""
    from snapstudio_core import pricing
    cost = cost_to_price(path, host, filename, port, currency, **factors)
    if not cost.get("available"):
        return {"schema_version": "pricing/1", "available": False,
                "reason": cost.get("reason", "no cost available")}
    fc = fixed_cost if fixed_cost is not None else float(factors.get("machine_price") or 0) or None
    return pricing.profit_analysis(
        cost.get("true_cost"), cost.get("suggested_price"), currency=currency,
        prints_per_month=prints_per_month, fixed_cost=fc, batch_count=batch_count)


def printer_firmware(host: str, port: int = 7125) -> dict:
    """Firmware Capability Intelligence: interpret the U1's OWN klipper object list
    into a plain-language capability set (mesh, input shaping, runout, exclusion,
    custom macros, multi-toolhead) and flag extended firmware. Read-only."""
    from snapstudio_core import moonraker, firmware_caps as fwc

    try:
        caps = moonraker.capabilities(host, port)
    except Exception as exc:  # noqa: BLE001 — a printer that will not answer is an answer
        # A route that 500s tells the user nothing. "Studio could not ask" is a
        # state the page already knows how to render, and it is the truth.
        return {"schema_version": fwc.SCHEMA_VERSION, "available": False,
                "error": f"the printer did not answer: {type(exc).__name__}",
                "features": [], "extended_firmware": False,
                "extended_firmware_evidence": None, "many_custom_macros": False,
                "summary": "Studio could not ask this printer what its firmware exposes."}
    # One short request, and only ever read as a positive: a community firmware
    # that serves its own page is announcing itself. No answer means Studio does
    # not know, never that the printer is running stock.
    probe = moonraker.extended_firmware(host)
    # Name the machine only when Studio has evidence of which one it is. An
    # unidentified printer is "This printer", not a model Studio assumed.
    from snapstudio_core import printer_profiles
    identity = printer_profiles.identify({
        "reachable": True,
        "toolhead_count": caps.get("toolhead_count"),
        "klipper_objects": caps.get("klipper_objects") or [],
    })
    name = None
    if identity.get("printer_id"):
        try:
            name = "Your " + printer_profiles.display_name(
                printer_profiles.load(identity["printer_id"]))
        except KeyError:
            name = None
    out = fwc.interpret(caps.get("klipper_objects"), caps.get("toolhead_count"),
                        caps.get("bed_mm"), extended_probe=probe, printer_name=name)
    out["identity"] = identity
    return out


def community_knowledge(query: str = "", risks: list | None = None) -> dict:
    """Community Knowledge Doctor (MVP): map a symptom (or the Report's risks) to
    curated community-known causes + fixes. Read-only, offline."""
    from snapstudio_core import community_knowledge as ck
    hits = ck.match_risks(risks) if risks else ck.match(query)
    return {"schema_version": ck.SCHEMA_VERSION, "query": query,
            "matches": hits, "count": len(hits)}


def plate_inspect(path: str) -> dict:
    """Per-Plate Filament Remapper — read-only inspection: plates by UI number,
    their objects, and the filaments in use (Commit A)."""
    from snapstudio_core import plate_remap
    return plate_remap.inspect(path)


def plate_dry_run(path: str, ui_plate: int, from_filament: int, to_filament: int) -> dict:
    """Per-Plate Filament Remapper — dry-run JSON diff, writes nothing (Commit B)."""
    from snapstudio_core import plate_remap
    return plate_remap.dry_run(path, int(ui_plate), int(from_filament), int(to_filament))


def plate_export(path: str, ui_plate: int, from_filament: int, to_filament: int,
                 out_path: str | None = None) -> dict:
    """Per-Plate Filament Remapper — verified safe export (Commit C). Writes a NEW
    3MF (never the source), changes only the target plate's object extruders, and
    passes a verification gate or quarantines the output."""
    from snapstudio_core import plate_remap
    return plate_remap.export_remap(path, int(ui_plate), int(from_filament),
                                    int(to_filament), out_path)


def demo_report() -> dict:
    """Demo Mode: a complete, representative Studio Intelligence Report with no
    file and no printer — for a sub-10-second reviewer demo."""
    from snapstudio_core import intelligence_report as ir
    return ir.demo()


def intelligence_report(path: str, host: str | None = None, filename: str | None = None,
                        port: int = 7125, currency: str = "$", **factors) -> dict:
    """Studio Intelligence Report: run every Doctor and synthesise one verdict —
    Studio score, will-it-print, cost, price, profit, biggest risk, next action,
    with each Doctor as supporting evidence. Read-only; one failing Doctor never
    sinks the report."""
    from snapstudio_core import intelligence_report as ir

    def _safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None

    predict = _safe(predict_success, path, host, port)
    bed = _safe(bed_fit, path, host, port)
    mm = _safe(mm_doctor, path, host, port)
    fl = _safe(first_layer, path, host, port)
    health = _safe(printer_health, host, port) if host else None
    cost = _safe(cost_to_price, path, host, filename, port, currency, **factors)
    pricing = _safe(pricing_doctor, path, host, filename, port, currency, **factors)
    profit = _safe(profit_doctor, path, host, filename, port, currency=currency, **factors)
    # Object spacing / collisions are not verified by Studio yet — pass an honest
    # status so the report never claims "no major blockers" for multi-object plates.
    from snapstudio_core.collision import assess_spacing
    _info = _safe(insights, path) or {}
    spacing = assess_spacing(_info.get("objects"), str(path).lower().endswith(".stl"))
    return ir.build(predict=predict, bed_fit=bed, mm=mm, first_layer=fl,
                    health=health, cost=cost, pricing=pricing, profit=profit, spacing=spacing)


def printer_health(host: str, port: int = 7125, limit: int = 50) -> dict:
    """Printer Health Score: fold the U1's OWN read-only signals — firmware/
    connectivity diagnostics + print-history failure patterns — into one 0–100
    score, a grade, and plain-language drivers. Read-only; never raises."""
    from snapstudio_core import moonraker, failure_patterns as fp, health_score as hs
    diag = None
    fail = None
    try:
        diag = moonraker.diagnostics(host, port)
    except Exception:
        pass
    try:
        hist = moonraker.history(host, port, limit)
        fail = fp.assess(hist.get("jobs"), hist.get("totals"))
    except Exception:
        pass
    return hs.score(diagnostics=diag, failures=fail)


def toolhead_fit(path: str, host: str | None = None, port: int = 7125) -> dict:
    """Toolhead-Fit Intelligence: does the design's colour count fit the U1's toolheads?
    Uses the printer's REAL toolhead count when a host is reachable, else the U1's known 4.
    Read-only end to end; works offline (printer-unaware) when no host is given."""
    from snapstudio_core.intelligence import project_info
    from snapstudio_core import toolhead_fit as tf
    info = project_info(path)
    colors = info.get("colors")
    heads = None
    known = False
    if host:
        from snapstudio_core import moonraker
        try:
            caps = moonraker.capabilities(host, port)   # can raise when unreachable
            if caps.get("toolhead_count"):
                heads = caps["toolhead_count"]
                known = True
        except Exception:
            pass
    return tf.assess(colors, heads, known)


def library_list(query: str = "", tag: str | None = None) -> dict:
    """List indexed projects, newest first. Optional name search / tag filter."""
    conn = _conn()
    try:
        rows = (library.search_projects(conn, query, tag)
                if (query or tag) else library.list_projects(conn))
        return {"projects": rows, "count": len(rows), "schema_version": "library/1"}
    finally:
        conn.close()


def library_delete(project_id: int) -> dict:
    """Remove a project from the index. Does NOT touch the user's files."""
    conn = _conn()
    try:
        library.delete_project(conn, int(project_id))
        return {"deleted": int(project_id)}
    finally:
        conn.close()


def library_history(project_id: int) -> dict:
    """Workflow timeline for one project, newest first (read-only)."""
    conn = _conn()
    try:
        events = library.get_history(conn, int(project_id))
        return {"project_id": int(project_id), "events": events, "schema_version": "history/1"}
    finally:
        conn.close()


def record_diagnosis(path: str, result: dict) -> None:
    """Best-effort: index a file the user just diagnosed + log a history event. Never raises."""
    try:
        conn = _conn()
        try:
            pid = library.upsert_project(
                conn, name=os.path.basename(path), source_path=path,
                source_family=result.get("family"), output_path=None,
                verdict=result.get("verdict"), score=result.get("score"),
                filament_count=result.get("filament_count"),
                last_action="doctor", updated_at=_now())
            library.add_history(conn, pid, "doctor",
                                f"Checked — {result.get('verdict', '')}".strip(" —"), _now())
        finally:
            conn.close()
    except Exception:
        pass  # the library is an index; failing to record must not break /doctor


def record_conversion(path: str, result: dict) -> None:
    """Best-effort: index a successful conversion + log a history event. Never raises."""
    try:
        try:
            diag = diagnose_path(path).to_dict()
        except Exception:
            diag = {}
        conn = _conn()
        try:
            pid = library.upsert_project(
                conn, name=os.path.basename(path), source_path=path,
                source_family=diag.get("family"),
                output_path=result.get("output_path"),
                verdict=diag.get("verdict"), score=diag.get("score"),
                filament_count=diag.get("filament_count"),
                last_action="convert", updated_at=_now())
            library.add_history(conn, pid, "convert",
                                f"Made U1-ready — {result.get('output_name', '')}".strip(" —"), _now())
        finally:
            conn.close()
    except Exception:
        pass


def _convert_and_record(path: str, out_dir: str | None = None) -> dict:
    """Convert one file and index it. Used by the batch worker so batched
    conversions land in the library exactly like single ones."""
    result = convert(path, out_dir, prepare_mode="preserve")
    record_conversion(path, result)
    return result


# --- batch jobs (background queue) -------------------------------------------
# A job runs in a daemon thread and publishes progress snapshots into _jobs.
# Clients start a job, then poll batch_status(job_id) until finished.

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOBS_MAX = 32  # cap retained jobs; the sidecar can run for days


def _prune_jobs_locked() -> None:
    """Evict oldest *finished* jobs so _jobs can't grow without bound. Running
    jobs are always kept. Caller must hold _jobs_lock."""
    if len(_jobs) <= _JOBS_MAX:
        return
    finished = [k for k, v in _jobs.items() if v["status"] in ("done", "error")]
    for k in finished[: len(_jobs) - _JOBS_MAX]:  # dict preserves insertion order
        _jobs.pop(k, None)


def batch_start(paths: list[str], out_dir: str | None = None) -> dict:
    """Kick off a batch conversion in the background. Returns a job handle."""
    if not paths:
        raise ValueError("no paths to convert")
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job_id] = {"id": job_id, "status": "running", "error": None, "result": None}

    def on_item(res) -> None:
        with _jobs_lock:
            _jobs[job_id]["result"] = res.to_dict()

    def worker() -> None:
        try:
            run_batch(paths, _convert_and_record, out_dir, on_item)
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
        except Exception as e:  # the orchestrator shouldn't raise, but be safe
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "total": len(paths), "schema_version": "batch/1"}


def batch_status(job_id: str) -> dict | None:
    """Current snapshot of a job, or None if the id is unknown."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        # shallow copy; result dict is already rebuilt fresh on each on_item
        return {"id": job["id"], "status": job["status"],
                "error": job["error"], "result": job["result"]}
