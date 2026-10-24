# Security model & hardening status

Snapmaker Studio is a local-first desktop app: a Tauri (Rust) shell + a webview UI
talking to a Python engine over **loopback HTTP only** (`127.0.0.1`). There is no
account, no cloud and no telemetry, and nothing leaves the user's local network.

The one outbound transfer Studio makes is Printer Hub sending a sliced job to a
printer the user gave it the address of, on their own network, after they confirm
it. It is not automatic and there is no other destination.

## Current protections
- **Loopback bind only** — the engine binds `127.0.0.1` (`server.py`, `ThreadingHTTPServer`); not reachable off-host.
- **Per-launch token** — a `secrets.token_hex(16)` token is generated each start, printed once as `{port, token}` on the sidecar's stdout, read by the Rust shell, and required on **every** POST (`X-Auth-Token`). Only `GET /health` is unauthenticated.
- **No-orphan lifecycle** — the sidecar is reaped on app exit via a Windows Job Object (`KILL_ON_JOB_CLOSE`) + parent-PID watch + `RunEvent::Exit`.
- **Input validation** — bad request input returns a sanitized HTTP 400; 500 bodies are generic (`internal error`), never raw tracebacks (`request_validation.py`).
- **Engine safety** — hardened lxml parser (entities/DTD/network off), GET-only outbound (printer probes), no `subprocess`/`eval`/`pickle`, parameterized SQL, provider API keys read from env server-side only, originals never mutated (verified safe-copy writers), report writes path-validated.

## Content Security Policy (implemented)

CSP is now set in `desktop/src-tauri/tauri.conf.json` (`security.csp`). Summary of the
policy: `default-src 'self'`; `script-src 'self'`; `style-src 'self' 'unsafe-inline'`;
`connect-src` limited to `'self'`, the Tauri IPC origins, and loopback
(`http://127.0.0.1:*` / `http://localhost:*`); `object-src 'none'`; `frame-src 'none'`.
The renderer can still obtain the sidecar token via the `get_api_info` Tauri command;
the webview loads only local, bundled assets — no remote or user-controlled HTML/script
is ever loaded.

Interactive verification of the CSP (app launch, navigation, sidecar API calls,
images/icons/theme) happens in the installed-app smoke each release. Optionally, a
future hardening could proxy sidecar calls through Tauri commands so the token is never
exposed to JS at all.

## 3MF archive handling (path traversal)

Studio parses 3MF zips fully in memory (`backend/snapstudio_core/container.py`);
archive entry names are never used as filesystem paths, so the OrcaSlicer-class 3MF
path-traversal issue does not apply. This behaviour is pinned by
`backend/tests/test_container_paths.py`.

## Runtime and trust-store floors

The repository's build and test scripts, and every workflow that sets up Node, run only on a Node.js release that carries the October 2026 security fixes (22.23.4, 24.22.1, 26.12.1 or newer;
CVE-2026-111497 is the Brotli decoder). `.nvmrc` names the CI version and `scripts/check-node-floor.mjs` enforces the floor in
those workflows and in the desktop `pretest`/`prebuild` scripts; the acceptance and hardware harnesses use the machine's Node and
have no floor check of their own. Studio ships no Node.js runtime.

The one public-CA TLS client in the shell (the update check) uses embedded roots. `desktop/src-tauri/tests/trust_store.rs` fails if the
lockfile resolves `webpki-roots` below 1.0.10 or `rustls-webpki` below 0.103.16, or if the removed emSign ECC G3 root is embedded. The release link
from the update check is limited to this repository's `releases/latest` and `releases/tag/<tag>` pages. Full audit: `docs/internal/SECURITY_ADVISORY_NODE2SHELL_EMUDHRA_2026-10-23.md`.

## Reporting
This is an independent open-source project (not affiliated with Snapmaker). Report
security issues via a GitHub issue marked security, or the repository contact.
