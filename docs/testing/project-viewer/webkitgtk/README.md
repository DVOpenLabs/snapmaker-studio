# Read-only project viewer in the packaged Linux app, under real WebKitGTK

Probe for the viewer candidate (PR #98, `feat/project-viewer` at 1836fd0): the extracted Linux `.deb` from the
`release-candidate.yml` run, started by `tauri-driver` + `WebKitWebDriver`, on WSL2's graphics-enabled session (WSLg
Wayland, compositing NOT disabled). Not Chromium, not Edge.

| File | What it is |
|---|---|
| `viewer-webkit.mjs` | the probe (W3C WebDriver client; judges what the page reports) |
| `run-viewer-webkit.sh` | runner: no sudo, user+network namespace with only a loopback (`unshare -rn`), WSLg or Xvfb |
| `evidence/showcase/` | run on `examples/demo_u1_showcase.3mf`: `results.json`, `console.txt`, window screenshots from the WebDriver |
| `evidence/offplate/` | same on `examples/demo_offplate_foreign.3mf` |
| `evidence/versions.txt` | exact versions and the `.deb` sha256 |
| `evidence/gl-debug-excerpt.txt` | Mesa/EGL loader messages from a separate start of the app with `LIBGL_DEBUG`/`EGL_LOG_LEVEL` |

Repeat: `unshare -rn` needs no root. Set `TAURI_DRIVER`, then
`run-viewer-webkit.sh <dir from dpkg-deb -x> <copy of a .3mf> <evidence dir> wslg isolated`.

## Result: 15/15 on each project

Both runs: 15 of 15 checks passed (see `results.json`). Checked from inside the page: the "3D view of this project" panel
appears; a 540x405 canvas is drawn; no alert shows; the object list and nine camera/slope buttons exist and are enabled;
selecting an object marks its row (`aria-pressed`); 48 real WebDriver input actions (left/middle/right drags with no
modifier and with Shift, Control, Alt, Shift+Control, Shift+Alt; Space held across a drag; wheel plain and with
Control/Alt/Shift; Delete, Backspace, R, S, M, P, C, X, B, F, Enter, arrows, Control+Z/Y/C/V/A, Escape) leave the object list
text unchanged; leaving the page removes the viewer and every canvas; the project file's sha256 is unchanged
(showcase `7d0daae0c663...`, offplate `823adf42e429...`); the page requested only from `127.0.0.1`.

The "unchanged" check is not vacuous: the picture in the canvas changed after the drags (`inputPhases.drags.pictureChanged`),
so the input reached the viewer and moved the camera (see `03a-window-after-drags.png`: the cube is orbited, not moved).

## What is NOT proven

* **GPU-backed WebGL was NOT exercised.** WebKit reports the renderer as "Apple GPU" (it masks the real string), so the
  page cannot tell. The evidence is indirect but consistent: in the app's processes Mesa's `libgallium` and `libLLVM` are
  loaded and no `d3d12`/`dxcore` library is mapped (`graphics-libs-loaded.txt`); starting the app with `LIBGL_DEBUG=verbose`
  shows the hardware attempts failing (`failed to get driver name for fd -1`, `ZINK: failed to choose pdev`, `DRI2: failed to
  load driver`) before it settles on a screen with no hardware fd (`gl-debug-excerpt.txt`). Treat this as Mesa **software
  rendering (llvmpipe) on WSLg**, by inference. WSL has `/dev/dxg` but no `/dev/dri`. WebGL 2 is available and the viewer
  draws correctly on it. Whether it also works on a real Linux GPU is not shown here.
* Only single-object projects were driven, so "list unchanged" and "selecting marks its row" had one row to test; no
  multi-object ordering. Object positions are not read back through WebKit (no API from the page); only the object list and
  the picture were compared.
* Wheel over the canvas also scrolled the page (`inputPhases.wheel.scroll`: the main column scrolled 170 to 200 px) while
  the picture changed. Could not tell from this probe whether the viewer's wheel handler lets the event through; worth a look.
* The element screenshot (`03a-after-drags.png`, `03b-after-keys.png`) shows a black band across the top of the canvas;
  the whole-window screenshots taken at the same moment do not, so this is a WebKitGTK element-capture artefact, not shown on
  screen. Use the `*window*` and `01`-`04` images as the proof images.
* Control+A selects the page text (default browser behaviour, visible in `03-after-input.png`); it is not a viewer action.
* Packaged Windows/WebView2, macOS, screen readers, a real printer: not run (no printer is ever contacted).

## Network isolation

The run is inside a user+network namespace made by `unshare -rn` (no root): `network interfaces in the namespace: lo`,
`routes: 0` (see `console.txt`). Only the app's own loopback engine and the page's `127.0.0.1` were reachable. The page's
resource list contains only loopback hosts.

## Method notes

* The app was extracted with `dpkg-deb -x` (no install, no root); `ldd` on the main binary found no missing libraries.
  The `.deb`'s sha256 was checked against the artifact's `SHA256SUMS` first.
* The project is passed on the command line (`tauri:options.args`); the probe then goes to `/workspace`, as the app does
  for an opened project.
* Home folder and user name are scrubbed from all written text; screenshots show only the app window.
