# Model Discovery → "Model Browser" direction

> **History and direction.** The sections below describe the beta-era browser. The
> v1.4.0 behaviour is in "Status (v1.4.0: Model Connect)" at the end of this file and
> supersedes the "manual download" statements above it. Live API search and one-click
> import ideas remain unshipped.

Product decision: Model Discovery is an **approved-site browser**, not an
API-key search. Beginners browse trusted 3D-model sites, download an STL/3MF from
the site, then open it in Studio. No API keys in the beginner flow, no scraping,
no import/download claims that aren't implemented.

> Independent open-source project — not affiliated with or endorsed by Snapmaker.

## Why

API-key setup confuses novices and most model sites don't offer an official
search API anyway. Browsing the real sites — where licenses, previews, and
download buttons already live — is simpler and respects each site's terms.

## Beginner experience (shipped)

Find Models now leads with:
- "Browse trusted model sites" — link-out buttons that open the site (with your
  search term) in the browser.
- "Got a downloaded file?" — Open downloaded file → Project Doctor.
- Plain copy: browse the site, download there, open in Studio.

Live in-app API search, filters, and the disabled "Import to Studio" control are
**Advanced-only** and clearly optional. No secret/API-key fields in the UI.

## Approved sites (allowlist)

Printables, Thingiverse, MyMiniFactory, Cults3D, Thangs, MakerWorld.

These are the only domains the Model Browser should ever navigate to. Anything
outside the allowlist opens in the user's external browser (or is blocked).

## Architecture (Tauri — confirmed)

The desktop app is **Tauri v2** (`desktop/src-tauri`, `tauri.conf.json`,
`tauri-plugin-dialog`). A future in-app Model Browser should be a **locked,
low-permission WebviewWindow**, separate from the main app webview:

- Navigation allowlist limited to the approved domains above; off-allowlist
  links open in the OS browser (or are denied), never inside the app window.
- No Node/Tauri API exposure to that webview (no `withGlobalTauri`, no IPC).
- Minimal filesystem/download permissions; the main app keeps its own.
- No injection that bypasses login, paywalls, or site restrictions.

## Download behavior

- **v1 (now):** manual. User downloads from the site; Studio's "Open downloaded
  file" picks the STL/3MF and routes it to Project Doctor on explicit action.
- **v2 (later, optional):** disclosed download interception — ask where to save
  (or a clearly-labeled Studio downloads folder), show progress, never silently
  fetch restricted/private content.

## Guardrails

- No scraping, mirroring, or re-hosting of models.
- No bypassing site terms, login, or paywalls.
- No "one-click download" or "import to Studio" copy unless actually implemented.
- API/provider keys (if ever added) live behind Advanced only, server-side, never
  in the frontend or app bundle.

## Status

**v1 shipped — the in-app Model Browser is live.** In Find Models, "Browse trusted
model sites" opens a dedicated, isolated Tauri WebviewWindow (label `model-browser`)
restricted to the approved domains. The allowlist is enforced in Rust
(`open_model_browser` validates the URL is https + on-allowlist; `on_navigation`
blocks any later off-allowlist top-level navigation). The browser window is granted
no capabilities, so remote pages have no Tauri IPC. In a plain browser (dev) it
falls back to a normal tab.

Download stays **manual** in v1: browse and download on the site, then "Open
downloaded file" → Project Doctor. Download interception is deferred to v2 — it is
not reliable cross-platform via WebView2/Tauri today. Third-party login redirects
(e.g. signing in with Google) navigate off-allowlist and are blocked in-app; sign
in on the site's own domain, or use those sites signed-out for browsing.

## Engineering note (beta.13): why a separate window, not a same-page embed (INTERNAL)

> Internal engineering detail. **Do not put this in public release notes, README
> hero copy, judge overview, or user-facing docs** — to beginners/judges it reads as
> "broken." Public docs say only: "Studio Model Browser opens approved sites in a
> locked Studio-owned browser window."

The original aim was a browser embedded directly in the main Studio page (a child
webview region under the toolbar). On the current stack (Tauri 2.11.3 / wry 0.55.1 /
WebView2 149, Windows) that path is not viable:

- `window.add_child(WebviewBuilder::External(url)...)` — and, in fact, calling
  `WebviewWindowBuilder::build()` for **any** External-URL webview **from inside a
  `#[command]`** — deadlocks. The webview is created (visible at `about:blank`) but
  its navigation never fires and the command never returns; a second invocation
  wedges behind the first.
- Diagnosed with runtime stderr instrumentation plus the WebView2 DevTools Protocol
  (the child target was visible at `about:blank`; `Page.navigate` over CDP loaded the
  site instantly, proving the webview itself works — only the build-time External
  navigation is the problem).

Stable fix shipped in beta.13: pre-build the locked `model-browser` window **once at
startup** (in `setup`, on the main thread, hidden, `about:blank`), where `build()`
returns normally. Commands then only `navigate()` + `show()` + raise the live window
(navigating an existing webview works reliably). "Close" hides it (kept for reuse);
the OS close button hides it too. `on_navigation` still locks every navigation to the
approved-domain allowlist; the window holds no capabilities (no IPC to the remote
page). Verified live: Printables and MakerWorld both load.

Do **not** reattempt the same-window `add_child` embed on this stack without first
re-verifying the deadlock against a newer Tauri/wry/WebView2 combination.

## Status (v1.4.0: Model Connect)

The workflow: browse MakerWorld / Printables in the Studio browser → press the site's own
download button → the file is added to the Design Library → Ready Now checks it against the
U1 → Prepare if needed → Snapmaker Orca.

- **Dedicated profile.** The `model-browser` window has its own persistent WebView2 data
  directory under Studio's state folder, so a site sign-in survives a restart but is not
  shared with Studio's own webview. "Clear site data" clears only that profile.
- **Native downloads.** The download is taken through the webview's download event, not an
  HTTP request made by Studio. Studio redirects it into its own downloads folder with a
  collision-safe, sanitised name and accepts only `.3mf` and `.stl`, up to 512 MiB. The
  only file host allowlisted so far is `files.printables.com`, observed in a live spike. A
  download from any other host is refused with a path-free message, and the blocked host
  (host only, size-bounded log) is recorded so it can be verified and added deliberately.
- **Provenance.** A downloaded file is registered through `POST /library/register_download`
  and a `project_sources` row records site, source page and download time. The library card
  shows "Added from <site>". No cookie, token or page content is stored.
- **Navigation.** Top-level navigation is limited to the approved sites plus the sign-in
  hosts those sites use (`account.prusa3d.com`, `accounts.google.com`, and `bambulab.com`
  only on its `/sign-in` path). Popups are denied; sign-in was verified to be same-window.
- **No IPC.** Only the `main` window has a Tauri capability. The browser window can call no
  Studio command, and Studio never reads its cookies.

Platform: downloads and "Clear site data" are Windows and Linux only. On macOS wry cannot
give the browser its own data store or report the finished file path, so both are disabled
there rather than risk clearing Studio's own webview. The download URL itself (not only the
page) must be on the file-host allowlist.

Registration boundary: the engine accepts a download only if its resolved path (symlinks
and junctions followed) is inside the downloads folder the desktop shell gave it, so a file
elsewhere cannot be added with download provenance. The size cap is checked once the
download finishes. A download abandoned part-way can leave a partial file in the downloads
folder (a v1.4 limitation; a failed download Studio can identify is removed).

### Not in v1.4.0
No folder scan, no DOM scraping, no "add current page" button, no authentication popup
support, no Smart Load Planner. MakerWorld and Printables are the first sites needing live
end-to-end verification (sign-in, download, library, Ready Now, restart, clear site data).
The other approved sites keep browsing and are not claimed to download until verified.

### Ready Now (v1.4.0)
Library projects only (newest 50). One printer read and one provider read per scan; no
printer, slot-map or provider writes. Results are cached by path, modified time and size.
Bucket precedence: needs preparation, needs attention, can't determine, one change away,
ready now. A colour-only mismatch may remain Ready now with a colour note; unknown stays
unknown.
