# scene/1: the backend scene contract (PR 3a)

The engine can now describe a project's geometry, placement and engine findings as one bounded,
machine-checked document (`scene/1`), built by a cancellable background job. This is the backend half
only. There is no viewer and no desktop change in this PR.

* Contract: `backend/snapstudio_core/data/scene-1.schema.json` (JSON Schema 2020-12, frozen: every object
  closed, every field required, unknown is `null`).
* Golden scene: `backend/tests/fixtures/scene/golden-scene-1.json`, written by hand and independently of the
  builder by `make_golden.py` next to it. A test requires the real builder to reproduce it exactly.
* Builder: `backend/snapstudio_core/scene.py`. Every numeric budget lives in
  `backend/snapstudio_core/scene_limits.py` and nowhere else.
* Jobs and routes: `backend/snapstudio_api/scene_jobs.py`; `POST /scene/start | status | result | cancel`
  (existing `X-Auth-Token`; the result body is serialized once and sent by the new `_send_bytes`).
* Units fix: `backend/snapstudio_core/units.py`, applied to every dimension source (below).
* Measurements: `results.json` in this folder, produced by `backend/tools/scene_benchmark.py`.

Not covered: any viewer, the Tauri window, WebKitGTK, a screen reader, a real printer, and Linux (see
"What was not run").

## What a scene is, and is not

A scene is a **consistent snapshot of the file as it was copied for the job**. The job copies the source once
into a private file, hashes it (the `revision` is the SHA-256 of those bytes) and parses only the copy, so
replacing the original while a job runs cannot tear the scene. `SOURCE_CHANGED` applies only to (a) a file that
changed while it was being copied, (b) a reused `request_id`+path whose file now hashes differently from that
job's revision, and (c) an `expected_revision` that differs from the job's. It does **not** apply to edits made
after the snapshot was taken. The original file is only ever read (a test compares its bytes and mtime before and
after; so does the job test).

Scenes say what the file proves and no more:

* **Placement.** STL files, models with no build item and unresolved placement are `placement_state: "unknown"`.
  Their `world_mm` is an identity used only so something can be drawn. No bed-fit or size statement of any kind is
  attached to an unknown-placement node.
* **Plates.** Membership is per instance, from `model_settings.config` (`plate: known | ambiguous | unknown`).
  Plate origins are never invented (`origin_mm` is always `null`). A multi-plate project gets
  `MULTI_PLATE_PLACEMENT_UNCHECKED` and no placement findings, because the grid spacing is not in the file.
* **Volumes and roles.** Every mesh partitions *all* its triangles into volumes (`part`, `modifier`, `negative`,
  `support_enforcer`, `support_blocker`, `unknown`). The synthetic whole-mesh `part` volume
  (`source: "object"`) is used ONLY for an object that has no volume metadata at all. Prusa volume ranges are read
  by attribute name (the order of `firstid`/`lastid` does not matter); an unmapped gap, an overlap or an unreadable
  range is `unknown` (`UNKNOWN_VOLUME_ROLE`), never a guess. Bambu/Orca part records are **per use**, so the role
  lives on the node (`role_context`), not on the shared mesh: a mesh can be a negative part under one object and an
  ordinary part under another, and a role given to a component assembly applies to everything beneath it. Decision
  (differs from `placement.read_objects`, which defaults to `normal_part`): an object that HAS part records but none
  for one of its components gives that component `role_context: "unknown"`, `UNKNOWN_VOLUME_ROLE` and status
  `partial`, and no fit finding. A node's bounds, `printable` and every fit statement use only role=part geometry;
  non-part geometry is carried (`has_non_part_volumes`) and excluded from fit.
* **Production-extension build items.** A build item's `p:path` names the model FILE its object lives in. Node
  identity, repeated-instance counting and lookup use the pair (part path, object id); an unresolvable `p:path` is
  `UNRESOLVED_REFERENCE`, never a fall back to the root file. Per the Production Extension a `p:path` must be an
  absolute package path (leading `/`), and component `p:path` references are honoured only from the root model
  part; relative paths, and component paths in any other part, are `UNRESOLVED_REFERENCE`.
* **Fail closed across files and duplicates.** Where the file cannot prove an association the answer is
  unknown, not a guess: (1) when the project has slicer settings, every part beneath a build object that lives in
  another file gets `role_context: "unknown"` (the part records are matched against root-file objects), with
  `UNKNOWN_VOLUME_ROLE`, status `partial` and no fit finding; (2) plate records name a bare object id, so when two
  build resources in different files share an id, neither can be proven on a plate (`plate.state: "ambiguous"`,
  `PLATE_MEMBERSHIP_UNKNOWN`, no finding); (3) two settings records for the same (object id, part id) that disagree
  make the role unknown, identical duplicates are fine; (4) `UNSUPPORTED_UNIT` lists, in `target_ids`, the nodes
  living in the affected part(s), and `sources[].unit`/`mm_per_unit` are then the fallback millimetre values.
* **Bounded parsing everywhere.** Model parts, the Bambu settings, the Prusa config and every `.rels` are parsed
  with a counter on completed elements (1,000,000 each) and every completed element is released as soon as its data
  is consumed (the element itself only, never its siblings: records a parent reads later, such as a negative
  `<part>`, are never lost to an unknown neighbour), so a part under its byte cap that is made of millions of tiny
  elements is refused early. A part record without an `id` still counts as "this object has part metadata" (the
  components it cannot cover are `unknown`). A present-but-empty `p:path` is `UNRESOLVED_REFERENCE`, not absent.
  When the ROOT model's unit is unrecognized, the top node of every build item is listed in the `UNSUPPORTED_UNIT`
  `target_ids`, since each item's translation is written in that unit. STL files: the kind is
  decided from the header AND the size; a binary-looking header over the triangle budget is refused before any
  decoding or large allocation whether or not the size matches; ASCII is read in 1 MiB chunks with a 4 KiB line cap,
  split on LF, CRLF and a lone CR.
* **Bed.** The U1 rectangle comes from Studio's own template (`x 0.5..270.5, y 1..271`, 0.5 mm inward margin,
  the same numbers `plate_placement` uses). If the template yields no usable rectangle, `bed.policy` is
  `"fallback"`, `BED_TEMPLATE_UNAVAILABLE` is reported and **all fit findings are suppressed**.
* **Findings** carry `kind` (`placement | size | note`), `scope` (`project | plate | instance`), the engine
  that produced them (`scene`), a JSON pointer into the scene and target node ids. Scene-produced
  out-of-bounds and size statements are `placement` and `size`; the viewer copy rule (PR 3b) is that the word
  "fits" is never derived from a scene.
* **Repeated instances.** Several build items of one object id get their own nodes and their own geometric
  world bounds, but `REPEATED_INSTANCE_PLACEMENT_UNVERIFIED` is reported and no finding is attached, because the
  engine's existing placement answer for repeated items is wrong on `main` (see "Known limitations").
* **Non-millimetre sources.** Coordinates are converted to millimetres, and `sources[]` records each part's
  unit. Because the contract was written before the conversion was shared, placement findings are still
  disabled for any non-mm source (`NON_MM_SOURCE_UNIT`); size findings are not. A declared unit outside the six
  defined ones is NOT treated like an absent attribute: the scene reports `UNSUPPORTED_UNIT`, falls back to
  millimetres in `sources[]` (documented) and makes no fit statement.
* **Plates.** If a project has plates but an instance is on none, it is `PLATE_MEMBERSHIP_UNKNOWN`, status
  `partial`, with no fit finding.

## Units fix (a correction of wrong claims, not a new feature)

Several readers ignored the 3MF `<model unit="...">` header, so a 12 inch part was reported as 12 mm and
every size-based bed-fit statement for a non-millimetre project was wrong. One shared helper
(`snapstudio_core/units.py`: the six-unit `mm_per_unit` table, a header reader and a translation scaler) is now
applied to **every** dimension source. The header is read from the REAL root `model` element with the XML parser
(first start event; namespace prefixes, comments, processing instructions and a long preamble are irrelevant, and
a `<model unit=...>` inside a comment is not seen), by the same `resolve_unit` function the scene parser calls.
Absent means millimetre; an unrecognized value is a distinct, flagged outcome (`UnitInfo.recognized`), with the
legacy readers keeping their old millimetre fallback:

| Source | Change |
|---|---|
| `intelligence.project_info` (feeds DesignHealth, `service.insights`, strategy signals, `bed_fit`, `validation_report`, `canonical`, `layout`, `mm_doctor`, `toolhead_fit`) | vertex coordinates scaled per model part by that part's own unit |
| `geometry.build_item_dims` (feeds `layout`, `scale_doctor`, `plate_placement.assess`) | vertices scaled per part; component and build-item **translations** scaled too (a translation is a length in the model's unit) |
| `geometry.load_mesh` (feeds `scale_doctor.preview`, `mesh_diagnostics`) | vertices scaled per part |
| `placement.read_objects` | mesh points and transform translations scaled (through the shared helper); its repeated-instance behaviour is untouched |
| `plate_placement.prepare_placed_copy` (the "move onto the plate" fix) | the offset it writes is computed in millimetres and is now converted back to the ROOT model's unit before it is added to a build-item translation. A move that does not achieve its goal no longer leaves its copy on disk |

Behaviour for millimetre files is unchanged: the scale factor is exactly 1.0 and the code skips the multiplication.
Evidence: outputs of `project_info`, `build_item_dims`, `load_mesh`, `read_objects`, `plate_placement.assess` and
`scale_doctor.scale_options` were hashed over all 50 fixtures and examples in the tree on `main` (b01f7d0) and on
this branch and compared: **identical** (sha256 `73a018e5...69ef` both sides). `tests/test_units_consumers.py` pins every consumer
named in the plan (`canonical`, `layout`, `validation_report`, `bed_fit` via `service.bed_fit`, strategy signals,
DesignHealth data path via `service.insights`, Scale Doctor, `plate_placement.assess`, `read_objects`) for all six
units, and asserts that a 12 inch part reads 304.8 mm everywhere.

What this does **not** do (decision, plan v4 item 1): the size-based consumers still answer "does the model's
size fit the bed". They are not placement-aware. A small object translated off the plate, or separated instances
whose union is large, is still judged by size only. The scene's placement findings are the placement-aware
source. No consumer copy was edited here; qualifying those claims "by size" is PR 3c.

## Jobs

One worker thread, at most one queued job (newest wins; a running job is marked cancelled at once and the
replacement waits, queued, until the cancelled thread observes the flag and exits). States:
`queued | running | succeeded | failed | cancelled`. Terminal states are immutable and the first terminal wins
(a worker finishing after a cancel discards its result). 60 s deadline from the moment the job starts
running. A terminal job is kept 120 s or until more than 8 terminal jobs exist. An evicted or unknown id answers
404 `EXPIRED`; there is no stored "expired" state.

| Route | Answers |
|---|---|
| `/scene/session {}` | 200 `{client_id, ttl_s}` (server-issued 24-character id); 503 `SESSION_LIMIT` |
| `/scene/start {path, request_id, client_id?, seq?}` | 200 job; 400 `INVALID_REQUEST` (also: only one of `client_id`/`seq`, null or malformed values, `seq` reused for another request, `request_id` reused at a higher `seq`); 422 `UNSUPPORTED_FORMAT`; 409 `INVALID_REQUEST` (request_id reused for another path), `SOURCE_CHANGED`, `STALE_START`, `CANCELLED_BEFORE_START` or `SESSION_EXPIRED`; 503 `WORKER_WEDGED` |
| `/scene/status {job_id, client_id?}` | 200 `{state, stage, completed, total, error, revision}`; 404 `EXPIRED`. A job started in a session needs that session's `client_id`; a missing or different one answers exactly like an unknown id (404 `EXPIRED`), so existence is never confirmed |
| `/scene/result {job_id, client_id?, expected_revision?}` | 200 scene; 422 `{error: <code>}` for a failed job; 409 `CANCELLED` / `NOT_READY` / `SOURCE_CHANGED`; 404 `EXPIRED` |
| `/scene/cancel {job_id, client_id?}` or `{client_id, request_id, seq}` | 200 status (idempotent; a late cancel on a terminal job is a no-op; for a session job `client_id` is required, as for status and result). By request: 409 `SESSION_EXPIRED` for an unknown session; otherwise `dead_through` rises to `seq` and the job registered for exactly that client_id + request_id (if any) is cancelled, but only if it was started at or before that `seq` (a delayed cancel for an old attempt cannot cancel a newer job that reused the request id); with no such job the body is a `job_status` with `job_id: null`, `state: "cancelled"` |

Error codes: `INVALID_REQUEST UNSUPPORTED_FORMAT INVALID_ARCHIVE INVALID_GEOMETRY UNRESOLVED_REFERENCE
LIMIT_EXCEEDED SOURCE_CHANGED CANCELLED TIMEOUT EXPIRED NOT_READY WORKER_WEDGED INTERNAL STALE_START
CANCELLED_BEFORE_START SESSION_EXPIRED SESSION_LIMIT` (`BUSY` is not an error code: a new start replaces the client's own earlier work).

### Start ordering by session

A client that aborts or times out a start cannot stop that request from still reaching the engine, possibly AFTER
the start it actually wants. The engine therefore orders a client's starts itself. The design is a **session** with
O(1) state, not a set of remembered requests. Four invariants, each pinned by tests named `test_i1_...` to
`test_i4_...`:

* **I1: delayed starts cannot become valid through bookkeeping eviction.** A start is judged against the
  session's watermark, not against whether its job is still retained, so an evicted job does not make an old
  start admissible again.
* **I2: cancellation cannot be forgotten while the start remains admissible.** A cancel raises the session's
  `dead_through` mark, so that start and every lower `seq` stay refused for as long as the session lives.
* **I3: idempotency is scoped to (session, request) and ownership is checked consistently on every path.** Jobs
  are keyed by `(client_id, request_id)`; two sessions may use the same request_id and path and each gets, and
  can cancel, its own job; cancel by request matches both ids exactly.
* **I4: capacity exhaustion or session expiry fails explicitly; nothing old is silently revived.**

**Protocol.** `POST /scene/session {}` returns `{client_id, ttl_s}`; the engine chooses the id (24 characters of
`[A-Za-z0-9_-]`). Starts and by-request cancels carry that `client_id` and a `seq`, an integer from 1 to 2**53-1 that
the client treats as a strictly increasing generation counter for the session (the client only ever abandons lower
seqs when it moves to a higher one). Both keys or neither: null or half-present pairs are `400 INVALID_REQUEST`,
never a legacy start; ids must match in full (a trailing newline is rejected). With neither key the start behaves
exactly as before, in its own request_id-only namespace.

**State per session** (nothing else): `watermark` (highest admitted seq), `dead_through` (highest cancelled seq),
`current` = (seq, request_id, path, job_id) of the entry at the watermark.

**Rules, in order, under the registry lock that also registers jobs** (one admission function for every
successful start): unknown or expired `client_id` -> 409 `SESSION_EXPIRED` (a late start from an expired session
is refused, never re-created); `seq <= dead_through` -> 409 `CANCELLED_BEFORE_START`; `seq < watermark` -> 409
`STALE_START`; `seq == watermark` with the same request_id and path -> the registered job (idempotent), or 409
`STALE_START` if that job is no longer registered (an exact retry of an already-processed start is refused); equal
with anything else -> 400 `INVALID_REQUEST`; `seq > watermark` -> register (replacing the older job as before) and
set the watermark, except that a request_id already registered for the session is 400 `INVALID_REQUEST`
("request id reused": the old job is never handed back), and that attempt still raises the watermark so an older
attempt still in flight is refused. An idempotent repeat that was still hashing the file is re-judged by the same
rules BEFORE `SOURCE_CHANGED` is reported. After any refusal the client retries with a FRESH `request_id` and a
HIGHER `seq`.

**Ownership (I3).** Every job records the session that started it. Status, result and cancel-by-job_id on a session
job need that session's `client_id` (404 `EXPIRED`, identical to an unknown id, otherwise), and `replaced_job_id`
in a start response names a replaced job only when it belonged to the same session (or both are legacy); in every
other case it is `null`. Legacy jobs keep today's behaviour.

**After an admitted start that is then rejected** (`WORKER_WEDGED`, an unsupported format, a missing file) the
session's watermark has already advanced to that `seq`, so a delayed older attempt cannot be accepted behind it.
The client retries with a fresh `request_id` and a higher `seq`; an exact retry is `STALE_START`.

**Sessions.** At most 32 (`MAX_SESSIONS`), idle TTL 15 minutes (`SESSION_TTL_SECONDS`), touched by every start,
cancel (by request or by job_id), status and result. Sessions are pruned after expired jobs are evicted in the same pass. Only idle-expired sessions that own no registered job are pruned; a live session is never
evicted. At capacity with nothing prunable, opening a session is 503 `SESSION_LIMIT`.

**Limits, stated plainly.** Ordering is provided PER SESSION. It is not provided across sessions: a start from
another session replaces the previous job exactly as before. An engine restart drops every session, so the first
start from an old `client_id` answers `SESSION_EXPIRED` and the client must open a new session. Session expiry
likewise ends that session's ordering (explicitly: `SESSION_EXPIRED`, never a silent revival).

## Budgets (provisional) and the coverage decision

| Budget | Value |
|---|---|
| Snapshot copy ceiling / archive expansion | 128 MiB / 128 MiB |
| Model XML (all `.model` parts) | 32 MiB |
| Rendered triangles (every repetition counted) / distinct parsed triangles | 250,000 / 250,000 |
| Distinct vertices | 300,000 |
| Nodes / depth | 2,000 / 64 |
| Whole serialized response | 8 MiB (exact bytes; geometry pre-check refuses before encoding) |
| Ids | 128 characters, by construction (a long ancestry is replaced by a deterministic digest) |
| Part names carried on nodes / `<object>` definitions / XML elements | 256 characters / 20,000 / 1,000,000, all counted while parsing |
| Findings / limitations | 500 / 50 |

Exceeding any of these is `LIMIT_EXCEEDED`, never a shortened scene.

### Corpus and results

Qualifications: the four real-world fixtures are upstream files fetched by `fetch_real_world.py` and are absent from
this worktree (the benchmark read them from the main checkout); all five local samples are STL files (89% of the 11,604 local .stl/.3mf files are STL), so they exercise the STL path and say little about 3MF project structure; they
were chosen by size quantile, not at random; the fixture
called "100k" is 99,458 triangles; timings are one machine, one run.

Machine: Windows 11, Intel64 Family 6 Model 183 (32 logical CPUs), 63.8 GiB RAM, Python 3.13.14. Numbers are one
run on a quiet machine; warm = best of 3. Corpus: authored synthetic fixtures, the repo examples, the four
real-world fixtures (fetched by `fetch_real_world.py`, not committed) and five local projects chosen by size
quantile and recorded **only** as `P-01..P-05` (names and contents are never written). All 19 repo examples
fit and are summarized in `results.json`; four representative ones are shown here.

| id | class | size | result | triangles (rendered) | nodes | response | parse+encode warm | tracemalloc peak | RSS delta |
|---|---|---|---|---|---|---|---|---|---|
| S-cube | synthetic | 1.5 KiB | ok (complete) | 12 (12) | 1 | 2.0 KiB | 0.001 s | 0.1 MiB | 0.1 MiB |
| S-bambu-3parts | synthetic | 4.7 KiB | ok (complete) | 36 (36) | 4 | 5.0 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| S-prusa-volumes | synthetic | 2.6 KiB | ok (complete) | 24 (24) | 1 | 2.4 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| S-stl | synthetic | 0.7 KiB | ok (partial) | 12 (12) | 1 | 2.0 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| S-grid-10k | synthetic | 603.3 KiB | ok (complete) | 9,800 (9,800) | 1 | 233.6 KiB | 0.036 s | 1.3 MiB | 0.1 MiB |
| S-grid-50k | synthetic | 3.11 MiB | ok (complete) | 49,928 (49,928) | 1 | 1.15 MiB | 0.176 s | 5.6 MiB | 3.8 MiB |
| S-grid-100k | synthetic | 6.22 MiB | ok (complete) | 99,458 (99,458) | 1 | 2.28 MiB | 0.405 s | 10.9 MiB | 3.5 MiB |
| S-instances-300 | synthetic | 19.9 KiB | ok (partial) | 12 (3,600) | 300 | 187.3 KiB | 0.008 s | 1.8 MiB | 0.0 MiB |
| S-over-budget | synthetic (deliberately over) | 17.83 MiB | **refused `LIMIT_EXCEEDED`** | 279,752 | - | 6.42 MiB if budgets raised | 1.15 s if raised | - | - |
| E-demo_offplate_foreign | repo example | 9.7 KiB | ok (complete) | 12 (12) | 2 | 2.9 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| E-demo_u1_showcase | repo example | 1.7 KiB | ok (partial) | 12 (12) | 1 | 2.0 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| E-sample_cube | repo example | 0.7 KiB | ok (partial) | 12 (12) | 1 | 2.0 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| E-sample_cube_SnapmakerU1 | repo example | 9.7 KiB | ok (complete) | 12 (12) | 2 | 2.7 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| R-bambu-pa-pattern | real-world | 22.5 KiB | ok (complete) | 12 (12) | 2 | 2.8 KiB | 0.003 s | 0.1 MiB | 0.0 MiB |
| R-orca-badge | real-world | 797.9 KiB | ok (complete) | 72,586 (72,586) | 42 | 1.70 MiB | 0.274 s | 8.2 MiB | 3.0 MiB |
| R-orca-pa-line-dual | real-world | 29.0 KiB | ok (complete) | 24 (192) | 24 | 18.5 KiB | 0.002 s | 0.2 MiB | 0.0 MiB |
| R-prusa-seam-test | real-world | 2.40 MiB | ok (complete) | 225,154 (225,154) | 1 | 5.15 MiB | 0.87 s | 25.0 MiB | 30.2 MiB |
| P-01 | local | 0.5 KiB | ok (partial) | 8 (8) | 1 | 1.9 KiB | 0.001 s | 0.1 MiB | 0.0 MiB |
| P-02 | local | 963.6 KiB | ok (partial) | 19,733 (19,733) | 1 | 464.3 KiB | 0.02 s | 4.5 MiB | 3.2 MiB |
| P-03 | local | 3.79 MiB | ok (partial) | 79,518 (79,518) | 1 | 1.82 MiB | 0.097 s | 18.4 MiB | 24.9 MiB |
| P-04 | local | 15.60 MiB | **refused `LIMIT_EXCEEDED`** | 327,141 | - | 7.49 MiB if budgets raised | 0.43 s if raised | - | - |
| P-05 | local | 1454.44 MiB | **refused `LIMIT_EXCEEDED`** (over the 128 MiB snapshot ceiling) | - | - | - | - | - | - |

Coverage (fraction of the corpus that fits, excluding the one deliberately over-budget fixture): **0.944**
(repo examples 19/19, synthetic 8/8, real-world **4/4**, local **3/5**). A size-only survey of the 1,230 local `.3mf`
files under the maintainer's model folders found 126 (**10.2%**) larger than the 128 MiB snapshot ceiling (median 31.2
MiB, p90 130.1 MiB); no names or paths are recorded. Some projects also exceed the triangle budget: the local `P-04`
has 327,141 triangles and `P-05` is over the ceiling (30.5 million triangles).

### Budget decision (accepted)

The first run, at the originally specified 100,000 triangles, fit only 3 of the 4 real-world fixtures:
`R-prusa-seam-test` has 225,154 triangles. Evidence: raised runs took about 1.2 s, and the response is 5.15 MiB.
The 8 MiB whole-body wire cap is the real wall, not time or memory. Decision: **`MAX_RENDERED_TRIANGLES` and
`MAX_PARSED_TRIANGLES` are now 250,000** (`scene_limits.py`, the only place they live); the 300,000 decoded-vertex
budget already covered the fixture (112,569 vertices) and is unchanged, as are the 8 MiB cap and every other gate.
Models over the budget stay refused with a message that names the count and the limit, for example
"The model has 327,141 triangles; Studio draws at most 250,000." (for a 3MF the count is "at least N", reported the
moment the budget is passed). `P-04` is such a model; its scene would be about 7.5 MiB. Chunked or binary mesh
transfer, or decimation, for larger models is a documented follow-up and is not part of this PR. The 128 MiB source
ceiling is unchanged; 10.2% of the surveyed local `.3mf` files exceed it and are refused.

### Gates

| Gate | Result |
|---|---|
| Whole-body response cap enforced on the exact bytes | pass (tests; largest measured scene 5.15 MiB) |
| Node / triangle / vertex / depth budgets enforced during traversal | pass (tests follow the constants) |
| Cancel observed within 2 s | pass: max 0.005 s over 5 cancels on the 100k fixture (and a test on a 90k scene) |
| 50 start/cancel cycles: retained <= cap, temp snapshots 0, threads at baseline | pass: retained 8 of 8, snapshots 0, threads 1 to 1 |
| `WORKER_WEDGED` never occurs in the 50-cycle run | pass (its fail-closed path is tested separately) |
| Repo examples fit | pass (19/19) |
| Four real-world fixtures fit | pass (4/4) after the budget decision above |
| 100k-triangle fixture: parse+encode <= 10 s, extra peak memory <= 500 MB | pass: 0.358 s, 11.0 MiB (tracemalloc) / 6.1 MiB (RSS) |
| Targets (not gates): <= 3 s and <= 300 MB on the 100k fixture | met |

## Reproduce

```text
cd backend
py -3.13 -m pip install -e ".[test]"
py -3.13 -m pytest -q tests/test_scene_contract.py tests/test_scene_build.py tests/test_scene_hostile.py \
    tests/test_scene_jobs.py tests/test_scene_api.py tests/test_units_consumers.py
py -3.13 tools/scene_benchmark.py --out ../docs/testing/scene-contract/results.json \
    --real-world tests/fixtures/real-world [--local-root <folder> ...]
```

## Known limitations (carry into the PR description)

1. **Size-only consumers are not placement-aware.** DesignHealth, `bed_fit`, `validation_report` and the service
   bed-fit path answer "does the SIZE fit". A small object translated off the plate is not detected by them, and
   separated instances inflate the union. The scene's placement findings are the placement-aware source. Tracked
   as issue #91; the copy change qualifying those claims "by size" is the planned PR 3c.
2. **Repeated build items of one object id are mis-placed by `plate_placement.assess` on `main`**
   (`placement.py` keeps the last transform: a cube at X=500 and X=100 reports "inside"). Not fixed here (tracked as issue #93). The scene reports `REPEATED_INSTANCE_PLACEMENT_UNVERIFIED` and attaches no finding to those nodes.
3. **Plates.** Non-Bambu projects (Prusa, plain 3MF, STL) have no plate records (`PLATES_UNAVAILABLE`). Grid origins
   of multi-plate projects are unknown, so multi-plate projects get no placement findings.
4. **Stuck native calls** cannot be interrupted in-process (fail-closed `WORKER_WEDGED` backstop, no multiprocessing).
5. **STL** is decoded incrementally: a binary header count over the budget is refused before any triangle is
   decoded, decoding runs in batches of 5,000 triangles with the cancel hook between them, and ASCII is line-streamed
   with a running counter.
6. **Budgets are provisional.** Models over 250,000 triangles (or over the 128 MiB source ceiling) are refused with `LIMIT_EXCEEDED`; chunked/binary transfer or decimation is a follow-up.
7. `jsonschema` is a test-only extra (`pip install -e ".[test]"`); the engine never imports it.

## Deviations from the written plan

* **Node ids.** `b<ordinal>.c<i>.c<j>...` does not fit 128 characters at 64 levels, so beyond 128 the ancestry is
  replaced by a deterministic digest (`b3.~<32 hex>`); the 128-character contract is kept, not widened. The digest
  (128 bits of SHA-256) gives practical collision resistance, not mathematical uniqueness; the builder asserts
  uniqueness while building and fails with `INTERNAL` if two node ids ever collide.
* **Freeze order.** The JSON Schema was frozen first, but the golden scene and the fixture matrix were authored
  after the first draft of the traversal, not before it. The golden is written independently of the builder and
  the builder is held to it.
* **Size findings** are only emitted for nodes whose placement is known (plan v2: no bed-relative statement for
  unknown placement), single-plate, template bed, non-repeated instances.
* **No `request_validation.py` change was needed**; the route validation reuses its existing helpers from
  `scene_jobs.py`.

## What was not run

Linux (the POSIX branch of the pid-liveness check is exercised only by monkeypatch; the Linux CI job), the frozen sidecar, the packaged app, any
viewer, a real printer and any network.
