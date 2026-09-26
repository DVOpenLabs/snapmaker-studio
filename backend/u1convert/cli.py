from __future__ import annotations
import json, shutil, sys
from pathlib import Path
import click
from snapstudio_core.container import ThreeMF
from snapstudio_core.detect import detect_source
from snapstudio_core.fingerprint import compute_fingerprint
from snapstudio_core.filaments import parse_remap
from snapstudio_core.repair import repair as do_repair
from snapstudio_core.validate import validate as do_validate
from snapstudio_core.doctor import diagnose_path as do_diagnose_path
from snapstudio_core.diff import diff_projects as do_diff
from snapstudio_core.report import write_fix_report
from snapstudio_core.errors import SnapStudioError

@click.group()
def cli():
    """Snapmaker Studio engine — a local-first workflow for modern 3D printing.

    Understand a design, check whether it will print, and get it print-ready.
    Bambu/Orca/STL today; Snapmaker U1 is the first printer target.
    """

@cli.command()
@click.argument("path", type=click.Path(exists=True))
def inspect(path):
    tm = ThreeMF.open(path)
    src = detect_source(tm)
    fp = compute_fingerprint(tm)
    click.echo(f"source: {src.family}  printer_model: {src.printer_model}  u1: {src.is_u1}")
    click.echo(f"objects: {fp.object_count}  plates: {fp.plate_count}  filaments: {fp.filament_count}")
    click.echo(f"painted_triangles: {sum(fp.painted_triangles.values())}")
    click.echo(f"filament colors: {list(fp.filament_colors)}")

def _run_repair(path, mode, remap, out, dry_run, opt_profile=None):
    if Path(path).suffix.lower() == ".stl":
        from snapstudio_core.stl_wrap import wrap_stl
        if dry_run:
            click.echo("DRY RUN - would wrap STL into U1 3MF; no files written"); return
        tm = wrap_stl(path)
        out_p = Path(out) if out else Path(path).with_name(Path(path).stem + "_SnapmakerU1.3mf")
        tm.save(out_p)
        res = do_validate(ThreeMF.open(out_p), against=None)   # generation -> structural+rules
        write_fix_report(out_p.parent / "FIX_REPORT.json",
                         [{"file": Path(path).name, "output": out_p.name, "source": "stl",
                           "generated": True, "validated_ok": res.ok, "errors": res.errors}],
                         base_dir=out_p.parent)
        click.echo(f"wrapped STL -> {out_p}  (validated_ok={res.ok})")
        return
    src = Path(path)
    tm = ThreeMF.open(src)
    src_fp = compute_fingerprint(tm)
    outcome = do_repair(tm, mode=mode, remap=parse_remap(remap), dry_run=dry_run,
                        opt_profile=opt_profile)
    if dry_run:
        click.echo("DRY RUN - no files written")
        click.echo(str(outcome.report)); return
    backup = src.with_suffix(".orig.3mf")
    if not backup.exists(): shutil.copy2(src, backup)
    out = Path(out) if out else src.with_name(src.stem + "_SnapmakerU1.3mf")
    tm.save(out)
    res = do_validate(ThreeMF.open(out), against=src_fp)
    entry = {"file": src.name, "output": out.name, **outcome.report,
             "validated_ok": res.ok, "errors": res.errors}
    write_fix_report(out.parent / "FIX_REPORT.json", [entry], base_dir=out.parent)
    click.echo(f"wrote {out}  (validated_ok={res.ok})")

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--mode", type=click.Choice(["safe","u1","optimize"]), default="u1")
@click.option("--remap", default=None, help='e.g. "5:1,4:3"')
@click.option("-o", "--out", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--opt-profile", default=None,
              help="optimization profile name (optimize mode only), e.g. u1_fast_prime_tower")
def repair(path, mode, remap, out, dry_run, opt_profile):
    try:
        _run_repair(path, mode, remap, out, dry_run, opt_profile)
    except SnapStudioError as e:
        raise click.ClickException(str(e))

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--against", type=click.Path(exists=True), default=None)
def validate(path, against):
    tm = ThreeMF.open(path)
    fp = compute_fingerprint(ThreeMF.open(against)) if against else None
    res = do_validate(tm, against=fp)
    click.echo(f"ok={res.ok} structural={res.structural_ok} rules={res.rules_ok} preservation={res.preservation_ok}")
    for e in res.errors: click.echo(f"  - {e}")
    if not res.ok: sys.exit(1)

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True)
@click.option("--opt-profile", default=None,
              help="optimization profile name, e.g. u1_fast_prime_tower")
def optimize(path, dry_run, opt_profile):
    try:
        _run_repair(path, "optimize", None, None, dry_run, opt_profile)
    except SnapStudioError as e:
        raise click.ClickException(str(e))

_PROJECT_TYPE = {"bambu-family": "Bambu/Orca project", "stl": "STL model", "unknown": "unknown"}

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def doctor(path, as_json):
    """Check whether a file will load cleanly on a Snapmaker U1, and what to do if not."""
    d = do_diagnose_path(path)
    if as_json:
        click.echo(json.dumps(d.to_dict(), indent=2, ensure_ascii=False))
    else:
        score = "n/a" if d.score is None else f"{d.score}/100"
        click.echo(f"Diagnosis: {Path(path).name}\n")
        click.echo(f"  Verdict : {d.verdict}")
        click.echo(f"  Score   : {score}\n")
        click.echo(f"  Project type           : {_PROJECT_TYPE.get(d.family, d.family)}")
        if d.input_type == "3mf":
            click.echo(f"  Snapmaker U1 compatible : {'yes' if d.is_u1 else 'no'}")
            click.echo(f"  Objects / plates        : {d.object_count} / {d.plate_count}")
            click.echo(f"  Filaments               : {d.filament_count}")
            click.echo(f"  Painted model           : {'yes' if d.painted else 'no'}")
            if d.validation_issues:
                click.echo("  File structure          :")
                for i in d.validation_issues: click.echo(f"    - {i}")
            if d.compatibility_issues:
                click.echo("  U1 compatibility        :")
                for i in d.compatibility_issues: click.echo(f"    - {i}")
            if not d.validation_issues and not d.compatibility_issues:
                click.echo("  Issues                  : none")
        click.echo(f"\nRecommended action: {d.recommended_action}")
        click.echo("Read-only check - no files were modified.")
    sys.exit(0 if d.verdict == "READY" else 1)

@cli.command()
@click.argument("file_a", type=click.Path(exists=True))
@click.argument("file_b", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def diff(file_a, file_b, as_json):
    """Compare two projects: what changed between FILE_A and FILE_B (read-only)."""
    d = do_diff(ThreeMF.open(file_a), ThreeMF.open(file_b))
    if as_json:
        click.echo(json.dumps(d.to_dict(), indent=2, ensure_ascii=False))
        return
    click.echo(f"Diff: {Path(file_a).name} -> {Path(file_b).name}\n")
    click.echo(f"  Structure : +{len(d.parts_added)} parts / -{len(d.parts_removed)}")
    for n in d.parts_added: click.echo(f"    + {n}")
    for n in d.parts_removed: click.echo(f"    - {n}")
    click.echo(f"  Geometry  : {'changed' if d.geometry_changed else 'unchanged'}")
    click.echo(f"  Objects {d.object_count[0]}->{d.object_count[1]}  "
               f"Plates {d.plate_count[0]}->{d.plate_count[1]}  "
               f"Filaments {d.filament_count[0]}->{d.filament_count[1]}")
    click.echo(f"  Painting  : {d.painted_triangles[0]} -> {d.painted_triangles[1]} painted triangles")
    click.echo(f"  Settings  : {len(d.settings_changed)} changed, "
               f"{len(d.settings_added)} added, {len(d.settings_removed)} removed")
    for c in d.settings_changed[:12]:
        click.echo(f"    {c['key']}: {str(c['old'])[:32]!r} -> {str(c['new'])[:32]!r}")
    if len(d.settings_changed) > 12:
        click.echo(f"    ... +{len(d.settings_changed) - 12} more (use --json for the full list)")
    if not d.has_changes:
        click.echo("\nNo differences.")


@cli.command("traits")
@click.argument("path", type=click.Path(exists=True))
def traits_cmd(path):
    """Print the graded facts Studio reads out of a project, with evidence.

    Machine-readable JSON: every trait carries its value, a confidence tier
    (confirmed / likely / informational / unknown) and the part of the file that
    proved it. This is the same data the app's Doctors reason from, so a script
    or another tool can consume it without going through the UI.
    """
    from snapstudio_core import project_traits
    click.echo(json.dumps(project_traits.extract(path), indent=2))


@cli.command("ecosystem")
@click.argument("path", type=click.Path(exists=True))
@click.option("--installed", "installed", default=None,
              help='JSON map of tool id to executable path, e.g. \'{"snapmaker-orca":"C:/.../x.exe"}\'.')
def ecosystem_cmd(path, installed):
    """Suggest which open-source tool suits this project, and why.

    Studio matches the project's real traits against its ecosystem registry
    (snapstudio_core/data/ecosystem.json). Tools are only reported as installed
    for ids given via --installed; nothing is probed or launched here.
    """
    from snapstudio_core import ecosystem
    try:
        found = json.loads(installed) if installed else None
    except json.JSONDecodeError:
        raise click.BadParameter("--installed must be a JSON object")
    if found is not None and not isinstance(found, dict):
        raise click.BadParameter("--installed must be a JSON object")
    click.echo(json.dumps(ecosystem.advise(path, installed=found), indent=2))



@cli.command("cost")
@click.argument("path", type=click.Path(exists=True))
@click.option("--price-per-kg", type=float, default=20.0, show_default=True,
              help="Your filament price per kilogram.")
@click.option("--currency", default="$", show_default=True)
def cost_cmd(path, price_per_kg, currency):
    """Material cost from the slicing result stored in the project.

    Reports available=false with an explanation when the file carries no real
    figures, rather than estimating one.
    """
    from snapstudio_core import project_cost
    click.echo(json.dumps(
        project_cost.estimate(path, price_per_kg=price_per_kg, currency=currency), indent=2))


@cli.command("placement")
@click.argument("path", type=click.Path(exists=True))
@click.option("--fix", is_flag=True, help="Write a new copy with the arrangement moved onto the plate.")
@click.option("--out-dir", type=click.Path(), default=None, help="Where to write the fixed copy.")
def placement_cmd(path, fix, out_dir):
    """Check whether every object sits inside the U1's printable area.

    With --fix, writes a NEW copy translated onto the plate when one move can do
    it honestly; the original is never modified and the command refuses rather
    than half-moving a project.
    """
    from snapstudio_core import plate_placement
    if fix:
        click.echo(json.dumps(plate_placement.prepare_placed_copy(path, out_dir=out_dir), indent=2))
    else:
        click.echo(json.dumps(plate_placement.assess(path), indent=2))

@cli.command("preflight")
@click.argument("path", type=click.Path(exists=True))
@click.option("--host", default=None, help="Printer address (IP or hostname). Omitted = project-only checks.")
@click.option("--port", type=int, default=7125, show_default=True)
def preflight_cmd(path, host, port):
    """Compare what this project needs against what a printer reports.

    Every check reports one of ok / attention / unknown, with its evidence and
    what to do. `unknown` means Studio could not read it — never that the printer
    cannot do it. Read-only: nothing is sent to the printer beyond status queries.
    """
    from snapstudio_api import service
    click.echo(json.dumps(service.preflight(path, host=host, port=port), indent=2))


@cli.command("fidelity")
@click.argument("original", type=click.Path(exists=True))
@click.argument("prepared", type=click.Path(exists=True))
def fidelity_cmd(original, prepared):
    """Report exactly what survived preparing a copy.

    Every element Studio can identify is classified as preserved (exactly or
    semantically), deliberately changed, deliberately removed, added, unsupported
    or unverified — with the reason. `claims` states what Studio is allowed to say
    about this pair; "nothing was lost" is only true when the audit proves it.
    """
    from snapstudio_core import fidelity
    click.echo(json.dumps(fidelity.audit(original, prepared), indent=2))


@cli.command("history")
@click.option("--source", type=click.Path(), default=None,
              help="Only entries produced from this project file.")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--share", is_flag=True,
              help="Omit file locations so the output is safe to paste into a bug report.")
def history_cmd(source, limit, share):
    """What Studio changed, newest first, and where to go back to.

    Each entry records the operation, what triggered it, every change with its old
    and new value, and whether the result validated. Your originals are never
    modified, so going back means opening the untouched file again.
    """
    from snapstudio_api import service
    if share:
        click.echo(json.dumps(service.fix_history_export(limit=limit), indent=2))
    else:
        click.echo(json.dumps(service.fix_history(source=source, limit=limit), indent=2))


@cli.command("colors")
@click.argument("path", type=click.Path(exists=True))
@click.option("--toolheads", type=int, default=4, show_default=True,
              help="How many toolheads the printer has.")
def colors_cmd(path, toolheads):
    """Say what a project with more colours than toolheads actually needs.

    Classifies each colour as sharing layers (needs a toolhead), introduced at a
    height (may be a planned swap), or unclassified. Painted colour is read from
    the project itself; what still needs the slicer is whether two colours land on
    the same layer, and a colour that cannot be proven separate is reported as
    unclassified rather than assumed easy.
    """
    from snapstudio_core import color_plan
    click.echo(json.dumps(color_plan.analyse(path, toolheads=toolheads), indent=2))


@cli.command("verify-printer")
@click.option("--host", required=True, help="Printer address (IP or hostname).")
@click.option("--port", type=int, default=7125, show_default=True)
def verify_printer_cmd(host, port):
    """Read-only hardware verification, safe to attach to a GitHub issue.

    Checks whether your printer answers, what Moonraker and its firmware
    report, and whether Studio recognises the model — nothing more. Every
    check is read-only: no print is started, nothing is uploaded, nothing on
    the printer is changed. The address you gave is never copied into the
    output in the first place — the checks below only ever report what the
    printer said or, on a failed connection, the local network error, never
    the address they asked — and whatever else could
    identify your network (your own username, hostname, a stray IPv4
    address) goes through the same redaction Studio's own support bundles
    use before you see it.

    Paste the JSON this prints into a "Help - Verify my printer" issue, or
    into docs/PRINTER_COMPATIBILITY.md's evidence table if you are the one
    maintaining it.
    """
    from snapstudio_core import hardware_verify
    bundle = hardware_verify.build_evidence(host, port=port)
    click.echo(json.dumps(bundle, indent=2))
    if any(c["result"] == "fail" for c in (bundle.get("checks") or [])):
        sys.exit(1)


@cli.command("selfcheck")
@click.option("--sample", type=click.Path(exists=True), default=None,
              help="Run against your own 3MF instead of the built-in fixture.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def selfcheck_cmd(sample, as_json):
    """Run the real pipeline end to end and print what worked.

    Nothing is stubbed and nothing is compared against a stored constant: each
    check asserts a property of a real result, so it can only pass if the feature
    genuinely worked. Everything is written to a temporary directory, and the
    input file is verified byte-identical afterwards.
    """
    from snapstudio_core import selfcheck as sc
    report = sc.run(sample)
    click.echo(json.dumps(report, indent=2) if as_json else sc.format_table(report))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":  # `python -m u1convert.cli` without installing the package
    cli()
