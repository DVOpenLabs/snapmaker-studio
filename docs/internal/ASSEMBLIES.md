# Assemblies (P5): multi-tile planning against shared spools

Evidence label: **fixture-tested**. Every input in the tests and screenshots is synthetic. No printer,
spool provider, library or real model file was read. Development build, not released software.

## What it does

An assembly is a project made of several tiles or parts, printed across plates, that share material
roles (for example "road" and "water") and therefore share spools. The page adds up what the tiles state
they need and compares that with the last stated remaining weight of each shared spool. The result is
advisory: it uses only the figures you give it and does not measure anything.

- **Tiles** carry a plate, a part id, a scale, a role-to-slot map, and grams per slot. Grams come from one of
  three sources: typed in (`usage`), a `project_compare.slot_usage` document (slots numbered from 1), or the
  `slots` of a `gcode.read_facts` document (tools numbered from 0). Both numbering schemes land on the same
  0-based `slot:n` id. Only the slicer figure (`sliced_g`) counts as grams.
- **Roles and bindings.** A role (road, water) is served by a different slot on different plates. The assembly
  binds each role to one spool (`SpoolRef`). A spool used through two roles, two slots or two tiles is counted
  once. Two providers' spools stay separate unless an explicit alias says they are the same spool.
- **Unknown stays unknown.** A slot with no stated grams is not zero. A tile with no gram source has an
  unknown need. A slot with no role, two roles, or a role with no bound spool has no known physical
  consumption, so the overall verdict cannot be "enough".
- **Supply** is an `Observation` of remaining grams (observed time, lifetime). `observations.freshness` decides
  whether it may be relied on (`usable_for_loadout`). A reading that is missing, undated, unusable or
  conflicting is *unknown*; an old, merely ageing (without `ageing_ok`) or restored reading is *stale*. Stale
  is reported as stale: neither a shortage nor "enough". The legacy `material_plan` sufficiency helper is not
  used (a test greps for it).
- **Verdicts per spool:** enough, shortage (names the spool, the tiles that run short in plate order, and the
  gram shortfall; when other tiles state no grams the figure is a lower bound), stale, unknown.
- **Other checks:** parts listed in the assembly with no tile are reported missing; a library project that no
  longer exists reads "missing" and one whose file differs from the recorded sha256 reads "changed"; tiles with
  different seam scales are flagged, and an unstated scale is reported as not stated; the attribution manifest
  (assembly and per tile) is kept exactly as written.

## Where things live

| Piece | Path |
|---|---|
| Model and validation | `backend/snapstudio_core/assemblies/model.py` |
| Evaluator | `backend/snapstudio_core/assemblies/evaluate.py` |
| `assemblies.db` (via `foundation.store.open_store`) | `backend/snapstudio_core/assemblies/store.py` |
| Routes (`/assemblies/evaluate, save, list, get, delete`) | `backend/snapstudio_api/routes_assemblies.py` |
| Page | `desktop/src/routes/ext/assemblies.{route.tsx,meta.ts}`, `desktop/src/lib/assemblies/` |
| Tests and fixtures | `backend/tests/assemblies/`, `backend/tests/fixtures/assemblies/` |
| Screenshots and how they were captured | `docs/internal/screens/assemblies/` |

Only assembly definitions are saved. Spool readings go stale, so they are supplied with each check and never
stored. The library cross-reference is a project id plus a sha256 in the definition and in a `tile_refs`
table, with no foreign key: the library is a different database the user can edit or empty. The library is
opened read-only and never created by a check.

## Known limits of this first version

- Tiles are entered as JSON on the page. There is no form builder, and no file picker that reads a 3MF or
  G-code into a tile; gram figures from `slot_usage` or `gcode.read_facts` are pasted in.
- A library project is compared by re-hashing its recorded source file when a tile records a sha256. A file
  over 256 MiB is not re-hashed inside the request and reads "not compared".
- Spool readings are typed in. Nothing here reads a printer or a spool provider; wiring supply from the
  Setups track is not done.
- Roles are matched by name. Role suggestions from model analysis are not done.
- No margin or waste allowance is added to the stated grams.
- The sidebar entry comes from the shared Studio+ navigation, which this package does not edit; the page is
  reachable at `/assemblies`.

## Test status against PLAN_V43 section 6, P5

| # | Test | Status |
|---|---|---|
| 1 | six tiles share road/water roles across plates | DONE |
| 2 | grams from slot_usage (1-based) / gcode facts (0-based) as `slot:n`, no double count of a `SpoolRef` | DONE |
| 3 | job without grams stays unknown | DONE |
| 4 | missing part listed; deleted library project reads "missing" | DONE |
| 5 | seam-scale mismatch flagged | DONE |
| 6 | attribution manifest retained | DONE |
| 7 | shortage names spool and starving tiles; unknown supply "unknown"; stale supply "stale" | DONE |
| 8 | foundation-aware evaluator; legacy sufficiency helper never referenced | DONE |
| 9 | unresolved slot-to-spool binding leaves physical consumption unknown | DONE |
| 10 | `assemblies.db` via the store; library cross-reference by id + sha256, no foreign key | DONE |
