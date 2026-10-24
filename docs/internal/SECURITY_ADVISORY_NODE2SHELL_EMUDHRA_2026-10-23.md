# Security report: Node2Shell (Node.js Brotli) and the October 2026 eMudhra intermediate compromise

Date of audit: 2026-10-23. Scope: this repository, its build and release infrastructure, and the application artifacts available
on the audit machine. No printer, Snapmaker service or third-party service was contacted other than the public sources below
and the package and advisory registries the scanners use. Nothing was merged, tagged, published or deployed.

## Sources (retrieved 2026-10-23)

| Source | Facts taken from it |
|---|---|
| https://nodejs.org/en/blog/vulnerability/october-2026-security-releases | Ten CVEs fixed in 22.23.4, 24.22.1 and 26.12.1, including CVE-2026-111497 (Brotli decoder out-of-bounds write via `node:zlib`, High, 22.x/24.x/26.x). Node 20 is not mentioned and, being end-of-life, is treated as unpatched. The same releases update ca-cert for the eMudhra intermediate compromise, Undici, c-ares and OpenSSL. No workaround is given. |
| https://github.com/nodejs/node/releases/tag/v26.12.1 | Released 2026-10-21. Brotli fix is a cherry-pick; bundled undici 8.12.2, NSS root certificates 3.131.1. |
| https://rustsec.org/advisories/RUSTSEC-2026-0381.html | webpki-roots: root `emSign ECC Root CA - G3` removed in 1.0.10. 0.26.11 is a wrapper that re-exports its separately resolved 1.x dependency, so that 1.x crate must be 1.0.10 or newer. |
| https://github.com/rustls/webpki-roots/pull/133 | Removed anchor identified by SPKI SHA-256 `8d417db2dd8bf5e3084d1e3f196d583849d81bdd4c00c70b9d39369e96b8c782`; merged 2026-10-19; 1.0.10 published. |
| https://blog.mozilla.org/security/2026/10/20/protecting-firefox-users-following-the-compromise-of-emudhra-intermediate-certificates/ | Private keys of eight eMudhra intermediate certificates are compromised; blocked via OneCRL; NSS 3.131.1 removes the signing root. The post gives no fingerprints or SPKI hashes and does not name the root. |
| https://rustsec.org/advisories/RUSTSEC-2026-0382.html (found by the scan, not in the request) | rustls-webpki below 0.103.16 may accept paths through the disclosed emSign intermediate keys when the configured anchors allow it. Fixed in 0.103.16. |

The two press articles named in the request were not fetched; the vendor pages above were treated as authoritative.

Facts: the version and fix statements in the table. Inference: exposure paths below. Unknown: whether any signing or release
credential of this project chains to an emSign certificate (nothing indicates it does; see Release signing).

## Exposure inventory

| Component | Observed | Role | Network entry / trust source | Node2Shell | eMudhra | Evidence |
|---|---|---|---|---|---|---|
| Node.js on the development machine (system install) | 24.11.0 | build and test tooling | npm registry and local loopback fetches | **Affected** (fixed 24.22.1) | uses Node's bundled NSS (pre-3.131.1) | `node -v`; reachability below |
| Other Node binaries on the machine (an editor helper, a Python Playwright driver) | 22.22.0, 24.21.0 | not used by this project | none from this project | Affected if used elsewhere; unrelated to project builds | n/a | file search |
| `guide-ci.yml` | `node-version: "20"` | CI, static guide build and checks | `fetch` HEAD to link targets | **Affected** (end-of-life line) | n/a | workflow file |
| `ci.yml`, `linux-ci.yml`, `release.yml`, `release-linux.yml` | `node-version: "22"` (floating; setup-node may use a runner-cached older 22.x) | CI and release builds | npm registry | Unverified for past runs; **not guaranteed** patched | n/a | workflow files; no run logs reviewed |
| Shipped installer and `.deb` payloads | no Node runtime (Windows payload: Rust shell and Python sidecar executables) | shipped | n/a | **Not affected** (no Node.js shipped) | see Rust row | extraction of the v1.7.0 RC1 and v1.6.0 installers |
| Rust shell `ureq 2.12.1` -> `rustls 0.23.43` -> `webpki-roots 0.26.11` -> `webpki-roots 1.0.9` | embedded roots include `emSign ECC Root CA - G3` | shipped; one HTTPS GET to the GitHub releases API (manual or opt-in update check) | public CA roots embedded in the binary | `brotli 8.0.4` is only the build-time asset compressor of the Tauri code generator (Rust, unrelated to Node's decoder); rustls' `brotli` feature is not enabled | **Affected** before this change | `cargo tree`; byte scan of binaries |
| Same, `rustls-webpki 0.103.15` | accepts paths through disclosed emSign intermediates | shipped | same | n/a | **Affected** before this change (RUSTSEC-2026-0382) | `cargo audit` |
| Python sidecar (frozen) | `snapstudio-api.exe`, sha256 `49ff00cf...25b8`, cryptography 50.0.2, lxml 6.1.1, no certifi, no bundled CA file | shipped | HTTP and HTTPS reads from providers on the user's own network only; default `ssl` context, so trust comes from the operating system store | not affected (no Brotli or zlib network decoding; no Node) | System store; depends on the OS update. Reachable only by a LAN provider presenting a public-CA chain, which is not the normal case | archive table of contents; `material_providers.py`; `pip-audit` |
| WebView2 (Windows) and WebKitGTK (Linux) | system component | shipped UI | content security policy limits connections to the app and loopback; only bundled assets load | n/a | system trust store or browser root program; outside this repository | `docs/SECURITY.md`, `tauri.conf.json` |
| Release and acceptance tooling | PowerShell downloads pinned tools with hash checks; harness uses loopback only | build | pinned hashes | n/a | n/a | `tools/release/tools.lock.json`, grep |

### Node2Shell reachability (traced)

No project source outside the floor script's test imports `node:zlib` or any Brotli API (that test round-trips its own data on a patched runtime only). Node-side `fetch` calls in `tools/` and `site/guide/tools/` target
loopback addresses we start ourselves (our sidecar, mock servers, the local UI), except the guide link checker, which sends
HEAD requests to external URLs (HEAD responses carry no body, so there is no body to decompress). The browser-side `fetch` in
the acceptance harness runs in WebView2, not in Node. The remaining exposure is therefore indirect: npm's own registry client
(a trusted-CA TLS connection), and any dependency that decompresses responses. Reaching the decoder would require control of a
registry or of a TLS path to it. The eMudhra incident makes the second condition more plausible for unpatched trust stores, which
is a reason to patch both together. A plain Node HTTP listener does not decompress request bodies; the listeners here are
test servers bound to loopback. Exploitability is **inferred and low**, not demonstrated, and no exploit input was run anywhere.

## Changes in this patch

1. `.nvmrc` pins 22.23.4. All five workflows that use `actions/setup-node` now read it (`guide-ci.yml` moves off Node 20) and
   run `scripts/check-node-floor.mjs`, which fails below 22.23.4, 24.22.1 or 26.12.1, on every line without a fix, and on any pre-release or nightly
   build (its version number does not show the fix is included), and writes the actual version to the step summary. The command
   compares real paths, so a symlink or drive-letter difference cannot make it skip silently. `ci.yml` also runs the script's own
   test file.
2. `desktop/package.json` and `site/guide/package.json` declare `engines` (`>=22.23.4 <23 || >=24.22.1 <25 || >=26.12.1 <27`, the same set the script accepts); the desktop `pretest` and `prebuild` scripts run the
   same check, so a local build or test run on an affected Node stops with a message. `desktop/package-lock.json` records the
   engines field only (the lockfile was otherwise left untouched; `npm install --package-lock-only` also dropped 512 lines of
   optional platform entries, so that result was discarded).
3. `Cargo.lock`: `webpki-roots` 1.0.9 -> 1.0.10 and `rustls-webpki` 0.103.15 -> 0.103.16, by `cargo update --precise`; checksums
   come from the registry. No `Cargo.toml` dependency change and no advisory suppression. `[dev-dependencies]` adds `rustls`,
   `sha2` and `webpki-roots` (versions already in the lock) for the regression test.
4. `desktop/src-tauri/src/main.rs`: the update check shows the release link from GitHub's answer. It now passes on only
   `releases/latest` (or `releases`) and `releases/tag/<tag>` of this repository, where the tag has only letters, digits, `.`, `-`, `_`,
   and otherwise uses the releases page (defence in depth against a forged answer). A prefix check alone was not enough: a link
   such as `.../snapmaker-studio/../../other/project` is normalised by a browser out of the repository, so dot segments,
   encoded dots, backslashes, queries and fragments are refused. Unit-tested with those cases.
5. Tests: `scripts/check-node-floor.test.mjs` (version floor table, workflow wiring, decoder smoke test that runs only on a
   patched runtime) and `desktop/src-tauri/tests/trust_store.rs` (see below).

## Verification (this machine, 2026-10-23)

Patched runtime for all JavaScript checks: Node 24.22.1 (portable build, archive SHA-256 matched the published SHASUMS file
`d2046d28...5fa5`; the checksum file came from the same origin and its signature was not verified). npm 11.19.1, cargo 1.91.1,
cargo-audit 0.22.2 (advisory database commit `84d943a6deeb`, 1351 advisories, updated 2026-10-23), pip-audit 2.10.1.

| Check | Result |
|---|---|
| `node --test scripts/check-node-floor.test.mjs` (Node 24.22.1) | 8 pass (adds pre-release rejection and a command-line exit-code test) |
| `check-node-floor.mjs` under the system Node 24.11.0 | exit 1, "below the fixed release 24.22.1" |
| `npm ci`, `npm run test` (desktop) | 70 files, 816 tests pass |
| `npm run build` (desktop) | success |
| Guide `tools/build.mjs`, `tools/check.mjs` | built, `public/index.html` unchanged, 49/49 static checks (browser e2e not run) |
| `cargo test --locked` (desktop shell), rerun after the last source edit | 50 unit + 8 trust-store tests pass |
| Trust-store test on the old lockfile (webpki-roots 1.0.9, rustls-webpki 0.103.15), current test file | exactly 4 of 8 **fail** as intended: `lockfile_resolves_the_webpki_roots_1x_crate_to_1_0_10_or_newer`, `lockfile_resolves_rustls_webpki_to_a_release_that_rejects_the_distrusted_emsign_intermediates`, `embedded_roots_exclude_the_removed_emsign_ecc_g3_anchor`, `no_embedded_anchor_is_named_emsign_ecc_g3`; the other 4 pass (an earlier trial with an older test file reported 3) |
| Trust-store test on the new lockfile | all pass: SPKI `8d417db2...c782` absent from the embedded roots; no anchor named `emSign ECC Root CA - G3`; a chain to a test CA verifies for its name, fails for another name, and fails with an unknown issuer |
| `pytest` (backend), `npm run test`, `cargo audit`, `pip-audit` | run earlier the same day on this change set; not rerun after the final edits, which touch neither the backend nor the desktop sources (the later edits are the shell link check, the floor script, `ci.yml`, `engines` strings and docs) |
| `pytest` (backend) | 2858 passed, 50 skipped (earlier run) |
| `cargo audit` on the new lock | RUSTSEC-2026-0381 and RUSTSEC-2026-0382 no longer reported |
| `pip-audit` (requirements and the frozen sidecar's pinned versions) | no known vulnerabilities |
| `npm audit` (desktop) | 15 findings (10 moderate, 5 high) in the dev toolchain: vite, vitest, postcss, esbuild, react-router, browserslist, nanoid, source-map-js, undici in jsdom and others. None concern Brotli or the two incidents. Not changed here. |

Alternate paths: after 1.0.10 the store still holds `emSign Root CA - C1`, `emSign Root CA - G1` and `emSign ECC Root CA - C3`
(SPKI SHA-256 `a9f0857a...`, `cab0f2c8...`, `19eb98b5...` as printed by the test). The sources remove only the G3 root and do not say
another emSign root is compromised. The disclosed intermediates are additionally refused by rustls-webpki 0.103.16, which covers a
path through any remaining anchor. Whether any of the eight intermediates is cross-signed by a different root is **unknown**;
the sources do not say. Certificate verification and hostname validation stay on (the test proves a wrong name is rejected);
no verification was disabled anywhere, and `grep` finds no `CERT_NONE`, `verify=False` or insecure flag in the repository.

### Local rebuild

A release-profile build of the Rust shell (`snapmaker-studio-desktop.exe`, 11,190,272 bytes, built 2026-10-23 21:02 local time, exit 0)
was made from the patched tree in an isolated target directory, after the last source edit (the first build of the same day,
11,364,352 bytes, predates the link-check hardening and was discarded; the size difference was not investigated further, both
used the same lockfile and front-end assets). SHA-256 `89D4617270FFA577A542893CE4615B2AAB9CB834EDB8A730A5BF7F316D056845`.
A byte scan of the executable (same method that found the root in the RC1 candidate and v1.6.0 payloads):

| Search string | Matches |
|---|---|
| `emSign ECC Root CA - G3` | **0** |
| `emSign ECC Root CA - C3`, `emSign Root CA - C1`, `emSign Root CA - G1` | 1 each (expected: the report above lists them as still present) |
| `rustls-webpki-0.103.16` / `rustls-webpki-0.103.15` | 12 / 0 |
| `releases/latest` | 2 (the compiled-in fallback and allowed page; the restriction's logic itself is covered by the unit test, not by this scan) |

Limits: this is a shell-only build. The Python sidecar in this build is an empty placeholder file, so it is not an installer
payload; it was not signed, packaged or run. A byte scan shows absence of the root's name, not of every certificate that could
chain to it. The rebuilt executable is a verification artifact on this machine only and was not distributed.

## Verdicts

| Component | Verdict |
|---|---|
| Node.js runtime selection in the repository (workflows, engines, local scripts) | Remediated and verified (floor enforced by test and by a failing run on 24.11.0). The hosted runner versions of past runs are **unverified**. |
| Node.js on this development machine | **Affected, not remediated**: 24.11.0 needs 24.22.1 or newer (host action) |
| Shipped installers and `.deb` | Node2Shell: not affected (no Node shipped). |
| Rust update-check trust (published v1.0.0 through the v1.7.0 RC1 candidate) | **Affected**: the RC1 candidate and v1.6.0 payload executables embed `emSign ECC Root CA - G3` (byte scan of both). Published installers older than v1.6.0 were not available for scanning: unverified, presumed affected. |
| Rust update-check trust in this patch | Remediated and verified at source, test and rebuilt-executable level (release-profile shell built locally, root absent by byte scan); no signed installer or `.deb` has been produced |
| Python sidecar trust | Not affected by embedded roots (no certifi or CA file); depends on the OS store; low reachability |
| WebView2 / WebKitGTK | Unverified (system or browser components) |
| Release signing | Unverified: no evidence of compromise; the Authenticode or other signing certificate chain was not available to inspect. Any certificate actually issued under an emSign chain would need replacement. |

Impact of the eMudhra issue on users, inferred: the only Studio code path that validates a public-CA certificate is the update
check. A network attacker holding a forged certificate for the GitHub API host could return a fake "newer version" answer
(version string and link). Studio does not download or install anything from it. The link was previously passed through; it is
now restricted to this repository.

## Remaining actions (not done here, need a decision or a host)

1. Install Node 22.23.4, 24.22.1 or 26.12.1 (or newer) on the development machine and any self-hosted runner; remove or ignore
   Node 20. Re-run `npm run test` there.
2. Apply the same lock and workflow changes to `release/v1.7.0` and any other maintained line. The v1.7.0 RC1 candidate still embeds
   the removed root and the old verifier; fixing it is a non-document change and needs a new candidate.
3. Decide whether to ship the fix in a patch release; previously distributed installers are not changed by a lockfile update.
4. Separate TLS findings on the same path, not part of these incidents and not changed here: rustls 0.23.43 has RUSTSEC-2026-0285,
   -0346, -0348 and -0349 (fixed in 0.23.46); `cargo update -p rustls --precise 0.23.46` is the likely fix. quick-xml 0.39.4
   (RUSTSEC-2026-0194, -0195) arrives through the Tauri build tooling.
5. Review the acceptance and hardware harnesses' use of the machine's Node; they have no floor check of their own.
6. Windows and Linux system trust stores need the vendors' root-program updates (for example the NSS 3.131.1 removal);
   this repository cannot change them. No machine-wide trust change was made.
7. Review run logs of past hosted builds if a record of the Node versions actually used is needed.
