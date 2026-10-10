# Local fonts: no remote font request (issue #94)

Studio's stylesheet used to start with an `@import` of Google Fonts (Inter, JetBrains Mono), so loading the web UI in a
browser or the Vite dev server contacted a remote host. That conflicts with Studio's local-first rule. The import is gone and
the font stacks are system stacks (set in `desktop/tailwind.config.js`, plus the splash in `desktop/index.html`). The CSP in
`desktop/src-tauri/tauri.conf.json` is unchanged.

Script: `tools/acceptance/local-fonts-offline.mjs` (Windows; Microsoft Edge via playwright-core;
`--out <folder> --tag before|after --mode dev|preview`). It loads the UI in dark and light themes with every request
recorded, aborts anything that is not loopback / `data:` / `blob:`, and fails if one was attempted or no text rendered.

## Result

| Run | Requests seen | Non-loopback attempts | Text rendered (dark, light) |
|---|---|---|---|
| before, dev server (`before-*.json`) | 320 | **2**, both `fonts.googleapis.com` | yes |
| after, dev server (`after-dev.json`) | 318 | **0** | yes |
| after, production build via `vite preview` (`after-preview.json`) | 6 | **0** | yes |

Screenshots: `before-dark.png`, `before-light.png`, `after-dark.png`, `after-light.png` (dev server, no engine running, so
the status bar says "Reconnecting"; no real data, printers, paths or model names).

The before and after screenshots are byte-identical (same SHA-256 for the dark pair and for the light pair). That is expected, not a missed change: the font request
was blocked in the "before" run, and Inter is not installed on this machine, so both fell back to the system UI font.
On a machine that has Inter installed, or with the font host reachable, the "before" look could differ slightly.

## Not run

- The packaged Tauri window (Windows installer build). The issue's guess that the CSP already blocks the request there is
  still unchecked; this change makes the question moot for the stylesheet.
- WebKitGTK (Linux).
- Any browser other than Edge.

The vitest guard `desktop/src/noRemoteFonts.test.ts` fails if any CSS, HTML, TS or TSX under `desktop/src`, or
`desktop/index.html`, references a known font host or a remote `@import`. Mutation-checked: putting the old `@import`
back in `index.css` makes it fail.
