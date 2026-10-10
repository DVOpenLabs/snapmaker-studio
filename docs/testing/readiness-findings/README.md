# "Print risk signals" replaces the "Print readiness (estimate)" percentage (#92)

Real Studio engine and this branch's own web UI, driven in **Microsoft Edge (Chromium, headless)** by
`tools/acceptance/readiness-findings-ui.mjs`. Both models are anonymous copies made in a throwaway folder
(`example-project.3mf`, copied from the repository's own example, and `example-cube.stl`, a 20 mm cube the script generates). No printer
is reachable: the only printer address used is this machine's own, where nothing listens, and any engine request naming another host
or discovery is aborted and fails the run.

**Result: 44/44 checks passed (including six self-tests that the printer-page check fails on "Score 85", "Grade B", "Printer Health Score", "92/100" and "Healthy (100/100) good to print") (`results.json`)**, in light and dark, including a scan of the whole page (visible text and every accessible name) after the Intelligence Report has loaded: no score, "/ 100", percentage, star rating ("X of 5"), "Score" or "rating" label, readiness rating, "will it print" or success verdict. The only percentages allowed are measured geometry ("N% of surfaces", "steep overhangs") and the pricing margin (`results.json`).

| Screenshot | What it shows |
|---|---|
| [01 light](01-signals-found-light-card.png), [01 dark](01-signals-found-dark-card.png) | The card for a project with a signal: what it found, what it means, what to do, the evidence kind ("Studio's check"), then what Studio checked, what it did not check, and what it cannot know. No percentage, band or verdict. |
| [02 light](02-nothing-flagged-light-card.png), [02 dark](02-nothing-flagged-dark-card.png) | A model with no signals: says exactly what the checks covered and what they did not, and that this is not a sign the print will succeed. |
| [03 light](03-printer-answered-evidence-light-page.png), [03 dark](03-printer-answered-evidence-dark-page.png) | A fake printer (a Moonraker look-alike on this machine) answers; the Intelligence Report's evidence is expanded. The Printer line says "Answered, N concerns"; no health number, grade, "good to print" or "Compatible". |
| [04 light](04-not-verified-object-spacing-light-page.png), [04 dark](04-not-verified-object-spacing-dark-page.png) | The Intelligence Report when object spacing is not verified and nothing else was found: the first tile reads "Not verified: Object spacing" (no "Risks found 0", no biggest risk), and the advisory line does not call it a count of risks. **One engine reply is stubbed for this state**: the script takes the real report reply for the cube and removes the risks / marks spacing not verified, because no real fixture here is both free of findings and a multi-object 3MF. The rest of the page is real. |
| [05 light](05-printers-what-the-printer-reported-light-card.png), [05 dark](05-printers-what-the-printer-reported-dark-card.png) | The Printers page card "What the printer reported", with the fake printer answering: a plain verdict, the drivers, and "From firmware state + last 5 prints"; no grade, score or /100, and no "Nothing concerning" beside listed concerns. |
| [06 light](06-printers-failed-print-no-warning-light-page.png), [06 dark](06-printers-failed-print-no-warning-dark-page.png) | The Printers page when the printer reports ready firmware, no firmware warning and one failed recent print: the state chip reads "See concerns" (not "Healthy") and the card below lists "1 of the last 5 prints failed". |
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
