# Tool tabs: keyboard and focus verification

Real-browser check of the two tab rows, **Compatibility / Source Check** and **Print Quality / First Layer**, operated
**only from the keyboard**, plus focus-ring, 600 px layout and network-isolation checks. Script:
`tools/acceptance/tool-tabs-keyboard.mjs` (Windows; Edge/Chromium; run with `--out <folder>`).

**46/46 checks passed.**

The run used the uncommitted change on top of the base commit. `results.json` records `baseCommit`, `worktreeDirty`, and a
`diffHash` (SHA-256 of `git diff HEAD` plus the untracked files, excluding this folder).

## Engine start

The harness starts the engine through `tools/acceptance/engine-startup.mjs`, which never waits unbounded. A missing Python
(`PYTHON`, default `py`) fails immediately with a clear message; an engine that exits early is reported with its exit code
and a bounded, path-redacted tail of its stderr; if no port is reported within 60 s (override with
`SNAPSTUDIO_ENGINE_TIMEOUT_MS`) the process this run started is stopped by its PID. All three exit nonzero (2) and clean up.
`node --test tools/acceptance/engine-startup.test.mjs` covers these with fake executables.

## What is real and what is not

- **Real:** the Studio engine and the web UI from this branch (served by the Vite dev server, not a production build),
  running locally, in Microsoft Edge (Chromium, headless).
- **This is Edge.** It is not the Tauri window, not WebKitGTK (the Linux window), and not a screen reader. Focus order
  and ring drawing can differ in those; how a screen reader announces the tab row was not tested.
- **No data:** no project is opened and no printer, provider or spool service is involved. The run uses the pages as
  they first appear.
- **Browser network guard:** requests to Google Fonts are aborted and recorded but do not fail the run (see the next
  item). Every other browser request or WebSocket to a host other than this machine is aborted and fails the run, as does
  any engine request that names a printer or network discovery. Service workers are blocked. WebRTC and browser-internal
  traffic cannot be intercepted from the script.
- **Not covered:** the spawned engine process makes its own network calls. This run neither constrains nor observes them,
  so it does not show that the engine stays on this machine.
- **One known, blocked request:** the app's stylesheet asks Google Fonts for its Inter typeface (`desktop/src/index.css`,
  line 1). That behavior is older than this change. The run blocks it, so the screenshots use the fallback typeface, and
  `results.json` lists the hosts in `knownBlockedFontHosts`. It is not fixed here.
- **Ignored console messages:** `Failed to load resource` and `net::ERR` come from the blocked font request. React
  `Invalid DOM property` warnings (`stroke-width`, `stroke-linecap`) come from the existing sidebar icons, not from the tab
  row. `results.json` lists them in `ignoredConsoleMessages`.
- **Not run:** WebKitGTK (`tools/acceptance/linux`) and the packaged Windows window.

## How the tabs behave

- Only one tab is in the Tab order. Focus entering the row always lands on the selected tab: when focus leaves the row,
  the tab stop resets to the selected tab, so a tab you only arrowed to is not remembered.
- Left and Right Arrow move focus, wrapping at the ends. Home and End jump to the first and last tab. Up and Down Arrow
  are not handled by the tab row (the page scrolls as usual); covered by the unit tests, not by this run.
- Arrow keys, Home and End **only move focus**. Enter, Space or a click selects the focused tab and shows its panel.
  Showing a panel reloads that tool, so moving focus along the row deliberately does not switch panels.
- Alt, Ctrl and Meta combinations (for example Alt+Left, Ctrl+Home) are left to the browser. Unit tests cover this.
- The tab row has an accessible name ("Compatibility tools", "Print quality tools"). The panel is labeled by its tab.

## Per case (both pages unless noted)

The table groups the 46 checks by behavior; `results.json` lists each one.

| Result | Case |
|---|---|
| PASS | The tab row has its name |
| PASS | Exactly one tab is in the Tab order, and it is the selected one |
| PASS | Tab, pressed 120 times through the page, lands on the selected tab and never on the other |
| PASS | ArrowRight moves focus to the second tab without switching the panel |
| PASS | The tab stop moves with focus |
| PASS | After arrowing to the other tab and leaving the row, Shift+Tab from the first focusable control in the panel lands on the selected tab |
| PASS | ArrowRight and ArrowLeft wrap; Home and End jump to the ends |
| PASS | Home, End and the arrows never switched the panel |
| PASS | Enter switches the panel and its heading appears; focus stays on the tab |
| PASS | The panel is labeled by the selected tab |
| PASS | Space switches back and the first heading appears |
| PASS | Focus ring visible on the keyboard-focused tab, dark and light (Compatibility page only) |
| PASS | At 600 px wide: no horizontal page scroll, labels not truncated and inside the viewport (both pages) |
| PASS | No request reached another host (the Google Fonts request was blocked, see above), a printer, or discovery |
| PASS | No console errors other than the blocked-request failures (`Failed to load resource`, `net::ERR`) and React `Invalid DOM property` warnings, which the run ignores |

The first focusable control inside each panel is named in `results.json`: "Open a 3MF project" (Compatibility) and
"Stringing / wisps" (Print Quality).

Evidence: [results.json](results.json), [focus ring, dark](01-focus-ring-dark.png),
[focus ring, light](01-focus-ring-light.png), [Compatibility, dark](02-compatibility-dark.png),
[Compatibility, light](02-compatibility-light.png), [Compatibility at 600 px](03-compatibility-600px.png),
[Print Quality at 600 px](03-print-quality-600px.png).

## Unit tests

`desktop/src/components/ui/ToolTabs.test.tsx` and `desktop/src/routes/ToolTabsHubs.test.tsx` cover the same behavior in
jsdom, plus a tab that disappears while selected or focused, modifier keys, and an empty tab list.
