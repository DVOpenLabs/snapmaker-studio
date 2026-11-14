# Local engine integrations

Evidence labels distinguish hand-written fixtures (`fixture-tested`), in-process API doubles (`mock-service-tested`), a real local engine (`local-service-exercised`), and hardware (`hardware-verified`). The Lumina fixtures in this work are documentation-derived and hand-written to the published API 2.0 source shapes, not captures. No real Lumina process or printer was exercised.

## Lumina Layers

The adapter accepts a user-supplied HTTP(S) URL only when `foundation.netguard.require_local_url` accepts it. Requests use `foundation.netguard.local_request`, which bounds response and request sizes and deadlines, checks the resolved address, and refuses redirects. The adapter reads `/openapi.json` and accepts only the research-observed FastAPI API version `2.0`; it checks `/api/health` before allowing POST and treats the health JSON as opaque because its response schema is not present in the research. The published preview route is `POST /api/convert/preview` with multipart `image` and `lut_name` fields and documented form options. Its response provides `session_id`, status and `/api/files/{file_id}` URLs. A file is fetched only by a validated file ID; SHA-256 and byte size are computed from returned bytes, while kind is mapped from the returned `Content-Type` header.

The saved research does not publish a progress route or response shape, nor a cancel route or request shape. Those methods return `progress_unknown` and `cancel_unknown`; no route is inferred. API error response shapes also were not established as a stable contract, so failures are returned as fixed adapter error codes without echoing service body text. The generator's internally produced `threemf_disk_path` is not treated as a Studio file path.

## Generic CLI runner

The configured executable path and argument template are fixed for a runner instance. The runner creates a fresh Studio-owned job directory, stages inputs as copies, sets that directory as cwd, and invokes argv directly with `shell=False`; `.bat` and `.cmd` entry points are refused. Templates accept only `{job_dir}`, `{output_dir}` and `{input}` with one-pass substitution. The timeout and combined stdout/stderr cap are bounded; cancellation terminates only the process handle started by this runner and does not wait for inherited pipes to reach EOF. Output scanning is capped at 10,000 entries and 32 directory levels, refuses scan errors and symlinks/junctions/reparse points, and artifact bytes are capped by the configured limit. Output artifacts include relative name, SHA-256, byte size and a known kind or `unknown`.

Evidence for this slice: `fixture-tested` and `mock-service-tested`. No local service was exercised.

## Review follow-up dispositions

F1-F5 are addressed in the bounded LUMINA1 repair. F6 remains deferred: environment isolation, staged-input size limits, Windows reserved output names, job-directory cleanup on pre-launch refusal and wait-error reporting need a separate review. F7 remains deferred: write-origin registration is process-global and needs a scoped ownership design. F8's kind-source statement is corrected above; streaming large artifact downloads remains deferred. F9 remains deferred: direct `cancel(pid)`, pre-health identity refusal and temporary-directory lifecycle need focused tests. F10 remains deferred: runtime discovery evidence still has a test-provenance default and should move to test/docs metadata.

## Known limits (review follow-ups, not closed)
- Timeout and cancel stop only the direct child. There is no job object or process group, so a descendant the engine started can keep running and keep writing into its job directory after the runner returns an error; each such run also leaves two pipe handles and reader threads until the descendant exits. Planned: a kill-on-close Windows Job Object / POSIX process group for processes this runner started.
- The output-root link check is check-then-scan; a descendant that keeps running can race it.
- Job directories are not removed after a refused or failed run.
- The runner can launch any configured executable. Before it is wired to a caller it needs a policy that keeps it from running a slicer (Studio does not slice).
- Lifecycle tests launch `sys.executable`; under a Windows venv launcher a job object could mask descendant survival.

Usability label: experimental library, fixture-tested and mock-service-tested, with one real loopback transport-boundary test. Not exercised against a real Lumina or engine, not wired to any caller or UI.
