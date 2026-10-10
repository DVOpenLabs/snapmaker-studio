# "Print risk signals" replaces the "Print readiness (estimate)" percentage (#92)

Real Studio engine and this branch's own web UI, driven in **Microsoft Edge (Chromium, headless)** by
`tools/acceptance/readiness-findings-ui.mjs`. Both models are anonymous copies made in a throwaway folder
(`example-project.3mf`, copied from the repository's own example, and `example-cube.stl`, a 20 mm cube the script generates). No printer
is reachable: the only printer address used is this machine's own, where nothing listens, and any engine request naming another host
or discovery is aborted and fails the run.

**Result: 30/30 checks passed**, in light and dark, including a scan of the whole page after the Intelligence Report has loaded (no score, "/ 100", percentage, readiness rating or success verdict; the only percentages left are measured geometry and the pricing margin, and the Project Doctor step heading "Print-Readiness" has no score) (`results.json`).

| Screenshot | What it shows |
|---|---|
| [01 light](01-signals-found-light-card.png), [01 dark](01-signals-found-dark-card.png) | The card for a project with a signal: what it found, what it means, what to do, the evidence kind ("Studio's check"), then what Studio checked, what it did not check, and what it cannot know. No percentage, band or verdict. |
| [02 light](02-nothing-flagged-light-card.png), [02 dark](02-nothing-flagged-dark-card.png) | A model with no signals: says exactly what the checks covered and what they did not, and that this is not a sign the print will succeed. |
| [03 light](03-printer-answered-evidence-light-page.png), [03 dark](03-printer-answered-evidence-dark-page.png) | A fake printer (a Moonraker look-alike on this machine) answers; the Intelligence Report's evidence is expanded. The Printer line says "Answered, N concerns"; no health number, grade, "good to print" or "Compatible". |
| `*-page.png` | The whole page, taken after the Intelligence Report loaded: it shows "Risks found" and no score hero. |

Checked on each: the card lists signals with "What to do"; names its evidence kind; has "Studio checked" and "Studio did not check"
lines (printer health and print history are listed as not checked because no printer answered); says Studio cannot know slicer
settings, filament storage, bed condition or mid-print behavior and to verify in Snapmaker Orca; contains no percentage, "Likely to
print", "Risky" or "Few risks" wording; no page errors.

## Not run

- The packaged Tauri window (this is the web UI in Edge, as in the other acceptance scripts).
- WebKitGTK (Linux).
- A screen reader. The signals use words ("Risk", "Heads up") as well as color, but this was not tested with assistive technology.
- A real printer. The printer scenario uses a fake Moonraker look-alike, not a live U1.

Run it: `PYTHON=py node tools/acceptance/readiness-findings-ui.mjs --out <folder>` (needs Edge and `npm install` in `tools/acceptance`).
