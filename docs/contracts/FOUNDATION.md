# Studio+ foundation contracts

This is the single normative text for the foundation layer (`backend/snapstudio_core/foundation/`,
`backend/snapstudio_core/adapters/base.py` and `registry.py`, `backend/snapstudio_api/ext_routes.py`).
It folds in every amendment made during planning; implementers do not need to reconstruct an
override order. Where an older plan section and this text differ, this text is correct. Evidence label for
everything below: `fixture-tested`.

Desktop mirrors and the desktop seam are specified separately in `DESKTOP_EXT.md`.

## 1. Rules that bind every track

1. No printer contact beyond guarded reads, no print/heat/motion, no cloud upload, no release. Originals are never modified.
2. Unknown stays unknown. Claims are computed, never asserted. No hardware claim from a mock or fixture.
3. Every outbound network call goes through `foundation.netguard.local_request`. Nothing else in new code imports `socket`, `ssl`, `http.client`, `urllib.request`, `urllib3` or `requests`.
4. Credentials (`X-Api-Key`, `Authorization`) live in process memory for the session. They are never persisted, logged, echoed in an error or response, or written to a job, checkpoint or recovery file.
5. Subprocess execution exists only in `engines/cli_runner.py`. Imported manifests, passports and project files never choose an executable or its arguments.
6. Foundation code never edits legacy modules (`fidelity`, `moonraker`, `material_providers`, `material_plan`, `preflight`, `preserve`, `gcode`, `library`, `freshness`, `paths`, and the others listed in the plan). It calls them read-only, or re-implements the small piece it needs.
7. Copy guards: no placeholder-status wording (the banned list lives in `lib/copy.test.ts`), "Printer Doctor" is not a name, and prepare-copy files avoid the banned status word. Track files do not use the words for simultaneous extrusion, guarantees, or percentage-success claims.
8. Fixtures live under `fixtures/<system>/<release-or-commit>/<case>.json` with a `PROVENANCE.md` that says whether the case is a documented example, synthesised from a documented schema, or a real capture.

## 2. Documents

Documents are pure data: `to_dict` / `from_dict`, a `schema_version` on every document, JSON-serialisable.
Hashing, persistence, transport and execution live in service modules (`artifacts`, `store`, `netguard`, `jobs`).

### 2.1 Decoding (`decode.py`)

External data is decoded, never trusted. `Decoded{schema_version, value|None, diagnostics:[{code, field, severity}], valid_for_evaluation, raw}`.
- Severity is `error`, `warning` or `note`. `value` is None whenever any error diagnostic exists.
- An unknown or missing `schema_version` gives `value=None`, `raw` preserved opaquely, `valid_for_evaluation=False`.
- Decoding malformed JSON, wrong types or unknown versions never raises. A wrong Python type passed by our own code still raises (programming error).
- Finite-number checks reject bool, NaN and infinity, and integers too large for a float (`OverflowError` is handled; `decode_document` never raises on external data).
- Every evaluation result carries `inputs_revision` (built by `decode.revision_envelope`, serialised with the result): `assignability(...)["inputs_revision"]` lists the topology `snapshot_id` and content hash, `mapping_revision`, the requested slots and the constraints; `capabilities.evaluate(...)` returns a list whose `.inputs_revision` lists the capability-set hash, the requirements and the scope, and `evaluation_to_document` serialises both. Callers pass `revisions={"artifact_hashes": [...], "observation_revision": ..., "calibration_revision": ...}` for the dependencies they have. Caller revisions and extras cannot replace computed or base fields; collisions raise `ValueError`. The envelope revision hashes all listed fields, so a changed dependency changes it. Any change invalidates dependent conclusions. A persisted conclusion is historical evidence, never reusable approval.

### 2.2 Topology (`topology.py`)

- IDs are typed and namespaced: `head:<n>`, `unit:<kind>:<instance>`, `lane:<unit-id>:<n>`, `slot:<n>`. Internal indices are 0-based; `display_index = index + 1`.
- Adapters normalise wire bases (G-code `T` is 0-based, Orca filament indices are 1-based, the multiACE wire index is 0-based) and record the `index_base_source` diagnostic.
- `PhysicalToolhead`, `FeederUnit` (`stock|multiace|afc|bmcu|sidecar|other`), `Lane` (`reachable_heads` None means unknown, `[]` means known unreachable), `LogicalSlot`, `ProjectSlotRequirement` and `SlotBinding` are separate things. Project requirements are not setup bindings.
- `Topology{snapshot_id, observed_at, received_at, mapping_revision, heads, units, slots, bindings, complete, evidence, diagnostics}`.
- `validate(topology)` names duplicate ids, dangling references, mixed index bases, a slot bound to two lanes, and a lane that references an unknown head.
- `counts(topology)` is never derived from `len(slots)` and never defaults to 4 or 16. Unknown head count is None.
- `assignability(topology, requested, constraints)` answers material-to-head assignability: `assignable` is True, False or None, with a `bound` and a `per_requirement` result (`ok|contended|unreachable|unknown`). Unknown reach or unknown constraints give None or a bound, never an exact count.

### 2.3 Materials (`materials.py`)

- `SpoolRef{provider_instance_id, provider_spool_id}`: equality needs both. Only an explicit `SpoolAlias` makes two providers' spools one physical spool. Colour never merges spools.
- `MaterialFact{field, value, provenance, observation_id}` with provenance `rfid|user|provider|project|derived|unknown`.
- `reconcile(facts, observations, now) -> MaterialView`, per field:
  1. discard observations whose freshness is UNUSABLE;
  2. a fact with unknown `observed_at` loses to any known-time usable fact; otherwise the newest `observed_at` wins; a STALE fact never beats a FRESH or AGEING one regardless of provenance;
  3. a tie is broken by rank rfid > user > provider > project > derived > unknown;
  4. losing facts with a different value are kept in `conflicts`;
  5. provenance is never promoted;
  6. a provider that supplies only weight never inherits identity fields from another provider's row.

### 2.4 Observations and freshness (`observations.py`)

- `Observation{observation_id, subject, field, value, source{provider_instance_id, kind, source_version, snapshot_id}, observed_at, received_at, ttl_s, ageing_ok, historical, source_kind, history_uncertain}`.
- `observed_at` is when the fact was true at the source; `received_at` is when Studio received it. They are never merged.
- `source_kind` is `live_query` or `cached_record`. For a live query, `observed_at` is the provider's own timestamp, otherwise the receipt time on every successful read (diagnostic `observed_at_is_receipt_time`). For a cached record, re-polling an unchanged `(subject, field, value, revision)` keeps the first `observed_at`; `received_at` still advances. Tracker eviction never renews a figure: an evicted key (kept as a digest) that is polled again has an unknown `observed_at` (diagnostic `observed_at_lost_after_eviction`). Eviction evidence is an exact digest cache and then two rotating digest-filter generations. The oldest generation is dropped on rotation, so filter false positives do not accumulate and a changed value or revision can receive a fresh timestamp. An unchanged key not seen for longer than that retention is treated as new, because no record of it remains.
- History uncertainty: once a rotation has dropped a generation that held evictions, the tracker has really lost history and cannot tell an unchanged forgotten record from one it never saw. From then on a cached record observed without a provider timestamp and not already known to the tracker (a first sighting, or a changed value or revision) gets `observed_at` = receipt time, so it displays FRESH and a change still becomes fresh, but it carries `history_uncertain=true` (diagnostic `observed_at_history_uncertain`) and is never `usable_for_loadout`. The mark is sticky: re-polling the same cached value is not new provider evidence, so every later sighting of that key within retention stays `history_uncertain` (freshness reason: "History is uncertain; no new source evidence yet."); it clears only when the key leaves the tracker. Only a provider timestamp establishes it. Records first seen before any loss are unaffected. A changed value after such a loss is therefore FRESH for display but not loadout-eligible until it is provider-timed.
- Freshness order: `ttl_s` not a finite number above zero (or a bool) is a construction diagnostic and state UNUSABLE; `observed_at` missing is UNKNOWN; unparseable is UNUSABLE; a time in the future beyond 300 s of skew is UNUSABLE, within skew the age is clamped to 0; age up to ttl/2 is FRESH, up to ttl is AGEING, above is STALE.
- `usable_for_loadout` is True only for FRESH, or AGEING when `ageing_ok`. `historical=True` and `history_uncertain=True` force False regardless of age. Restored observations are historical.

### 2.5 Artifacts and lineage (`artifacts.py`)

- `ArtifactRef{artifact_id = "sha256:<hex>:<size>", role, bytes{sha256,size_bytes}, name, locator, created_at}`; roles `original|prepared|generated|sliced|image|settings|lut_ref|calibration`.
- `Derivation{derivation_id, output, inputs[], producer, witness, declared_by, created_at}`. `witness=local` only when this Studio process produced or observed the output; anything imported (passport, manifest) is `declared`. A declared parent whose bytes exist locally with a different hash is flagged `declared_mismatch` and never promoted.
- `snapshot(path, role, ...)` copies files up to 512 MiB into the private snapshot directory, hashes the copy, and all later analysis reads the copy. Larger files get hash, size and mtime only, with the `not_snapshotted` diagnostic; `same_bytes` must pass immediately before each analysis.
- `same_bytes(ref, path)` returns `same|changed|missing|unreadable|unverified`. Size-equal replacement is detected by hash.
- Aggregate snapshot quota is 4 GiB. When it would be exceeded, only unpinned snapshots older than the grace period (24 h) are evicted, oldest first; if that is not enough the new snapshot is refused with `snapshot_quota_exceeded` and nothing referenced is deleted.
- Pins: `artifacts.pin(artifact_id, holder_kind, holder_id, *, data_dir=None)` / `unpin` are the canonical calls and PERSIST through the store (revision-checked read-modify-write of the `snapshot_pins` document, under that document's cross-process writer lock). `pin_in_memory` / `unpin_in_memory` are process-local helpers that a sweep never sees. Each track pins when it creates a reference (checkpoint, passport, assembly, calibration record, active workspace). `sweep_snapshots_persisted`, `sweep_snapshots` and quota eviction ALWAYS decide from the CURRENT persisted registry, read while holding the same writer lock across the read and the deletions, so a pin cannot land between them. A registry passed in (`registry=`) is additive only: it is unioned with the persisted one and can never reduce protection, so a stale empty registry cannot cause a pinned snapshot to be deleted. Sweep takes the admission lock then the pin lock (the order `snapshot` uses), so it cannot delete a copy a snapshot just renewed; it also removes `.<uuid>.tmp` partial copies older than the grace period. They delete only unpinned snapshots past the grace period and do nothing at all if either registry is unreadable. Quota measurement fails closed: if the snapshot directory cannot be scanned, admission is refused (`snapshot_dir_unavailable`).
- Copy and quota admission: `snapshot` runs quota admission and the copy under a cross-process lock (`<snapshot_dir>/.admission`, not counted against the quota), enforces `max_copy_bytes` and the remaining quota WHILE copying (a source that grows past the copy cap is aborted, the partial removed, and hashed in place with `not_snapshotted`), so concurrent snapshots cannot exceed the 4 GiB quota.
- `job_identity.check` is not called with role `generated`; passports and recovery use `same_bytes`.

### 2.6 Recipes and capabilities

- `VirtualRecipe` is always `simulated=True`. `validate` reports missing components, cycles, duplicates, negative or non-finite ratios; an unknown `ratio_kind` is preserved and never read as consumption. A ratio that is present but not a finite number (NaN, infinity, bool, text, oversized integer) is kept as `ratio_invalid=True` with `ratio=None`; `assess` reports `non_finite_ratio` and withdraws execution approval. Unsupported definitions are kept with `execution_supported=False`, never dropped. `physical_inputs` returns referenced inputs, not a nozzle count.
- `Capability{key, state: supported|unsupported|unknown|conflicting, scope, evidence}`. A missing key is unknown. `evaluate(requirements, capability_set)` returns `satisfied|unmet|unknown` per requirement; conflicting evidence is unknown with both pieces of evidence; alternatives may satisfy.

## 3. Persistence (`store.py`)

- The storage root comes only from `paths.data_dir`; store names and schemas are code constants, never request content. `library.py` and its `user_version` are untouched.
- `open_store(name, migrations)`: one connection per call, `isolation_level=None`, explicit `BEGIN IMMEDIATE` per migration with `user_version` set in the same transaction, never `executescript`, `busy_timeout=5000`. A `user_version` newer than the code raises `StoreVersionError` with no write. A failed migration rolls back and leaves prior schema and rows.
- `read_json` / `write_json(name, doc, expected_revision=...)`: a thread lock in front of an OS advisory lock on `<name>.json.lock` (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows), retried with backoff until `wait_s`, then `StoreLockError`. A lock file that cannot be opened also raises `StoreLockError` (callers such as `snapshot` report `snapshot_dir_unavailable`). On Windows the lock is explicitly unlocked before the descriptor closes. The OS releases the lock when the holder exits or is killed, so there is no staleness protocol, no maximum age (`max_age_s` / `lock_max_age_s` are accepted and ignored) and no reclamation or tombstone code. The lock file is never unlinked by anyone and may persist; it holds the holder's pid, token and time for diagnostics only. Limit: local filesystems only, advisory locking on network shares is not guaranteed. `document_lock(name)` exposes the same lock for dependent actions (use `write_json(..., lock_held=True)` inside it; it is not re-entrant). `read_json(rename_damaged=True)` takes the lock to rename a damaged file: a thread that already holds `document_lock(name)` should pass `rename_damaged=False`; if it does not, the rename is skipped without waiting. A revision mismatch raises `RevisionConflict`. Writes use a unique temp file in the same directory, `flush` + `fsync`, then `os.replace` with up to 5 retries on `PermissionError`; on final failure the previous file stays. Maximum 16 MiB.
- A file that fails JSON decoding is renamed `<name>.damaged-<timestamp>`, only while holding the writer lock and only if the bytes still fail to decode and are unchanged (a read that cannot get the lock leaves the file alone). A file with a newer `schema_version` is not renamed: `StoreVersionError`, bytes preserved, read-only inspection allowed.
- The lock protects against two Studio sidecars, not against external tools editing the files.

## 4. Network guard (`netguard.py`)

`netguard` never uses the legacy unbounded resolver (`material_providers._host_is_local` or `validate_provider_url`'s resolution). It re-implements the syntax rules (scheme, no userinfo, hostname pattern, length) on the origin part only, with a parity test against the legacy validator for IP literals. `moonraker.validate_host` is a syntax check, never a locality check.

- `require_local_url(url)`: http/https only. Local means loopback, private, `100.64.0.0/10`, IPv6 site-local, and `.local`/`.lan`/`.home`/`.internal`/`.home.arpa` names. Refused: public addresses, link-local (`169.254/16`, `fe80::/10`), 6to4, Teredo, NAT64. Name resolution happens only in netguard's bounded pool (4 threads, no queue; a saturated pool fails fast as `unavailable`; a stuck resolver cannot outlive the deadline).
- `local_request(method, url, *, headers=None, body=None, timeout=10.0, max_bytes=4 MiB, max_request_bytes=None, stream_to=None, write_ok=False, secret_headers=(), origin=None, resolver=None, resolver_pool=None)`. The deadline parameter is named `timeout` (seconds); `origin` is the configured origin that credential headers are tied to; `max_request_bytes` caps the request body (default: `max_bytes`); `resolver` / `resolver_pool` are test and bounded-pool seams; `stream_to` is an existing DIRECTORY, the body goes to a new temporary file there and `Response.path` names it. Credential values sent, including the token portion of Bearer and Basic Authorization values, are redacted from the response reason, header values and the body, including streamed bodies (a rolling overlap catches a value split across read boundaries). Every resolved address is checked at connect time and only a vetted address is dialled. No proxy is consulted. TLS verification uses the default context (self-signed local HTTPS is therefore refused; this is a disclosed limitation). Every redirect is refused. Headers and body are capped; `stream_to` has its own explicit cap. One deadline covers resolve, connect, headers and body and closes the live socket.
- Credential headers are attached only when `origin` equals `scheme://host:port` of the request after canonicalising default ports. Errors are redacted: no header values, no credentials, no raw body, no URL.
- Method policy: GET and HEAD by default. Any other method needs `write_ok=True` and a target origin that was registered through `confirm_write_origin` in the same session (Lumina identity confirmed by GET `/api/health`). `write_ok=True` appears only under `engines/`.
- Path policy, applied to every host and method after normalisation (percent-decode once, collapse `//` and dot segments, drop query and fragment, lowercase, match on segment boundaries, refuse residual encoded traversal): denied with all sub-paths are `/printer/print`, `/printer/gcode/script`, `/printer/emergency_stop`, `/printer/firmware_restart`, `/printer/restart`, `/machine`, `/server/files/upload`, `/api/printer`, `/api/job`. The only exception is `GET /machine/system_info`. For non-GET methods `/api/files/local`, `/api/files/sdcard`, `/server/jsonrpc` and `/server/job_queue` are also refused.
- Host adapters extract from `/machine/system_info` only `product_info.nozzle_diameter` and `sd_info.total_bytes`; device name, serial, MAC and IP are never surfaced.

## 5. Jobs (`jobs.py`)

- States: `queued | running | cancel_requested | succeeded | failed | cancelled | interrupted`. `queued` goes to `running` or `cancelled`. `running` goes to `cancel_requested`, `succeeded` or `failed`. `cancel_requested` goes to `cancelled`, `failed`, or `succeeded` when the work finished before the stop was acknowledged; that late result is marked `late=True` and is never published (temp files deleted).
- `JobManager(max_workers=2, max_queue=8, result_ttl_s=600, max_temp_bytes=1 GiB)`. A full queue is refused explicitly. Per-kind slot limit is 1. `max_queue` bounds jobs unable to launch now, including jobs awaiting persistence; launch slots are reserved during persistence so concurrent starts cannot bypass the global worker or waiting-job limit. A reservation holds its slot and kind against every unreserved waiter until its record is persisted and it launches. `start(kind, inputs, session_id, idempotency_key)` with the same `(session_id, key)` returns the existing job; inputs are frozen at start with `inputs_revision`.
- Thread workers are cooperative: a cancel token, with all I/O bounded by netguard deadlines. A thread that ignores cancellation keeps its slot and is reported `wedged`; a wedged worker needs a sidecar restart, and job status says so. Subprocess workers are killed as a process tree by their owner (`engines/cli_runner.py`); `jobs.py` only calls the worker's `cancel()` / `kill()` callbacks and never touches process handles.
- A cancelled or timed-out worker keeps its slot until it has actually stopped. On process start, persisted job records are marked `interrupted`; nothing is replayed.
- Ownership: the sidecar uses the one process-wide `jobs.default_manager()`. Every manager has an instance id, stamps its records with it (`owner`), and keeps its temp files in its own subdirectory of `job-tmp`. Restore adopts and interrupts only records whose owner is not another manager still open in this process; a closing manager stays live until its workers stop. Release from the live set is the last persistence step: under the persist lock the manager writes a fresh snapshot of its current records and only then leaves the live set, so a replacement manager can never adopt a record as interrupted while the owner's terminal save is still pending. It deletes only the temp directories of the jobs it restored. Saving merges: records of other owners are kept, never overwritten. (A manager in a different OS process is not detected; the sidecar is one process.)

## 6. Route seam (`snapstudio_api/ext_routes.py`)

- `server.py` carries exactly two edits: the import line `from . import ext_routes` and one `elif ext_routes.dispatch(self, self.path, data): pass` branch before the final 404. A test diffs `server.py` against the baseline commit and fails on anything else.
- The registry maps path to handler. A handler is `fn(data: dict) -> (status, body)` and returns within 5 s; long work goes through `jobs.py`. `register` / `@route` refuse a path outside the nine prefixes `/setups /creative /engines /calibration /assemblies /variants /passport /monitoring /recovery`, a path outside its own track's prefix (decided by the handler's module name; `routes_recovery` owns `/monitoring` and `/recovery`), a handler whose module is not one of the track modules (test modules are exempt), a duplicate, and a collision with any `self.path` literal in `server.py`.
- `dispatch(handler, path, data)`: an unknown path sends nothing and returns False. A non-object body is `400 {"error":"invalid","message"}`.
- Error map (complete): `request_validation.ValidationError` is 400 `{"error":"invalid","message":<its message>}` and is checked before any `ValueError`. `SnapStudioError` is 422 `{"error":"refusal","message":<its message>}`. `NetguardRefused`, `RevisionConflict` and `StoreVersionError` are 422 `{"error":"refusal","message":<fixed redacted text>}`. A plain `ValueError` and every other exception are logged server-side (class and call sites only) and answered 500 `{"error":"internal","message":"Internal error."}`. The body always has `message`, which is what `api.ts` `post()` reads.
- Route handlers convert `InvalidHost` and `require_local_url` failures on user input into `ValidationError` (400). `NetguardRefused` at connect time, on a redirect or for a resolved public address stays 422.
- Loading: `load_all()` runs at import of `ext_routes` and contains one literal `try: from . import routes_<track> except ImportError` block per module (`routes_setups`, `routes_creative`, `routes_engines`, `routes_calibration`, `routes_assemblies`, `routes_variants`, `routes_passport`, `routes_recovery`). Presence is decided with `importlib.util.find_spec` (safe in the frozen sidecar): an absent module is skipped, a present module that fails to import re-raises. It then calls `adapters.registry.discover()` with the same rule for the `accessory` and `host` packages.

## 7. Adapters (`snapstudio_core/adapters`)

- `AdapterInfo{id, kind: host|accessory, versions_supported, ttl_s}`. `ttl_s` is mandatory (finite, above zero); constructing an adapter without it fails.
- `Adapter.parse(payload, *, received_at, source_version) -> AdapterResult{topology, observations, material_facts, unknowns, diagnostics, errors, source_version}`; `to_decoded()` gives the `Decoded` form. Subclasses implement `_parse` and build observations through `Adapter.observe`, which applies the declared `ttl_s` and the `observed_at` rules of 2.4.
- `parse` never raises. Malformed JSON, a non-object payload, or a defect inside the parser yields no documents and an `errors` entry (the exception text is dropped). A `source_version` the adapter does not list yields every field unknown (`unknowns == ["all"]`) plus `unknown_source_version`; nothing is guessed.
- Adapters are network-free. The host layer fetches through netguard and hands the payload over.
- `registry.register` refuses a duplicate id; `discover()` follows the same skip-absent / raise-broken rule as route loading.

## 8. Guard tests

The AST checks in `backend/tests/test_foundation_guards.py` (`scan_source`) implement G1, G1b, G1c, G3 and G5. They scan every module under `snapstudio_core/{adapters,engines,creative,calibration,assemblies,variants,passport,monitoring_context,workspace_recovery,foundation}` plus `snapstudio_api/routes_*.py`, `ext_routes.py`, `setup_view.py` and `u1convert/passport_cli.py` (absent ones are skipped). Each implemented rule has a negative self-test that fails on a synthetic violating source. G2 credential echo checks are owned by the netguard redaction tests; G4 storage checks are owned by the desktop phases.

- G1 (allowlist): only `foundation/netguard.py` imports or accesses `socket`, `ssl`, `http.client`, `urllib.request`, `urllib3` or `requests` (including module aliases and literal dynamic imports).
- G1c: write permission passed to `local_request` appears only under `snapstudio_core/engines/`; indirect values and expanded keyword arguments are covered.
- G1b: new modules import from or use `snapstudio_core.moonraker` only `toolhead_objects`, `validate_host`, `InvalidHost`, `DEFAULT_PORT`, `SCHEMA_VERSION`, `EXTENDED_MARKERS`, `CONTROL_PATH` (AST test). `emergency_stop`, `upload_gcode`, `confirm_upload`, `_post`, `_get`, `job_queue`, `probe`, `discover`, pause/resume/cancel/start, status and history are forbidden.
- G2: a sentinel credential appears in no response body, log line, job record, checkpoint or recovery file.
- G3: no scanned module reads `slot_count` or `len(nozzles)` (a head count comes from the topology).
- G4 (desktop): no storage write of a field named `apiKey`, `api_key` or `token`.
- G5: subprocess calls, `os.system`, `os.spawn*`, `os.exec*`, `os.posix_spawn*`, `os.fork*`, `pty.spawn`, `multiprocessing`, `loop.subprocess_exec/shell`, `getattr(os, "system")`, `os.startfile`, `os.popen`, `Popen`, and `asyncio.create_subprocess_*` / `asyncio.open_connection` appear only in `engines/cli_runner.py`, including aliased imports.
- Data-dir isolation: an autouse fixture points `SNAPSTUDIO_DATA_DIR`, `LOCALAPPDATA`, `XDG_DATA_HOME` and `HOME` at a temporary directory, and a tripwire fails any test that changes the real data directory.
- Test basenames are globally unique and every test directory has `__init__.py`.

## 9. Evidence labels

`fixture-tested` (synthetic or documentation-derived fixtures), `mock-service-tested` (in-process mock HTTP service), `local-service-exercised` (a real local service on the maintainer's LAN, dated and anonymised), `hardware-verified` (a real U1; none expected). Every `PROVENANCE.md` that is not a capture says "documentation-derived fixture". Interface copy states a capability only at the label achieved, and calibration, cost, allocation and compatibility verdicts carry "advisory" wording.

## 10. Known limitations

1. The legacy core (`preflight._toolheads_vs_filaments`, `firmware_caps.interpret`, `preserve.prepare_preserved_values` four-padding, `gcode.read_facts` with `slot_count=len(nozzles)`) is not topology-aware. New pages show a limitation notice, and legacy preparation is not treated as validated for more than four logical materials, a non-four-head printer, or a non-identity mapping.
2. Accessory and host fixtures are documentation-derived. No multiACE, AFC, BMCU, Sidecar, OctoPrint or Lumina service and no live printer is exercised.
3. Link-local addresses (including IPv6 `fe80::/10`) are refused. A host reachable only that way is unsupported and shown as refused, not unreachable.
4. Self-signed local HTTPS is refused because TLS verification is not relaxed.
5. Files above 512 MiB are not snapshotted. Bytes are re-verified immediately before use, but a race between verification and read remains possible.
6. Job persistence is in-process. After a crash, queue state is lost except what a track persists itself; restoration marks interrupted and never replays.
7. A wedged job needs a sidecar restart.
8. Monitoring filename association is `unverified`; Studio does not confirm that the printer runs the local artifact.
9. Tool-change counts come from a bounded G-code scan; partial files give unknown.
10. Optical and calibration values are nominal, not measured.
11. OctoPrint Application Keys request flow (a server write) is excluded; users paste an existing key.
12. The cross-process store lock does not protect against external tools editing the files, and relies on OS advisory locking, which is only guaranteed on local filesystems.
