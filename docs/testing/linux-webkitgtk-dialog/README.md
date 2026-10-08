# Printer-action confirmation prompt on Linux (WebKitGTK)

Integrated check of the confirmation prompt in the **real packaged Studio app** on Linux: the Tauri build's own
WebKitGTK web view, driven over WebDriver by `tauri-driver`. Printer calls are mocked by a loopback Moonraker look-alike.

- **Result:** 27/27 checks passed, two consecutive runs of the final script (an earlier version of the script ran 25/25 twice; it did not yet confirm emergency stop, see the review notes).
- **Artifact under test:** the `snapmaker-studio-linux-deb` artifact of the Linux CI run for `main` at `3ce3e263efea`
  (`snapmaker-studio_1.5.0_amd64_3ce3e263efea.deb`, sha256 `8aef32ba4b0848a0bf9f0d85e1cff7f7862923905bbc70184d69f8a20d3890fc`,
  verified against the artifact's `SHA256SUMS`). An unreleased engineering preview.
- **Environment:** Ubuntu 24.04.3 on WSL2, Xvfb 1280x900 (no window manager), libwebkit2gtk-4.1-0 2.52.6, tauri-driver 2.1.0,
  WebKitWebDriver from `webkit2gtk-driver`, Node 20. The web view reports `AppleWebKit/605.1.15`.
- **Isolation:** the app, driver and script run as an ordinary user inside a network namespace that has only a loopback
  interface and no routes (the script prints this). Root is used only to create that namespace (and, beforehand, to install
  packages). No real printer, router or other machine can be reached from there.
- **Run it:** `tools/acceptance/linux/printer-confirm-dialog-webkit.sh <user> <evidence-dir>`.

## Per case

| Result | Case |
|---|---|
| PASS | the page is a real WebKitGTK web view with native <dialog>.showModal() |
| PASS | printer controls appear for the loopback printer while it is printing |
| PASS | opens as an alertdialog named by its title |
| PASS | the warning and the printer are in its description |
| PASS | initial focus is on Cancel |
| PASS | the prompt is centered in the window |
| PASS | six Tabs forward and six Shift+Tabs backward never focus a control on the page behind the prompt |
| PASS | the prompt's own buttons are the only controls focus visited |
| PASS | the connect field behind the prompt cannot be clicked |
| PASS | Escape closes the prompt |
| PASS | Escape sent nothing to the printer |
| PASS | focus returns to the Cancel print button |
| PASS | Escape pressed twice while the request is running leaves the prompt on screen |
| PASS | three rapid confirms send exactly one cancel request |
| PASS | the prompt closes when the request finishes |
| PASS | the prompt is withdrawn when the printer stops answering |
| PASS | nothing was sent to the printer that went away |
| PASS | the prompt is withdrawn when the print finishes |
| PASS | no cancel was sent for a print that had already ended |
| PASS | focus lands on the card heading after the Cancel button disappeared |
| PASS | the prompt is withdrawn when the printer address changes |
| PASS | nothing was sent to either printer |
| PASS | emergency stop asks first and names the printer |
| PASS | dismissing emergency stop sends nothing |
| PASS | confirming emergency stop sends exactly one M112, to the printer named in the prompt (three rapid presses of Yes) |
| PASS | nothing was sent to the other printer |
| PASS | every connection the look-alike printers received arrived on a loopback address (and at least one did) |

Raw per-case record: [results.json](results.json). Screenshots taken from the web view itself:
[dialog open](dialog-open.png), [dialog closed](dialog-closed.png).

## What this does and does not show

- Shown: native `<dialog>` modal behaviour, accessible name/description, initial focus on Cancel, keyboard containment,
  Escape cancellation (including a second Escape while a request runs), focus restoration, withdrawal when the printer goes
  offline, its print ends or the address changes, and exactly one request for three rapid confirms, in WebKitGTK.
- On WebKitGTK, Tab/Shift+Tab can land on the `<dialog>` box itself between its two buttons; focus never reaches the page
  behind it. The check accepts that (the first run asserted buttons only and flagged it).
- The address change is made programmatically, because the page behind a modal prompt is inert and cannot be typed into.
- Not covered: a screen reader, Wayland, a physical display or GPU, a signed or released build, and real printers.

## Review notes

- Emergency stop is now activated against the loopback look-alike: the check asserts one `M112` POST to the printer shown in the prompt and none to the other.
- If the driver cannot start or answer, or the WebDriver session cannot be created, the script stops with exit code 2 and prints why, with the driver's own output; `results.json` then carries a `startupFailure` field instead of check results.
- The last check used to pass whatever happened. It now records the address each look-alike connection actually arrived on and requires that at least one arrived. It does not prove isolation by itself; the empty network namespace does that.
- `results.json` has two request lists: `allPosts` (every POST the look-alike printers received during the run, in order) and `callsSinceLastReset` (only the requests since the script last cleared its list between scenarios, so it does not include the earlier cancel). The wrapper gives the test user its own `XDG_RUNTIME_DIR`, so the driver log is free of the desktop-library permission noise an inherited root runtime directory caused.
