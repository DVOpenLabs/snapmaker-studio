# Windows release checklist (Snapmaker Studio)

> Why this exists: `tauri build` does **not** re-freeze the PyInstaller sidecar.
> If you forget to rebuild it, the installer ships a **stale sidecar** and new
> backend endpoints (e.g. Compatibility / Scale / Model Discovery / Print Quality
> / First Layer Doctors) return 404 at runtime even though the UI renders. v0.4.0-
> beta.4 shipped with this bug; always follow the steps below.

## 1. Version bump
- `desktop/package.json`, `desktop/src-tauri/Cargo.toml`,
  `desktop/src-tauri/tauri.conf.json` → the public version (no `-local`).
- `backend/pyproject.toml` → PEP 440 form (e.g. `0.4.0b5`).
- Commit the `Cargo.lock` change too.

## 2. Tests (must be green)
```
cd backend  && python -m pytest -q
cd desktop  && npm run test && npx tsc --noEmit && npx vite build
```

## 3. Build — ALWAYS refreeze the sidecar first
```
cd desktop
npm run release:windows      # = build:sidecar (pwsh scripts/build-sidecar.ps1) then tauri build
```
(equivalently: `cd desktop/scripts && pwsh build-sidecar.ps1`, then `cd desktop && npx tauri build`.)

Dev/local builds may skip the refreeze; **public releases must not.**

## 4. Mandatory bundled-sidecar endpoint smoke (do NOT publish if this fails)
Start the staged sidecar (`desktop/src-tauri/bin/snapstudio-api-*.exe`), read its
stdout handshake `{port, token}`, and confirm every route resolves (POST routes
need the `X-Auth-Token` header). None of these may 404:

- `GET  /health`             → 200
- `POST /plate_inspect`      → present (existing)
- `POST /compatibility_check`→ present
- `POST /scale_preview`     → present
- `POST /model_search`      → present (ok if providers disabled — no API keys)
- `POST /quality_check`     → 200 with a valid symptom
- `POST /first_layer_check` → 200 with a valid symptom

A missing route returns **404**; an executed route on bad input returns 400/500 —
that still proves the route exists. Also confirm **0 orphan sidecar processes**
after the app/sidecar closes.

## 5. Checksum + notes
- Compute final size + SHA256 of `Snapmaker Studio_<version>_x64-setup.exe`.
- Fill `docs/RELEASE_NOTES.md` and `docs/windows-install.md` (file name, size, SHA256).
- Grep release notes for paid/commercial model names — expect 0 hits.

## 6. Tag + publish
```
git commit -am "release: v<version>"
git tag -a v<version> -m "Snapmaker Studio v<version>"
git push origin main && git push origin v<version>
gh release create v<version> --title "Snapmaker Studio v<version>" \
  --notes-file docs/RELEASE_NOTES.md --prerelease --verify-tag \
  "desktop/src-tauri/target/release/bundle/nsis/Snapmaker Studio_<version>_x64-setup.exe"
```

## 7. Reminder
The installer is **unsigned** (SmartScreen "Unknown publisher"); ship the SHA256
so users can verify. Signing readiness: `docs/windows-code-signing.md`.

## 8. Pre-GA blockers (OK for beta, must close before a wider/signed public launch)
- **Code signing** — acquire a cert; see `docs/windows-code-signing.md`.
- **CSP** — set in `tauri.conf.json`; re-verify the GUI still reaches the local engine
  after any CSP change. See `docs/SECURITY.md`.

## 9. Public release-notes protocol (EVERY release)
`docs/RELEASE_NOTES.md` becomes the GitHub release body. It is public/marketing.
- **User-facing only.** Describe features and fixes. NEVER mention internal review
  tools, AI model or vendor names, the security-review process, implementation
  mechanics, or exploit-style detail (external review tooling, independent review
  passes, automated reviewers, and specific security surfaces all stay unnamed).
  Use safe wording: "improved validation/reliability", "release packaging checks",
  "advisory wording", "planned security hardening". Before `gh release create`,
  grep the drafted body for banned terms (see docs/internal/FABLE_RELEASE_COPY_REVIEW.md §4).
- **No guarantees / no paid model names** (the unqualified-claim + tooling-term
  guards in `backend/tests/test_public_claims.py` enforce both — keep them green).
- **Absolute links.** A GitHub *release page* resolves relative links against the
  repo ROOT, not `docs/`, so `(windows-install.md)` 404s. Link with a full URL:
  `https://github.com/DVOpenLabs/snapmaker-studio/blob/v<version>/docs/<file>`.
- **Verify the LIVE body after publishing:** open the release, click every link
  (no 404s), confirm SHA256 + unsigned notice present, asset attached, and no banned
  terms. Same protocol when adding any "superseded" notice to an older release.

## Open follow-ups

- [ ] Refresh README screenshots (current set is beta.16-era: pre-truth-sweep hero wording + old version stamps) after beta.21 acceptance.
