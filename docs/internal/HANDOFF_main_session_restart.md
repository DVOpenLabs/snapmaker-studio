# Start here — session restart, 2026-08-28

The single file a fresh session should read first. Everything below is current as
of the commit that carries it.

## Exact state

| | |
|---|---|
| Current stable release | **v0.8.0**, published, latest, untouched |
| Release tag | `v0.8.0` → `e12bc59` |
| `main` and `origin/main` | in step, tree clean, no stashes |
| Release evidence | `docs/internal/evidence/0.8.0.json` unchanged; no snapshot edited |

No exact HEAD is written here on purpose: a handoff naming the hash of the commit
that contains it is stale the moment it is committed. What matters is that the
tree is clean, `main` and `origin/main` agree, and the gates below pass.

## Verification on `main`

Backend **1811 passed / 4 skipped** · desktop **340** · `u1convert selfcheck`
**27/27** · `tsc --noEmit` clean · `cargo check` clean · production build clean.

**Installed acceptance: 43/43**, run 2026-08-28 against a development installer
built from this tree — 17,101,301 bytes, sha256
`505762ef6fe5e23e4caf3ca9ccf5a474d86a08ae1cb1023db12b50acf399949d`. It carries the
version string 0.8.0 and **is not the published v0.8.0 asset**, whose sha256 is
`67776cd1…`; a development build from a later commit simply inherits the version
in the manifests. Full account below.

**Real U1, read-only: 57/57**, run 2026-08-28 against that same installer with a
physical Snapmaker U1 on the network. The current development runtime — commit
`25d99a7`, installer `505762ef…` — is **hardware verified**. Full account below.

**There is no release.** v0.8.0 remains the published release and its own
evidence is unchanged; nothing here makes v0.8.0 newly verified, and nothing here
is a v0.9.0. The next release is a minor — **v0.9.0**, not v0.8.1 — and it needs
its own final installer and its own evidence.

## Start here

```
cd "D:/STL Files/snapmaker-studio"
git status --short                       # expect clean
git rev-parse HEAD origin/main           # expect the two to match
cd backend && py -m pytest -q            # expect 1731 passed, 4 skipped
```

Python is `py` on this machine — there is no `python` on PATH and no virtualenv.
Backend tests run from `backend/`; the desktop gates are `npm run test`,
`npx tsc --noEmit` and `npm run build` from `desktop/`; `cargo check` from
`desktop/src-tauri`. The selfcheck is
`py -c "from u1convert.cli import cli; cli(['selfcheck'])"`.

## What is settled — do not reopen without a measured defect

Each of these was established by handing Snapmaker Orca a project, letting Orca
save it back, and reading what Orca wrote — never from a warning, a screenshot or
a matching key name, and always with a control that discriminates.

- **Per-object overrides.** `layer_height` (exact), `fill_density` →
  `sparse_infill_density` and `support_material` → `enable_support` (semantic).
  A per-object layer height is withheld on a multi-filament plate, because Orca
  refuses to slice a prime-tower plate whose objects differ.
- **The preset-deviation mechanism.** A value a project states is used **only**
  when the project declares it in `different_settings_to_system`. Entry 0 is the
  process preset, entries 1..N the filaments, the **last** the printer. A key in
  the wrong entry is ignored; an unrecognised key costs nothing.
- **Target readability.** `Metadata/model_settings.config` and
  `3D/_rels/3dmodel.model.rels` are required; `[Content_Types].xml` is ignored;
  `slice_info`, `filament_maps`, `model_instance`, `assemble` and `printer_model`
  are reconstructed by Orca.
- **The Application gate.** Geometry-only mode needs **both** a flat root model
  and the case-sensitive substring `PrusaSlicer` in the Application. An invented
  name, `SuperSlicer`, `Slic3r` and lower case are all fine.
- **The U1 project contract.** Closed 2026-08-28 — see
  `HANDOFF_main_contract_closed.md`. Template is **541 keys**. The remaining 274
  preset-equal values are **REDUNDANT_BUT_HARMLESS / DEFERRED**.

Full measurement record: `docs/internal/PRUSA_SEMANTICS.md`. Template rule:
`backend/snapstudio_core/data/templates/PROVENANCE.md`.

## Installed acceptance — done, 43/43

Run 2026-08-28 against the installed application and its frozen sidecar, not the
dev server, with a real **Spoolman 0.26.1** and a real **Bambuddy 1.2.5.3** in
session-owned containers seeded through their own APIs. Clean install, launch,
close, reopen twice, uninstall, no orphan sidecar, install directory removed, and
the maintainer's own uninstall registration exported and restored.

What it now proves that it could not before:

- **The legacy wire still works.** `spoolman:` reaches a remaining weight and a
  send decision in the frozen build, and `provider`/`provider_url` decides
  *exactly* what it decided — the same verdict on the same slot, not merely
  something similar. `/provider/test` with no provider named still means Spoolman.
- **No provider means no request**, measured rather than asserted: a probe server
  counts what it receives, and the count does not move for any of the three
  shapes of none.
- **A redirect off the local network is refused in the shipped binary**, for both
  providers, with no trace of the public host's own answer in the error.
- **Equivalence in the installed build** — enough, tracked-recent-short, derived,
  undated, unknown, archived and a stale mapping all decide identically across
  the two providers.
- Impossible weights a real Bambuddy stores without complaint become unknown,
  never enough.

**One real defect was found, and it was a product defect rather than a harness
one:** a slot whose provider mapping named a spool that no longer existed was
described as *"the printer reports it empty"* with no printer configured and none
contacted. Fixed in `material_plan.plan`, which now takes the normalised slot
facts and says a different sentence for each of the three reasons a slot can be
absent. Seven regression tests. Reachable with Spoolman alone, and older than the
seam having two implementations.

Three further failures were defects in the new harness code and are fixed in it:
a probe script path split on the space in the repository path, a hit counter read
from an origin not allowed to fetch it, and probes tracked alongside the app so a
mid-run restart killed them. Two of those produced a connection refused that read
exactly like a product failure, which is why the run now proves the probes are
alive before the checks that depend on them.

**How to re-run it**, with both providers:

```
docker run -d --name <yours> -p 18912:8000 ghcr.io/donkie/spoolman:latest
docker run -d --name <yours> -p 18000:8000 -e PORT=8000 ghcr.io/maziggy/bambuddy:latest
# seed both, then export SNAPSTUDIO_SPOOL_* and SNAPSTUDIO_BB_* with the ids
pwsh -File tools/acceptance/run.ps1 -InstallerPath <rewrapped installer> -AttestationPath <its attestation> -SpoolmanUrl 127.0.0.1:18912 -BambuddyUrl 127.0.0.1:18000
```

Both provider addresses and the seeded spool ids arrive as environment variables,
so the positional argument contract the harness already had is untouched. A run
with neither provider still exercises everything that does not need one.

**A note for whoever seeds Bambuddy:** its scale route accepts a fractional
`weight_grams` and then its own list endpoint returns HTTP 500 serialising the
`last_scale_weight` it stored, because that field is declared an integer. Use a
whole number of grams. Studio survives it correctly — the provider becomes
unavailable and nothing is claimed — but it will stop a seeding script dead.

## Real U1 hardware — done, 57/57

Run 2026-08-28 through the installed application and its frozen sidecar against a
physical Snapmaker U1, pinned to the accepted installer rather
than whatever was newest in the bundle directory.

**Read-only, and the gate is printed before the first request.** Seven routes,
all reads; the allow-list is asserted against a deny-list of every control route
at load time. Nothing was uploaded, started, paused, resumed, cancelled, heated,
homed, moved or configured. The machine happened to be **mid-print when the run
began** and finished on its own during it — worth recording, because it means the
loaded-filament evidence is a machine genuinely using those spools, and because
nothing this harness can do could have interfered either way.

**Live identity, from the printer rather than its name.** `matched: true`,
`printer_id: snapmaker_u1`, `confidence: confirmed`, on the evidence that it
exposes `print_task_config` — which mainline Klipper does not — and reports four
toolheads. Moonraker **1.6.0**, Klipper **1.6.0.267_20260815150420**, klippy
ready, **196** firmware objects, 115 custom macros, 7 capabilities detected.

**Live wins over the profile**, everywhere it is asked: four toolheads from
`live`, 271 × 335 × 281 mm from `live`, four filament slots from `live`. The
travel envelope is larger than the printable plate and that is still **not** a
conflict — `conflicts: []` — because axis range and printable area answer
different questions.

**Eighteen new provider checks**, the ones that could not exist before there was
a second provider *and* a machine that can see its own spools:

- a provider that agrees supplies the weight the machine cannot know, and
  agreement is not reported as a disagreement;
- a provider that disagrees loses on material and keeps its weight;
- **the two providers decide identically about the same live observation**,
  agreeing and disagreeing alike, provenance name aside;
- an unreachable provider subtracts a weight, not the printer;
- nothing claims the printer weighed anything. A U1 is not a scale.

All 39 checks from the v0.8.0 hardware evidence are present and passing.
**Nothing was removed.** Evidence:
`docs/internal/hardware-main-25d99a7.json`, named for the runtime commit because
there is no version to name it after.

**How to re-run it:**

```
pwsh -File tools/hardware/verify.ps1 -PrinterHost <ipv4> -InstallerPath <rewrapped installer> -AttestationPath <its attestation>
```

Two things that cost time and will again:

- **Pass an IPv4 address.** Resolving the printer's name can hand back the IPv6
  link-local address first, zone index and all, and Studio then fails safe with
  "the printer did not answer" — correct behaviour, and indistinguishable at a
  glance from the printer being off.
- **Do not pass a hostname that is a substring of anything in the evidence.** The
  anonymiser replaces the address string wherever it appears, so a host called
  `u1` would rewrite `snapmaker_u1` into `snapmaker_<printer-on-lan>` and corrupt
  the identity evidence. An IP address has no such collision.

The provider addresses and seeded spool ids arrive through the environment, so a
run with no provider still does everything else and reports the provider checks
as skipped rather than passing.

## The second material provider — done

**Bambuddy** is the second implementation of the material-provider seam, closed
2026-08-28. Read `docs/internal/PROVIDER_AUDIT.md` (second half) before touching
any of it.

Seven candidates were researched against the live projects. U1Hub is **still**
ineligible — re-checked, and it has neither an intentional external API nor any
remaining-filament quantity. OpenSpool's tag format has no remaining field;
OctoPrint's SpoolManager offers a Python event bus rather than an HTTP API;
SpoolEase documents no API and carries a Commons Clause rider; SpoolBuddy and
FilaMan are clients of other people's inventories rather than inventories.

What the sprint established, and what not to redo:

- **The seam is generic, and it is proved.** `test_provider_seam_equivalence.py`
  builds each scenario from the raw payload each provider really returns, pushes
  it through that provider's real adapter, and demands the whole downstream
  result be *equal* after scrubbing the two names. Twelve situations. A source
  guard walks the AST of every generic consumer and fails on a comparison
  against a provider name.
- **The wire names are `provider` and `provider_url`.** `spoolman=` still works
  and means what it did, which is why the acceptance harness needed no change.
- **A local address that redirects to a public host used to be followed**, and
  the request left the machine. Fixed at the shared transport for every provider.
  If you add a third provider, you inherit that rule — do not write a second
  opener.
- **Bambuddy's remaining figure is arithmetic** (`label_weight - weight_used`)
  unless the spool has been weighed. `core_weight` and `last_scale_weight` are
  deliberately unused: a scale reading is gross weight and `core_weight` defaults
  to 250 g whether or not anyone set it.
- **Studio has no secure credential store.** A Bambuddy wanting an `X-API-Key`
  is told plainly that Studio cannot read it. Do not "fix" this by storing a
  token in `localStorage`.

A third provider is **not** wanted. Two implementations sharing no wire format
prove the seam; a third would cost the same and prove much less.

## Backlog

Every development verification gate is now closed. What remains is a **v0.9.0
convergence sprint**, which is not on this list because it is a release rather
than engineering: version bump, a *new* final installer with its own hash, the
full software gates, installed acceptance and the hardware harness re-run against
**that** binary, the v0.8.0 → v0.9.0 in-place upgrade, an immutable v0.9.0
evidence snapshot, and publish / re-download / re-hash. None of this sprint's
evidence transfers to a different binary.

1. Individual per-object placement, if the product ever wants it — the check
   already reports which objects are off the plate; it needs its own user intent
   and its own audit rows.
2. OBJ/GLB input — unchanged, still last.

The 274 preset-equal template values are **not** on this list. They are
deferred, not unfinished.

## Things that will bite

Everything under this heading in the earlier handoffs still applies. The ones
that cost the most time recently:

- **GUI automation needs an exclusive desktop.** The harness drives the
  foreground and is built to lose to whoever is using the machine. `GetLastInputInfo`
  measures *human* input only — another agent session on the same desktop makes
  the idle counter read quiet while stealing the foreground. Check both: no human
  input **and** a foreground that stays put.
- **Keep evidence paths short.** A 160-character path typed into Orca's file
  dialog loses its leading characters, and the failure reads as a save timeout.
  `WM_SETTEXT` and clipboard paste were both tried and neither could be verified.
  A short destination worked first time.
- **Orca reorders objects on save.** Compare per object by name; position and id
  are both the wrong key.
- **A fixture off the plate is `plate_placement` working.** The `prusa-semantics`
  sources land 1.0/1.5 mm off the U1 bed and Orca greys out Slice.
  `plate_placement.assess` names it and offers the one-piece move.
- **`prusa-multi-object` cubes are open shells** — "No layers were detected".
  Use solid geometry for anything that must slice.
- **The template is not the output.** `set_filament_block` rewrites every
  per-filament array at prepare time. Classify the prepared project, never the
  template.
- **Unicode digits.** `\d` in a Python regex matches them, and so does `float()`
  — `float("１０００")` is 1000.0. Spell out `[0-9]`. This has now been
  hit three times in this codebase.
- **Grep before building.** More than one sprint has started by writing a feature
  that already existed.

## The harness

It lives in a session scratchpad and goes when the session does — that is
correct, it does not belong in the repository. Rebuilding is about an hour and
the method is described in `HANDOFF_main_contract.md` and
`HANDOFF_main_contract_closed.md`. Its safety contract is not optional: refuse if
any slicer this session does not own is running, own the temp directory and the
pid, prove foreground ownership before every keystroke and click, never
force-kill anything this session did not start, and audit the machine afterwards.

## Release policy

**NO RELEASE** until a convergence sprint that runs, against the **final** built
installer: version bump, full software gates, installed acceptance, the
v0.8.0 → v0.9.0 in-place upgrade, the real-U1 hardware harness, an immutable
v0.9.0 evidence snapshot, and publish / re-download / re-hash.
