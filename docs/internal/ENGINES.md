# Local engine integrations

Evidence labels distinguish hand-written fixtures (`fixture-tested`), in-process API doubles and synthetic loopback HTTP stand-ins (`mock-service-tested`), a real local engine (`local-service-exercised`), and hardware (`hardware-verified`). The Lumina fixtures in this work are documentation-derived and hand-written to the published API 2.0 source shapes, not captures. No real Lumina process or printer was exercised.

## Lumina Layers

The adapter accepts a user-supplied HTTP(S) URL only when `foundation.netguard.require_local_url` accepts it. Requests use `foundation.netguard.local_request`, which bounds response and request sizes and deadlines, checks the resolved address, and refuses redirects. The adapter reads `/openapi.json` and accepts only the research-observed FastAPI API version `2.0`; it checks `/api/health` before allowing POST and treats the health JSON as opaque because its response schema is not present in the research. The published preview route is `POST /api/convert/preview` with multipart `image` and `lut_name` fields and documented form options. Its response provides `session_id`, status and `/api/files/{file_id}` URLs. A file is fetched only by a validated file ID; SHA-256 and byte size are computed from returned bytes, while kind is mapped from the returned `Content-Type` header.

The saved research does not publish a progress route or response shape, nor a cancel route or request shape. Those methods return `progress_unknown` and `cancel_unknown`; no route is inferred. API error response shapes also were not established as a stable contract, so failures are returned as fixed adapter error codes without echoing service body text. The generator's internally produced `threemf_disk_path` is not treated as a Studio file path.

## Generic CLI runner

The configured executable path and argument template are fixed for a runner instance. The runner creates a fresh Studio-owned job directory, stages inputs as copies, sets that directory as cwd, and invokes argv directly with `shell=False`; `.bat` and `.cmd` entry points are refused. Templates accept only `{job_dir}`, `{output_dir}` and `{input}` with one-pass substitution. The timeout and combined stdout/stderr cap are bounded. Timeout, cancellation, and output refusals stop the process tree started by the runner: a private POSIX session/process group or a Windows kill-on-close Job Object. Failed runs remove their job directory; successful results keep it until the caller reads artifacts and calls `cleanup(result)`. Output scanning is capped at 10,000 entries and 32 directory levels, refuses scan errors and symlinks/junctions/reparse points, and artifact bytes are capped by the configured limit. Output artifacts include relative name, SHA-256, byte size and a known kind or `unknown`.

A configured executable whose basename (case-insensitive, with or without `.exe`) is `orca`, `snapmaker-orca`, `bambu`, `prusa`, `slic3r`, `superslicer`, `cura`, or `kiri`, or contains `slicer`, is refused with `executable_policy_refused`. This name-based policy is a safety rail, not a sandbox or a guarantee. Admission is also by identity: the runner starts only `sys.executable` (the interpreter running Studio) or an executable whose SHA-256 the caller pinned with `approved_sha256`; anything else is refused with `executable_not_approved`. A renamed copy of a slicer therefore fails unless a caller pins its exact bytes, and the name rail still refuses slicer-named files even when pinned. A caller that pins a slicer binary under a neutral name defeats the rail; callers must not. The hash is read at construction, so a swap afterwards is not detected, and this is not a sandbox. The output-root link check remains check-then-scan and can race a still-running writer.

Evidence for this slice: `fixture-tested` and `mock-service-tested`. No local service was exercised.

## Review follow-up dispositions

F1-F5 are addressed in the bounded LUMINA1 repair. F6 is partially addressed: process-tree termination, failure cleanup, and executable-name refusal are covered here; environment isolation, staged-input size limits, Windows reserved output names, wait-error reporting, and a stronger output-root race boundary remain deferred. F7 remains deferred: write-origin registration is process-global and needs a scoped ownership design. F8's kind-source statement is corrected above; streaming large artifact downloads remains deferred. F9 is partially addressed: process-tree cancellation and explicit successful-job cleanup are provided; pre-health identity refusal and focused direct `cancel(pid)` lifecycle coverage remain deferred. F10 remains deferred: runtime discovery evidence still has a test-provenance default and should move to test/docs metadata.

## Known limits (review follow-ups, not closed)
- The output-root link check is check-then-scan; a descendant that keeps running can race it.
- Process-tree stop is best effort within a bounded wait; inherited pipe-reader threads can outlive the immediate return if the operating system does not close descendant handles promptly.
- Executable admission is a name rail plus a caller-pinned SHA-256 (or `sys.executable`). It is checked once at construction, so a swap after that is not detected, and it is not an execution sandbox. Studio still does not slice.
- Successful job directories remain until callers finish reading artifacts and call `cleanup(result)`.
- Lifecycle tests launch `sys.executable`; under a Windows venv launcher a job object could mask descendant survival.

## Wired routes and screen (Engines track)

`backend/snapstudio_api/routes_engines.py` registers three POST routes through `ext_routes` under the existing `/engines` prefix; `server.py` and `ext_routes.py` are unchanged. The desktop screen is `desktop/src/routes/ext/lumina.{route.tsx,meta.ts}` (path `/lumina`, Studio+ group, shown in Advanced mode) with its view in `desktop/src/lib/lumina/`.

- `POST /engines/lumina/formats {}` returns the explicit supported list: `3mf`, `png`, `glb`, each with a one-line meaning and `evidence: mock-service-tested`. A format is chosen by the user and never inferred.
- `POST /engines/lumina/status {service_url}` runs discovery and the identity check through `LuminaClient`. `ok` means only that the service answered Studio's checks; anything else is `unknown` with a fixed explanation. No response body is echoed. Loopback and LAN addresses only (netguard); a non-local address is a 422 refusal.
- `POST /engines/lumina/generate {service_url, image_path, lut_name, format, out_dir?}` refuses an unlisted format before any request, names the list, and otherwise submits the image through the adapter. The service's preview and GLB locators are fetched only through validated `/api/files/{id}` ids, and the artifact is kept only if its kind (from the returned `Content-Type`) equals the chosen format; otherwise nothing is saved and the kinds returned are named. The artifact is written as a NEW file (`lumina-<sha12>.<kind>`, exclusive create, never replacing) in `<data dir>/lumina-output` or a local `out_dir` the user chose, which must not be the image's own folder. The response carries only the file name, SHA-256, size, kind, `generated_by` ("a user-configured local Lumina-compatible service (not verified)"), a plain `location_label`, and an advisory that Studio did not watch the file being made. No full path appears in any response. Progress and cancel are reported as `unknown`; no route is invented for them.

Image-path guard: this branch has no shared `localpath` module (it lives in #140), so `snapstudio_core/engines/local_input.py` refuses UNC and device paths in any slash style, links whose target reaches a network location, non-regular files and files over the adapter's input cap (128 MiB). It is best-effort, not a sandbox: check and open are separate steps. #140's shared guard should replace this helper once both land. A mapped network drive letter looks local and is allowed.

Evidence: `mock-service-tested` against `LuminaHttpMock` (a synthetic loopback HTTP service in `backend/tests/mocks/lumina_server.py`), with the real Studio backend process, vite dev UI and headless Edge screenshots in `docs/internal/screens/lumina/`. No real Lumina installation or process was exercised, and no real-Lumina compatibility is claimed.

## Still not done

F6-F10 above remain deferred as listed. Also: no streaming for large artifact downloads; generation is one synchronous request bounded by the adapter's timeout, so a slow service surfaces as a plain refusal; the UI has no output-folder field (the route accepts `out_dir`); `/api/files` kind mapping knows only 3MF, GLB and PNG content types, so anything else is `unknown` and is not saved.

Usability label: experimental, mock-service-tested and fixture-tested, with one real loopback transport-boundary test. No real Lumina installation or process was exercised.
