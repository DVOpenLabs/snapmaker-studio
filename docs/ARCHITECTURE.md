# Snapmaker Studio — Architecture

How the platform is built today, and how that maps to the kernel + plugins
direction in [PRODUCT_VISION.md](PRODUCT_VISION.md) §6.

## Layered overview

```
+----------------------------------------------------------+
|  Desktop shell  (Tauri v2 . React 18 . TS . Tailwind)     |
|  Dashboard . Projects . Workspace . Settings . drag-drop  |
+---------------^---------------------------+---------------+
                | get_api_info (Tauri cmd)  | HTTP (loopback, token)
+---------------+---------------------------v---------------+
|  Sidecar API  (snapstudio_api . stdlib http.server)       |
|  GET /health . POST /doctor . POST /convert  (CORS,token) |
+---------------------------+-------------------------------+
                            | pure function calls
+---------------------------v-------------------------------+
|  Engine kernel  (snapstudio_core . pure Python, no net/UI)|
|  detect . doctor . convert . repair . validate . stl_wrap |
|  u1_identity . filaments . fingerprint . config_io . rules|
|  + data/ (templates, profiles, rules, filament arrays)    |
+----------------------------------------------------------+
```

Two distribution forms:
- **Desktop app** — Tauri shell spawns the engine as a bundled sidecar.
- **`u1convert` CLI** — same kernel, command-line front end (inspect/doctor/
  repair/convert/validate/diff).

## Components (current)

### 1. Desktop shell (`desktop/`)
Tauri v2 (Rust) host + React/TypeScript/Tailwind UI. Routes: Dashboard, Projects,
Workspace (mock library), **LiveWorkspace** (real open->Doctor->Convert flow),
Settings. Open dialog + native drag-and-drop feed a Zustand session store, which
calls the sidecar via a small `api.ts`. Light/dark themes; Coming-Soon toasts for
not-yet-wired features. Packaged as a one-click NSIS installer (per-user, WebView2
bootstrapper).

### 2. Sidecar (`backend/snapstudio_api/`)
Loopback `http.server` bound to `127.0.0.1`, ephemeral port, per-launch auth
token, CORS for the webview origin. On start it prints a `{port, token}`
handshake the Rust host reads. Endpoints: `GET /health` (open), `POST /doctor`,
`POST /convert` (token-gated). In production it is a **PyInstaller-frozen exe**
(`snapstudio-api-...-msvc.exe`) bundled as a Tauri `externalBin` — **no system
Python required**. Lifecycle is leak-proof: a Windows **Job Object**
(`KILL_ON_JOB_CLOSE`) plus a Python parent-watchdog guarantee **zero orphan
processes** on graceful close, crash, or force-kill.

### 3. Engine kernel (`backend/snapstudio_core/`) — pure, no network/UI imports
- **`detect`** — classify source family (Bambu/Orca, Prusa, U1, generic) from
  archive parts + `printer_model`.
- **`doctor` (Diagnose)** — `diagnose_path()` -> verdict
  (READY/REPAIRABLE/CONVERTIBLE/HIGH_RISK), score/100, issue lists; read-only,
  `to_dict()` JSON-ready.
- **`convert` (Transform)** — orchestrates: STL -> wrap; geometry-only/foreign
  3MF (no `project_settings`) -> geometry wrap; Bambu/Orca 3MF -> repair. Writes
  `<stem>_SnapmakerU1.3mf` beside the source; **never overwrites the original**
  and writes no `.orig.3mf` backup for the desktop or API (the output is a new
  file). Only the CLI `repair` / `optimize` commands keep a `<stem>.orig.3mf`
  snapshot, as their in-place contract. `structure_problems()` is the one gate
  both Prepare (`check_structure`) and the Doctor use, so the Doctor does not
  recommend a Prepare the engine would refuse.
- **`repair`** — clamp rules -> profile swap -> conform filament arrays ->
  **`u1_identity`** normalize -> scrub foreign tokens -> blank slice_info version.
- **`u1_identity`** — the authoritative U1 identity layer: preset ids, version,
  filament identity (from the known-good reference), foreign Bambu/BBL/H2D scrub,
  newer-schema value normalization, and `is_u1_clean()` (the validation gate).
- **`stl_wrap`** — build a clean U1 project from raw geometry (STL or geometry-
  only 3MF), preserving meshes/build items; min-4 filament block; consistent
  per-filament arrays.
- **`validate`** — structural + rules + preservation (geometry fingerprint).
- **`filaments`** — per-filament array conformance (truncate/pad), purge
  matrix/vector resizing — the array-consistency that prevents "Customized
  Preset."
- **`fingerprint` / `config_io` / `container` / `rules`** — geometry hashing,
  JSON/XML (hardened lxml) IO, 3MF (OPC ZIP) read/replace, clamp rules.
- **`printer_profiles`** — facts about a machine (build volume, tool count, what
  it reports about its own materials) with a source and a verification level for
  each, plus the capability resolver that lets live evidence beat a profile.
- **`data/`** — `templates/` (known-good U1 project_settings), `profiles/`,
  `printer_profiles/` (U1 + one second machine), `u1_rules.json`,
  `u1_filament_arrays.json` — the declarative knowledge base.

### 4. Validation corpus (`validation/`)
`validate_corpus.py` scans a directory of **real** files (referenced by path,
never committed), converts each in a temp dir (sources untouched), runs Doctor,
classifies family + failure category, and writes `report.md` (success rate,
composition, per-file table). **Current: 112 files, 100% structurally valid in the internal gate — not print success.** This is the
reliability backbone and the future CI gate for plugins.

## Key design decisions

- **Pure kernel.** `snapstudio_core` has no network/UI imports, so it is testable,
  embeddable (sidecar *and* CLI), and freezable.
- **Preserve-by-default.** Geometry `.model` bytes are kept verbatim; conversion
  is metadata-level wherever possible; originals are never written.
- **Truthful validation.** `convert.validated_ok = structural/preservation AND
  is_u1_clean(output)` — success can't be reported unless the output is provably
  clean.
- **Local + sandboxed.** Loopback only, token-gated, hardened XML parsing
  (no XXE/network/DTD).

## Mapping to the kernel + plugin vision

| Today (hard-coded for U1) | Becomes (plugin contract) |
|---|---|
| `detect` family logic | **Ecosystem adapters** (Bambu/Orca/Prusa/Cura/...) |
| `u1_identity` + `data/profiles/` + templates | **Printer profile packs** (U1 is the first) |
| `repair` passes, `filaments` conformance, optimize | **Transform passes** |
| `is_u1_clean` / `validate` | **Validators** ("clean for target X?") |
| React routes/panels | **Views** |
| `validate_corpus.py` | **Corpus-as-CI** gating every plugin |

The refactor is incremental: extract stable contracts behind the existing
functions, then move U1 specifics into the first profile pack + adapter. No
rewrite — the proven kernel stays; the seams become public.

### Printer profiles — the first seam actually extracted

`printer_profiles.py` + `data/printer_profiles/*.json` is the kernel/plugin split
above, done for one layer rather than described. A profile holds **facts** about a
machine — build volume, tool count, what it reports about its own materials, what
it is known not to report — with a source for each and a verification level saying
how well established they are. It holds no behaviour: there is no per-printer
function in the package, and a test parses the generic printer modules and fails
the build on a conditional that branches on a model name.

Two rules make it more than a lookup table:

- **Live evidence beats the profile.** A profile says what a machine of this kind
  is expected to be; the machine says what it is. `resolve()` records which source
  won and reports a disagreement rather than correcting the hardware.
- **A capability is proved by a Klipper object, not by a manufacturer.** With no
  live object list a profile can say only what is *expected*, in those words.

The layer above it — Preflight, the Post-Slice Doctor, the send check, the
material plan, the firmware capability interpreter — reads what a printer reported
and never asks which printer it is. Two profiles ship: the Snapmaker U1
(hardware verified) and a VORON 2.4 250 (profile verified, no hardware tested).
See [PRINTER_COMPATIBILITY.md](PRINTER_COMPATIBILITY.md) for what each level
claims, and `internal/SECOND_PRINTER_PROOF.md` for what the exercise found.

The prepare path — `convert`, `repair`, `u1_identity`, `stl_wrap` — is
deliberately untouched by this. Studio prepares U1 copies for Snapmaker Orca; that
is the product, not an assumption to be abstracted away.

## Tech stack

- **Engine/CLI:** Python 3.13, stdlib + lxml; PyInstaller (sidecar freeze).
- **Sidecar:** stdlib `http.server` (no framework dependency).
- **Desktop:** Tauri v2 (Rust), React 18, TypeScript, Vite, Tailwind, Zustand,
  TanStack Query, React Router; `windows-sys` (Job Object).
- **Packaging:** NSIS (per-user), WebView2 download bootstrapper.
