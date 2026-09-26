// Snapmaker Studio desktop shell.
//
// On startup it spawns the local Python engine sidecar, reads its handshake line
// ({"port", "token"}) from stdout, and exposes that to the frontend via the
// `get_api_info` command. The frontend then calls the sidecar over loopback.
//
// DEV (debug): runs `python -m snapstudio_api` from <repo>/backend (the live engine).
// PROD (release), Windows: runs the PyInstaller-frozen sidecar bundled via Tauri
//                 externalBin, which lands next to the app exe as `snapstudio-api.exe`.
// PROD (release), Linux: runs the PyInstaller onedir build bundled via Tauri
//                 bundle.resources (externalBin can't hold onedir's directory
//                 output), located at runtime via resource_dir() — see sidecar.rs.
//
// The sidecar child is tracked in app state and brought down on exit — no orphan
// process (Windows: the Job Object binding in sidecar.rs, backed by the plain
// kill()+wait() below; Linux: three independent layers in sidecar.rs — PDEATHSIG
// + its own process group, armed before exec; graceful /shutdown-then-killpg via
// shutdown_sidecar(), called from the RunEvent::Exit handler below; and a stdin-EOF
// lifeline the sidecar itself arms, see backend/snapstudio_api/_lifeline.py).

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

use tauri::{
    Manager, RunEvent, State, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

use sidecar::{shutdown_sidecar, spawn_sidecar, ApiInfo, SidecarProc};

// Model Browser allowlist — the ONLY domains the in-app browser may navigate to.
// Enforced in Rust at open time and on every navigation; off-allowlist top-level
// navigations are blocked. The browser window gets no capabilities (no IPC).
const ALLOWED_MODEL_DOMAINS: &[&str] = &[
    "printables.com",
    "thingiverse.com",
    "myminifactory.com",
    "cults3d.com",
    "thangs.com",
    "makerworld.com",
];

fn model_host_allowed(url: &Url) -> bool {
    match url.host_str() {
        Some(h) => {
            let h = h.to_ascii_lowercase();
            ALLOWED_MODEL_DOMAINS
                .iter()
                .any(|d| h == *d || h.ends_with(&format!(".{d}")))
        }
        None => false,
    }
}

/// Open (or reuse) the locked in-app Model Browser at an approved-site URL.
/// The frontend builds the (encoded) URL; Rust is the security boundary: it
/// refuses anything not https + on the approved-domain allowlist, and blocks any
/// later navigation that leaves the allowlist.
const MODEL_BROWSER_LABEL: &str = "model-browser";

/// Create the locked Model Browser window, hidden, at about:blank.
///
/// IMPORTANT: this MUST be built at startup (in `setup`, on the main thread), NOT
/// from a #[command]. On this Tauri 2.11 / wry 0.55 / WebView2 stack, calling
/// `WebviewWindowBuilder::build()` from a command's worker thread deadlocks — the
/// window is created but `build()` never returns and the page never navigates. Built
/// here at startup, `build()` returns normally; commands then just `navigate()` the
/// live window, which works reliably. The window is reused for the app's lifetime
/// (closing it only hides it), so commands never need to build it again.
///
/// Security: the window gets NO capabilities (capabilities.json lists only "main"),
/// so the remote page has zero Studio IPC. `on_navigation` locks every navigation to
/// the approved-domain allowlist; only about:blank (the initial blank doc) is allowed
/// off-list.
fn build_model_browser_window(app: &tauri::AppHandle) -> Result<WebviewWindow, String> {
    if let Some(w) = app.get_webview_window(MODEL_BROWSER_LABEL) {
        return Ok(w);
    }
    let blank = Url::parse("about:blank").map_err(|e| e.to_string())?;
    let w = WebviewWindowBuilder::new(app, MODEL_BROWSER_LABEL, WebviewUrl::External(blank))
        .title("Snapmaker Studio — Model Browser")
        .inner_size(1100.0, 850.0)
        .min_inner_size(900.0, 600.0)
        .center()
        .visible(false)
        .on_navigation(|u| u.scheme() == "about" || model_host_allowed(u))
        .build()
        .map_err(|e| e.to_string())?;
    // The OS close button should HIDE the locked window (keep it for reuse), not
    // destroy it — destroying it would force a from-command rebuild, which deadlocks.
    let wc = w.clone();
    w.on_window_event(move |e| {
        if let WindowEvent::CloseRequested { api, .. } = e {
            api.prevent_close();
            let _ = wc.hide();
        }
    });
    Ok(w)
}

#[tauri::command]
fn open_model_browser(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let parsed = Url::parse(&url).map_err(|_| "invalid url".to_string())?;
    if parsed.scheme() != "https" || !model_host_allowed(&parsed) {
        return Err("url is not on the approved model-site allowlist".into());
    }
    eprintln!("[model-browser] open host={} -> approved window", parsed.host_str().unwrap_or("?"));
    // The window is pre-built at startup; navigate the live webview (the path that
    // works on this stack) and bring it forward.
    let w = app
        .get_webview_window(MODEL_BROWSER_LABEL)
        .ok_or_else(|| "model-browser window unavailable".to_string())?;
    w.navigate(parsed).map_err(|e| e.to_string())?;
    let _ = w.show();
    let _ = w.unminimize();
    // Reliable raise on Windows: a brief always-on-top toggle forces the window to
    // the foreground even when set_focus alone would be ignored.
    let _ = w.set_always_on_top(true);
    let _ = w.set_focus();
    let _ = w.set_always_on_top(false);
    eprintln!("[model-browser] navigated + shown");
    Ok(())
}

// ---- Snapmaker Orca handoff (one-way: Studio prepares, Orca slices) ----------
//
// Studio never slices and never controls Orca. These commands only (a) detect an
// installed Snapmaker Orca at a verified location and (b) launch that exact
// executable with the user's prepared 3MF as a single argument. No shell, no
// extra flags, no slicing commands. A path is only ever reported/used if it
// actually exists on disk — no guessed path is treated as truth.

/// Known Snapmaker Orca install locations on Windows, most-trusted first.
#[cfg(windows)]
fn orca_candidates() -> Vec<PathBuf> {
    let exe = "snapmaker-orca.exe";
    let mut v = Vec::new();
    // Verified default install (per-machine).
    match std::env::var("ProgramFiles") {
        Ok(pf) => v.push(Path::new(&pf).join("Snapmaker_Orca").join(exe)),
        Err(_) => v.push(PathBuf::from(r"C:\Program Files").join("Snapmaker_Orca").join(exe)),
    }
    if let Ok(pf86) = std::env::var("ProgramFiles(x86)") {
        v.push(Path::new(&pf86).join("Snapmaker_Orca").join(exe));
    }
    // Per-user install location.
    if let Ok(la) = std::env::var("LOCALAPPDATA") {
        v.push(Path::new(&la).join("Programs").join("Snapmaker_Orca").join(exe));
    }
    v
}

#[cfg(target_os = "linux")]
fn orca_candidates() -> Vec<PathBuf> {
    let mut v = linux_desktop_entry_candidates(&["snapmaker orca", "snapmaker_orca"]);
    v.extend(linux_dir_candidates(&["snapmaker_orca", "snorca"]));
    v.sort();
    v
}

#[cfg(not(any(windows, target_os = "linux")))]
fn orca_candidates() -> Vec<PathBuf> {
    Vec::new()
}

/// First candidate that is a real file on disk (never a guessed path), and —
/// on Unix — actually executable. Windows has no separate executable bit to
/// check (an .exe is executable by virtue of its extension); a downloaded
/// Linux AppImage is a plain file until `chmod +x`'d, so a candidate that
/// exists but isn't executable is correctly NOT reported as "found" — Studio
/// would only fail to launch it anyway, and under-claiming is the correct
/// failure direction here, same rule this table already follows for a
/// community fork installed somewhere this list does not know about.
fn first_existing(candidates: &[PathBuf]) -> Option<PathBuf> {
    candidates.iter().find(|p| is_usable_executable(p)).cloned()
}

#[cfg(unix)]
fn is_usable_executable(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    match std::fs::metadata(p) {
        Ok(m) => m.is_file() && (m.permissions().mode() & 0o111 != 0),
        Err(_) => false,
    }
}

#[cfg(not(unix))]
fn is_usable_executable(p: &Path) -> bool {
    p.is_file()
}

// ---- Linux tool detection: bounded, deterministic, no filesystem scan -----
//
// Snapmaker Orca, OrcaSlicer and FOrcaSlicer all distribute for Linux as
// AppImages (verified against each project's real GitHub releases this
// session) — there is no "Program Files"-equivalent standard install
// location. Two bounded, deterministic sources are checked, matching the
// mandate's own "prefer which/PATH, .desktop entries, known application
// directories" guidance — never a recursive or whole-filesystem scan:
//
//  (a) XDG .desktop entries: the deterministic signal for a user who
//      integrated the AppImage via AppImageLauncher or any other installer
//      that produces one — its Exec= line names the real AppImage path
//      directly, which is more reliable than guessing a filename.
//  (b) A short, fixed list of directories a user is likely to have placed a
//      downloaded AppImage in, single-level (non-recursive) listing only,
//      filtered by filename prefix against a small set of known patterns.

#[cfg(target_os = "linux")]
fn linux_known_dirs() -> Vec<PathBuf> {
    let home = std::env::var("HOME").map(PathBuf::from).ok();
    let mut dirs = Vec::new();
    if let Some(h) = &home {
        dirs.push(h.join("Applications"));
        dirs.push(h.join("AppImages"));
        dirs.push(h.join(".local/bin"));
        dirs.push(h.join("Downloads"));
        dirs.push(h.clone()); // many users just leave a downloaded AppImage in $HOME
    }
    dirs.push(PathBuf::from("/opt"));
    dirs
}

/// Single-level (non-recursive) directory listing, filtered by filename
/// PREFIX match (case-insensitive) against `name_patterns`. Bounded cost,
/// bounded scope — never descends into subdirectories, never reads a
/// directory outside the given list. Sorted before returning: `read_dir`'s
/// order is filesystem-defined, not stable, and `first_existing` picks
/// whichever candidate comes first — a non-deterministic sort order means a
/// non-deterministic choice of which install gets launched.
#[cfg(target_os = "linux")]
fn dir_candidates_in(dirs: &[PathBuf], name_patterns: &[&str]) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for dir in dirs {
        let entries = match std::fs::read_dir(dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let name_lc = entry.file_name().to_string_lossy().to_ascii_lowercase();
            if name_patterns.iter().any(|p| name_lc.starts_with(p)) {
                out.push(entry.path());
            }
        }
    }
    out.sort();
    out
}

#[cfg(target_os = "linux")]
fn linux_dir_candidates(name_patterns: &[&str]) -> Vec<PathBuf> {
    dir_candidates_in(&linux_known_dirs(), name_patterns)
}

/// Parse XDG .desktop files (freedesktop spec) in the standard application
/// directories for an entry whose `Name=` (in `[Desktop Entry]` only — never
/// an `[Desktop Action ...]` block) identifies one of `name_hints`, and
/// return the executable path from its `Exec=` line.
#[cfg(target_os = "linux")]
fn linux_desktop_application_dirs() -> Vec<PathBuf> {
    let home = std::env::var("HOME").map(PathBuf::from).ok();
    let mut dirs = vec![
        PathBuf::from("/usr/share/applications"),
        PathBuf::from("/usr/local/share/applications"),
        PathBuf::from("/var/lib/flatpak/exports/share/applications"),
    ];
    if let Some(h) = &home {
        dirs.push(h.join(".local/share/applications"));
        dirs.push(h.join(".local/share/flatpak/exports/share/applications"));
    }
    dirs
}

/// Letters and digits only, lowercased. The comparison alphabet for matching
/// a tool identity against free text: "FOrcaSlicer", "F-Orca-Slicer" and
/// "forca_slicer" all become "forcaslicer", and — the point of doing this
/// instead of a raw substring search — "forcaslicer" and "orcaslicer" now
/// compare unequal instead of one containing the other.
#[cfg(target_os = "linux")]
fn normalize_ident(text: &str) -> String {
    text.chars().filter(|c| c.is_ascii_alphanumeric()).flat_map(|c| c.to_lowercase()).collect()
}

#[cfg(target_os = "linux")]
fn desktop_entry_candidates_in(dirs: &[PathBuf], name_hints: &[&str]) -> Vec<PathBuf> {
    let targets: Vec<String> = name_hints.iter().map(|h| normalize_ident(h)).collect();
    let mut out = Vec::new();
    for dir in dirs {
        let entries = match std::fs::read_dir(dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("desktop") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else { continue };
            let Some(name) = desktop_entry_name(&text) else { continue };
            let name_norm = normalize_ident(&name);
            // Exact identity match, not "contains": a substring check is what
            // let a FOrcaSlicer entry answer for "orcaslicer" (the tail of
            // "forcaslicer" is literally "orcaslicer") and an OrcaSlicer-
            // ImageMap entry answer for plain "orcaslicer" the same way.
            if !targets.iter().any(|t| *t == name_norm) {
                continue;
            }
            let Some(exec_path) = desktop_entry_exec_path(&text) else { continue };
            // The executable this Exec= line names has to plausibly BE the
            // tool the Name= line just matched — not a launcher that then
            // decides what to run. A Flatpak-exported entry's Exec= starts
            // with `/usr/bin/flatpak run <app-id> ...`: the first token is a
            // real, executable, existing binary, and without this check it
            // would be reported and launched as the slicer itself while
            // Flatpak's own argument convention (an app id, not a file path)
            // means nothing would actually open.
            let basename = exec_path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if !exec_path.is_absolute() || !normalize_ident(basename).contains(&name_norm) {
                continue;
            }
            out.push(exec_path);
        }
    }
    out.sort();
    out
}

#[cfg(target_os = "linux")]
fn linux_desktop_entry_candidates(name_hints: &[&str]) -> Vec<PathBuf> {
    desktop_entry_candidates_in(&linux_desktop_application_dirs(), name_hints)
}

/// The `Name=` value from a .desktop file's `[Desktop Entry]` section only —
/// never from a later `[Desktop Action ...]` block, which names a secondary
/// action ("Open a New Window") rather than the application itself.
#[cfg(target_os = "linux")]
fn desktop_entry_name(desktop_file_text: &str) -> Option<String> {
    let mut in_desktop_entry = false;
    for line in desktop_file_text.lines() {
        let line = line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_desktop_entry = line == "[Desktop Entry]";
            continue;
        }
        if !in_desktop_entry {
            continue;
        }
        if let Some(name) = line.strip_prefix("Name=") {
            let name = name.trim();
            if !name.is_empty() {
                return Some(name.to_string());
            }
        }
    }
    None
}

/// Extract the real executable path from a .desktop file's `Exec=` line, in
/// `[Desktop Entry]` only. The XDG spec permits the command to be quoted
/// (spaces allowed inside `"…"`, `\` escapes the next character) and allows
/// trailing %-codes (`%f`, `%F`, `%u`, `%U`, ...); this returns only the
/// first field — the binary itself — never the whole line, so a placeholder
/// or a trailing argument is never mistaken for the executable path.
#[cfg(target_os = "linux")]
fn desktop_entry_exec_path(desktop_file_text: &str) -> Option<PathBuf> {
    let mut in_desktop_entry = false;
    for line in desktop_file_text.lines() {
        let line = line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_desktop_entry = line == "[Desktop Entry]";
            continue;
        }
        if !in_desktop_entry {
            continue;
        }
        if let Some(rest) = line.strip_prefix("Exec=") {
            return exec_first_token(rest).map(PathBuf::from);
        }
    }
    None
}

/// The first field of an `Exec=` value, honoring the XDG quoting rule: a
/// field wrapped in `"…"` may contain spaces, and `\` inside quotes escapes
/// the next character. Unquoted, the field ends at the first whitespace.
#[cfg(target_os = "linux")]
fn exec_first_token(value: &str) -> Option<String> {
    let mut chars = value.trim_start().chars().peekable();
    let mut token = String::new();
    if chars.peek() == Some(&'"') {
        chars.next();
        while let Some(c) = chars.next() {
            match c {
                '"' => break,
                '\\' => {
                    if let Some(escaped) = chars.next() {
                        token.push(escaped);
                    }
                }
                _ => token.push(c),
            }
        }
    } else {
        for c in chars {
            if c.is_whitespace() {
                break;
            }
            token.push(c);
        }
    }
    if token.is_empty() { None } else { Some(token) }
}

// ---- Ecosystem tool detection ----------------------------------------------
//
// Studio suggests which open-source tool suits a given project (see the engine's
// ecosystem registry). The suggestion is only actionable if the tool is actually
// installed, and "installed" must be a fact, not a guess — so detection is
// exactly the same rule as the Orca handoff: a tool counts as present only when
// one of its known install locations is a real file on disk.
//
// Rust owns this table on purpose. The webview asks to open a tool *by id*; it
// can never hand over an arbitrary executable path to launch. Ids here must match
// the ids in backend/snapstudio_core/data/ecosystem.json.
//
// Install locations are best-effort for the community forks: if a fork installs
// somewhere this table does not list, Studio reports it as not installed and
// offers its download link. Under-claiming is the correct failure direction.
#[cfg(windows)]
fn tool_candidates(id: &str) -> Vec<PathBuf> {
    let program_files = std::env::var("ProgramFiles").unwrap_or_else(|_| r"C:\Program Files".into());
    let program_files_x86 = std::env::var("ProgramFiles(x86)").ok();
    let local_programs = std::env::var("LOCALAPPDATA")
        .ok()
        .map(|la| Path::new(&la).join("Programs"));

    // (directory name, executable name) pairs to try under each install root.
    let specs: &[(&str, &str)] = match id {
        "snapmaker-orca" => &[("Snapmaker_Orca", "snapmaker-orca.exe")],
        "orcaslicer" => &[("OrcaSlicer", "orca-slicer.exe")],
        "forcaslicer" => &[
            ("FOrcaSlicer", "forca-slicer.exe"),
            ("FOrcaSlicer", "snapmaker-orca.exe"),
            ("FOrcaSlicer", "orca-slicer.exe"),
        ],
        "orcaslicer-imagemap" => &[
            ("OrcaSlicer-ImageMap", "orca-slicer.exe"),
            ("OrcaSlicerImageMap", "orca-slicer.exe"),
        ],
        "prusaslicer" => &[("Prusa3D\\PrusaSlicer", "prusa-slicer.exe")],
        _ => &[],
    };

    let mut roots: Vec<PathBuf> = vec![PathBuf::from(&program_files)];
    if let Some(pf86) = program_files_x86 {
        roots.push(PathBuf::from(pf86));
    }
    if let Some(lp) = local_programs {
        roots.push(lp);
    }

    let mut out = Vec::new();
    for root in &roots {
        for (dir, exe) in specs {
            out.push(root.join(dir).join(exe));
        }
    }
    out
}

// Linux: only the tools confirmed to distribute as AppImages get real
// detection (Snapmaker Orca, OrcaSlicer, FOrcaSlicer). PrusaSlicer moved to
// Flatpak-only distribution after 2.8.1, a different launch mechanism
// (`flatpak run <app-id>`, not a direct executable path) — deliberately left
// undetected here rather than forcing a mismatched mechanism onto it.
// orcaslicer-imagemap's real-world distribution was not confirmed, so it
// stays undetected too: under-claiming is the correct failure direction.
/// Drop any candidate whose filename, reduced to letters+digits, contains
/// `fragment` — the tool for excluding a fork's AppImage from a broader
/// sibling's prefix match (e.g. keeping OrcaSlicer-ImageMap out of plain
/// OrcaSlicer's results). A small pure function on purpose: easy to prove
/// correct on its own, apart from real directory scanning.
#[cfg(target_os = "linux")]
fn exclude_by_name_fragment(v: Vec<PathBuf>, fragment: &str) -> Vec<PathBuf> {
    v.into_iter()
        .filter(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            !normalize_ident(name).contains(fragment)
        })
        .collect()
}

#[cfg(target_os = "linux")]
fn tool_candidates(id: &str) -> Vec<PathBuf> {
    let (desktop_hints, dir_patterns): (&[&str], &[&str]) = match id {
        "snapmaker-orca" => (&["snapmaker orca", "snapmaker_orca"], &["snapmaker_orca", "snorca"]),
        "orcaslicer" => (&["orcaslicer"], &["orcaslicer", "orca_slicer", "orca-slicer"]),
        "forcaslicer" => (&["forcaslicer", "forca slicer"], &["forcaslicer", "forca_slicer", "forca-slicer"]),
        _ => (&[], &[]),
    };
    if desktop_hints.is_empty() && dir_patterns.is_empty() {
        return Vec::new();
    }
    let mut v = linux_desktop_entry_candidates(desktop_hints);
    v.extend(linux_dir_candidates(dir_patterns));
    if id == "orcaslicer" {
        // "orcaslicer" as a filename PREFIX also matches OrcaSlicer-ImageMap's
        // own AppImage naming convention. ImageMap is a different tool this
        // table does not (yet) detect; under-claiming is the correct failure
        // direction, never reporting one fork as though it were another.
        v = exclude_by_name_fragment(v, "imagemap");
    }
    v.sort();
    v
}

#[cfg(not(any(windows, target_os = "linux")))]
fn tool_candidates(_id: &str) -> Vec<PathBuf> {
    Vec::new()
}

/// Ids Studio knows how to look for. Kept in sync with the engine registry.
const DETECTABLE_TOOLS: &[&str] = &[
    "snapmaker-orca",
    "orcaslicer",
    "forcaslicer",
    "orcaslicer-imagemap",
    "prusaslicer",
];

/// Map of tool id -> install path, containing only tools genuinely found on disk.
/// A tool that is missing is simply absent from the map; it is never reported
/// with a guessed path.
#[tauri::command]
fn detect_tools() -> std::collections::HashMap<String, String> {
    let mut found = std::collections::HashMap::new();
    for id in DETECTABLE_TOOLS {
        if let Some(p) = first_existing(&tool_candidates(id)) {
            found.insert((*id).to_string(), p.to_string_lossy().into_owned());
        }
    }
    found
}

/// Hand a prepared file to one of the detected tools. Same one-way handoff as the
/// Orca command: the tool is resolved from its id against the table above, the
/// file must exist, and the file is passed as a single argument — no shell, no
/// extra flags, no slicing commands.
#[tauri::command]
fn open_with_tool(tool_id: String, path: String) -> Result<(), String> {
    let file = Path::new(path.trim());
    if path.trim().is_empty() || !file.is_file() {
        return Err("prepared-file-missing".into());
    }
    if !DETECTABLE_TOOLS.contains(&tool_id.as_str()) {
        return Err("tool-not-supported".into());
    }
    let exe = first_existing(&tool_candidates(&tool_id)).ok_or_else(|| "tool-not-found".to_string())?;
    Command::new(&exe)
        .arg(file)
        .spawn()
        .map_err(|e| format!("launch-failed: {e}"))?;
    Ok(())
}

/// Return the path to an installed Snapmaker Orca, or null if none is found.
#[tauri::command]
fn detect_orca() -> Option<String> {
    first_existing(&orca_candidates()).map(|p| p.to_string_lossy().into_owned())
}

/// Hand the prepared 3MF to Snapmaker Orca: launch the verified Orca exe with the
/// file as a single argument. The user drives slicing from there.
#[tauri::command]
fn open_in_orca(path: String) -> Result<(), String> {
    let file = Path::new(path.trim());
    if path.trim().is_empty() || !file.is_file() {
        return Err("prepared-file-missing".into());
    }
    let orca = first_existing(&orca_candidates()).ok_or_else(|| "orca-not-found".to_string())?;
    Command::new(&orca)
        .arg(file)
        .spawn()
        .map_err(|e| format!("launch-failed: {e}"))?;
    Ok(())
}

/// "Close" the locked Model Browser: hide it and blank the page (stop the site).
/// The window itself is kept hidden for reuse — destroying it would force a
/// from-command rebuild, which deadlocks on this stack.
#[tauri::command]
fn close_model_browser(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(MODEL_BROWSER_LABEL) {
        let _ = w.hide();
        if let Ok(blank) = Url::parse("about:blank") {
            let _ = w.navigate(blank);
        }
    }
    Ok(())
}

/// Whether the Model Browser window is currently shown (so the trusted Studio
/// control panel can reflect its state). Hidden == "closed" to the user.
#[tauri::command]
fn is_model_browser_open(app: tauri::AppHandle) -> bool {
    app.get_webview_window(MODEL_BROWSER_LABEL)
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

/// Bring the Model Browser window to the front (Studio-side control only; the
/// remote page never gets a command channel). No-op if it has never been opened.
#[tauri::command]
fn focus_model_browser(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(MODEL_BROWSER_LABEL) {
        let _ = w.show();
        let _ = w.unminimize();
        w.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ---- Open a model passed on the command line --------------------------------
//
// Two things want this. A user who has associated .3mf with Studio, or who picks
// "Open with", expects the file to be there when the window appears. And an
// automated acceptance run needs a way to get a project into the app: the native
// picker is a Win32 common dialog with no DOM, and on this stack invoking it
// without real user input blocks without ever creating a window, so no
// UI-automation client can reach it.
//
// Only a path that exists on disk and carries a model extension is accepted, so
// a stray argument cannot make the app try to open something arbitrary.
fn launch_file_from_args() -> Option<String> {
    std::env::args().skip(1).find_map(|arg| {
        if arg.starts_with('-') {
            return None;
        }
        let path = Path::new(&arg);
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.to_ascii_lowercase());
        match ext.as_deref() {
            // `.gcode` joins the list because Studio can now read a sliced job:
            // the Post-Slice Doctor checks what the printer will actually
            // execute. Studio still never slices one.
            Some("stl") | Some("3mf") | Some("gcode") if path.is_file() => {
                Some(path.to_string_lossy().into_owned())
            }
            _ => None,
        }
    })
}

/// What a release check found. Never fetched unless the user asks for it.
#[derive(serde::Serialize)]
struct UpdateInfo {
    current: String,
    latest: String,
    newer: bool,
    url: String,
    published: String,
}

/// Compare two dotted versions numerically, so 0.10.0 is newer than 0.9.0.
///
/// A pre-release suffix (`0.5.0-beta.1`) sorts before the same release without
/// one, which is the behaviour that matters here: a beta must never look newer
/// than the stable it precedes.
fn is_newer(latest: &str, current: &str) -> bool {
    fn parts(v: &str) -> (Vec<u32>, bool) {
        let trimmed = v.trim_start_matches('v');
        let (core, pre) = match trimmed.split_once('-') {
            Some((c, _)) => (c, true),
            None => (trimmed, false),
        };
        (
            core.split('.')
                .map(|p| p.parse::<u32>().unwrap_or(0))
                .collect(),
            pre,
        )
    }
    let (a, a_pre) = parts(latest);
    let (b, b_pre) = parts(current);
    for i in 0..a.len().max(b.len()) {
        let x = a.get(i).copied().unwrap_or(0);
        let y = b.get(i).copied().unwrap_or(0);
        if x != y {
            return x > y;
        }
    }
    // Same numbers: a release beats a pre-release of itself.
    b_pre && !a_pre
}

/// Ask GitHub whether there is a newer release.
///
/// This is the only thing in Studio that talks to the internet, it happens only
/// when a person presses a button, and it sends nothing but the request itself —
/// no identifiers, no usage, no telemetry. Studio never downloads or installs an
/// update on its own; the answer is a version number and a link.
#[tauri::command]
fn check_for_update() -> Result<UpdateInfo, String> {
    let current = env!("CARGO_PKG_VERSION").to_string();
    let response = ureq::get(
        "https://api.github.com/repos/DVOpenLabs/snapmaker-studio/releases/latest",
    )
    .set("User-Agent", "snapmaker-studio")
    .set("Accept", "application/vnd.github+json")
    .timeout(std::time::Duration::from_secs(10))
    .call()
    .map_err(|e| format!("could not reach GitHub: {e}"))?;

    let body: serde_json::Value = response
        .into_json()
        .map_err(|e| format!("could not read GitHub's answer: {e}"))?;

    let latest = body
        .get("tag_name")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .trim_start_matches('v')
        .to_string();
    if latest.is_empty() {
        return Err("GitHub did not name a release".into());
    }

    Ok(UpdateInfo {
        newer: is_newer(&latest, &current),
        current,
        url: body
            .get("html_url")
            .and_then(|v| v.as_str())
            .unwrap_or("https://github.com/DVOpenLabs/snapmaker-studio/releases/latest")
            .to_string(),
        published: body
            .get("published_at")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        latest,
    })
}

/// The model this launch was asked to open, if any. The frontend calls this once
/// at startup; returning null is the ordinary case.
#[tauri::command]
fn get_launch_file() -> Option<String> {
    launch_file_from_args()
}

struct ApiState(Mutex<ApiInfo>);

#[tauri::command]
fn get_api_info(state: State<ApiState>) -> ApiInfo {
    state.0.lock().unwrap().clone()
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(ApiState(Mutex::new(ApiInfo::default())))
        .manage(SidecarProc(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            get_api_info,
            open_model_browser,
            close_model_browser,
            is_model_browser_open,
            focus_model_browser,
            detect_orca,
            open_in_orca,
            detect_tools,
            open_with_tool,
            get_launch_file,
            check_for_update
        ])
        .setup(|app| {
            let (info, child) = spawn_sidecar(app.handle());
            *app.state::<ApiState>().0.lock().unwrap() = info;
            *app.state::<SidecarProc>().0.lock().unwrap() = Some(child);
            // Pre-build the locked Model Browser window here on the main thread
            // (hidden). It MUST be created at startup — building it from a command
            // deadlocks on this Tauri/wry/WebView2 stack. Commands only navigate it.
            if let Err(e) = build_model_browser_window(&app.handle()) {
                eprintln!("[model-browser] startup build failed: {e}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Snapmaker Studio");

    app.run(|app_handle, event| {
        // Closing the MAIN window must end the whole app — it did not,
        // silently, since beta.13. Tauri only raises RunEvent::Exit when its
        // window map becomes empty, and the Model Browser (built hidden at
        // startup, its own CloseRequested handler always calls
        // prevent_close()+hide() so it can be reused) means that map is
        // NEVER empty: the user closes the visible window, the process and
        // its sidecar are left running in the background until something
        // else kills them. Confirmed against a real built release binary,
        // not inferred: closing the main window left the process and both
        // sidecar processes alive 30+ seconds later. Explicitly requesting
        // exit here is what makes RunEvent::Exit (and therefore
        // shutdown_sidecar below) reachable at all via the path a real user
        // takes; every existing "zero-orphan" proof up to this point only
        // covered process being killed outright, not a normal window close.
        if let RunEvent::WindowEvent { label, event: WindowEvent::Destroyed, .. } = &event {
            if label == "main" {
                app_handle.exit(0);
            }
        }
        // Bring the sidecar down when the app exits so no orphan process
        // survives. See sidecar::shutdown_sidecar for what "bring down" means
        // per platform (Linux: graceful /shutdown then bounded killpg;
        // Windows: unchanged kill()+wait(), backed by the Job Object).
        if let RunEvent::Exit = event {
            if let Some(child) = app_handle.state::<SidecarProc>().0.lock().unwrap().take() {
                let info = app_handle.state::<ApiState>().0.lock().unwrap().clone();
                shutdown_sidecar(child, &info);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_existing_returns_none_when_no_candidate_exists() {
        let candidates = vec![
            PathBuf::from(r"C:\does\not\exist\snapmaker-orca.exe"),
            PathBuf::from("/does/not/exist/snapmaker-orca"),
        ];
        assert!(first_existing(&candidates).is_none());
    }

    #[test]
    fn first_existing_picks_the_first_real_file() {
        // The test binary itself is guaranteed to exist on disk.
        let real = std::env::current_exe().expect("current exe");
        let candidates = vec![
            PathBuf::from(r"C:\nope\snapmaker-orca.exe"),
            real.clone(),
        ];
        assert_eq!(first_existing(&candidates), Some(real));
    }

    #[cfg(windows)]
    #[test]
    fn windows_candidates_include_verified_program_files_path() {
        let c = orca_candidates();
        assert!(!c.is_empty());
        let tail = Path::new("Snapmaker_Orca").join("snapmaker-orca.exe");
        assert!(c.iter().any(|p| p.ends_with(&tail)));
    }

    #[cfg(not(any(windows, target_os = "linux")))]
    #[test]
    fn non_windows_non_linux_has_no_candidates() {
        assert!(orca_candidates().is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn is_usable_executable_rejects_non_executable_file() {
        let dir = std::env::temp_dir().join(format!("snapstudio-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("plain.txt");
        std::fs::write(&file, b"not executable").unwrap();
        assert!(!is_usable_executable(&file));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[cfg(unix)]
    #[test]
    fn is_usable_executable_accepts_chmod_plus_x_file() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("snapstudio-test-x-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("tool.AppImage");
        std::fs::write(&file, b"#!/bin/sh\n").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert!(is_usable_executable(&file));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[cfg(target_os = "linux")]
    mod linux_detection {
        use super::*;

        fn scratch_dir(name: &str) -> PathBuf {
            let dir = std::env::temp_dir().join(format!("snapstudio-test-{name}-{}", std::process::id()));
            std::fs::create_dir_all(&dir).unwrap();
            dir
        }

        #[test]
        fn desktop_entry_exec_path_takes_only_the_binary_token() {
            let text = "[Desktop Entry]\nName=Snapmaker Orca\nExec=/home/u/Apps/snapmaker-orca.AppImage %f\nType=Application\n";
            assert_eq!(
                desktop_entry_exec_path(text),
                Some(PathBuf::from("/home/u/Apps/snapmaker-orca.AppImage"))
            );
        }

        #[test]
        fn desktop_entry_exec_path_strips_quotes_and_keeps_the_space() {
            let text = "[Desktop Entry]\nName=OrcaSlicer\nExec=\"/home/u/My Apps/orca-slicer.AppImage\" %U\n";
            assert_eq!(
                desktop_entry_exec_path(text),
                Some(PathBuf::from("/home/u/My Apps/orca-slicer.AppImage"))
            );
        }

        #[test]
        fn desktop_entry_exec_path_unquoted_stops_at_first_space() {
            let text = "[Desktop Entry]\nName=OrcaSlicer\nExec=/opt/orcaslicer.AppImage %f\n";
            assert_eq!(desktop_entry_exec_path(text), Some(PathBuf::from("/opt/orcaslicer.AppImage")));
        }

        #[test]
        fn desktop_entry_exec_path_honours_a_backslash_escape_inside_quotes() {
            let text = "[Desktop Entry]\nName=X\nExec=\"/opt/weird\\\"name.AppImage\" %f\n";
            assert_eq!(desktop_entry_exec_path(text), Some(PathBuf::from("/opt/weird\"name.AppImage")));
        }

        #[test]
        fn desktop_entry_exec_path_none_when_missing() {
            assert_eq!(desktop_entry_exec_path("[Desktop Entry]\nName=Something\n"), None);
        }

        #[test]
        fn desktop_entry_exec_path_ignores_a_line_before_any_section_header() {
            // Regression: a bare `?` on a non-matching line used to abort the
            // whole scan at the first line that was not "Exec=", instead of
            // moving on to the next one.
            assert_eq!(desktop_entry_exec_path("Exec=/opt/evil\n"), None);
        }

        #[test]
        fn desktop_entry_exec_path_ignores_an_action_sections_exec() {
            // A [Desktop Action …] block names a secondary action ("open a
            // new window"), not the application — using its Exec= would
            // launch the wrong thing.
            let text = "[Desktop Entry]\nName=X\n[Desktop Action NewWindow]\nExec=/opt/orcaslicer.AppImage --new-window\n";
            assert_eq!(desktop_entry_exec_path(text), None);
        }

        #[test]
        fn desktop_entry_candidates_matches_by_name_hint_and_ignores_others() {
            let dir = scratch_dir("desktop");
            std::fs::write(
                dir.join("snapmaker-orca.desktop"),
                "[Desktop Entry]\nName=Snapmaker Orca\nExec=/opt/snapmaker-orca.AppImage %f\n",
            )
            .unwrap();
            std::fs::write(
                dir.join("unrelated.desktop"),
                "[Desktop Entry]\nName=Text Editor\nExec=/usr/bin/gedit %f\n",
            )
            .unwrap();
            std::fs::write(dir.join("not-a-desktop-file.txt"), "Exec=/opt/evil\n").unwrap();

            let found = desktop_entry_candidates_in(&[dir.clone()], &["snapmaker orca"]);
            assert_eq!(found, vec![PathBuf::from("/opt/snapmaker-orca.AppImage")]);
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn desktop_entry_candidates_skips_unreadable_directory() {
            let missing = PathBuf::from("/does/not/exist/applications");
            assert!(desktop_entry_candidates_in(&[missing], &["snapmaker orca"]).is_empty());
        }

        #[test]
        fn dir_candidates_matches_appimage_by_prefix_case_insensitively() {
            let dir = scratch_dir("dircand");
            std::fs::write(dir.join("SnapMaker_Orca-1.2.3.AppImage"), b"").unwrap();
            std::fs::write(dir.join("some-other-tool.AppImage"), b"").unwrap();

            let found = dir_candidates_in(&[dir.clone()], &["snapmaker_orca"]);
            assert_eq!(found, vec![dir.join("SnapMaker_Orca-1.2.3.AppImage")]);
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn linux_known_dirs_includes_home_locations_when_home_is_set() {
            if std::env::var("HOME").is_ok() {
                let dirs = linux_known_dirs();
                assert!(dirs.iter().any(|d| d.ends_with("Downloads")));
                assert!(dirs.iter().any(|d| d.ends_with(".local/bin")));
            }
        }

        // --- name collisions (Opus review of b4dc65d: BLOCK, CRITICAL) ------

        #[test]
        fn forcaslicer_desktop_entry_is_not_matched_as_plain_orcaslicer() {
            // "forcaslicer" contains "orcaslicer" as a literal substring
            // (forCASLICER) — a .contains() match on raw file text answered
            // for the wrong tool. Matching now requires the Name= value to
            // equal a hint exactly, after both are reduced to letters+digits.
            let dir = scratch_dir("collision-forca");
            std::fs::write(
                dir.join("forcaslicer.desktop"),
                "[Desktop Entry]\nName=FOrcaSlicer\nExec=/opt/forcaslicer.AppImage %f\n",
            )
            .unwrap();
            let found = desktop_entry_candidates_in(&[dir.clone()], &["orcaslicer"]);
            assert!(found.is_empty(), "FOrcaSlicer must not answer for plain orcaslicer: {found:?}");
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn imagemap_desktop_entry_is_not_matched_as_plain_orcaslicer() {
            let dir = scratch_dir("collision-imagemap");
            std::fs::write(
                dir.join("imagemap.desktop"),
                "[Desktop Entry]\nName=OrcaSlicer-ImageMap\nExec=/opt/orcaslicer-imagemap.AppImage %f\n",
            )
            .unwrap();
            let found = desktop_entry_candidates_in(&[dir.clone()], &["orcaslicer"]);
            assert!(found.is_empty(), "ImageMap must not answer for plain orcaslicer: {found:?}");
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn exclude_by_name_fragment_drops_only_the_matching_filename() {
            let v = vec![
                PathBuf::from("/opt/OrcaSlicer-ImageMap-2.0.0.AppImage"),
                PathBuf::from("/opt/OrcaSlicer-2.4.2.AppImage"),
            ];
            assert_eq!(
                exclude_by_name_fragment(v, "imagemap"),
                vec![PathBuf::from("/opt/OrcaSlicer-2.4.2.AppImage")]
            );
        }

        #[test]
        fn imagemap_appimage_filename_is_excluded_from_the_plain_orcaslicer_dir_scan() {
            let dir = scratch_dir("collision-imagemap-dir");
            std::fs::write(dir.join("orcaslicer-imagemap-2.0.0.AppImage"), b"").unwrap();
            std::fs::write(dir.join("orcaslicer-2.4.2.AppImage"), b"").unwrap();
            let raw = dir_candidates_in(&[dir.clone()], &["orcaslicer"]);
            assert_eq!(raw.len(), 2, "both files should match the bare prefix: {raw:?}");
            let filtered = exclude_by_name_fragment(raw, "imagemap");
            assert_eq!(filtered, vec![dir.join("orcaslicer-2.4.2.AppImage")]);
            std::fs::remove_dir_all(&dir).ok();
        }

        // --- wrapper/launcher programs (Opus review: BLOCK, CRITICAL) -------

        #[test]
        fn a_flatpak_wrapper_exec_line_is_never_reported_as_the_slicer_itself() {
            let dir = scratch_dir("flatpak-wrapper");
            std::fs::write(
                dir.join("com.github.softfever.orcaslicer.desktop"),
                "[Desktop Entry]\nName=OrcaSlicer\nExec=/usr/bin/flatpak run --branch=stable --arch=x86_64 com.github.SoftFever.OrcaSlicer @@u %u @@\n",
            )
            .unwrap();
            let found = desktop_entry_candidates_in(&[dir.clone()], &["orcaslicer"]);
            assert!(found.is_empty(),
                "a flatpak-wrapped entry must not be reported as a directly-launchable OrcaSlicer: {found:?}");
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn a_relative_exec_path_is_refused() {
            let dir = scratch_dir("relative-exec");
            std::fs::write(
                dir.join("x.desktop"),
                "[Desktop Entry]\nName=OrcaSlicer\nExec=orcaslicer.AppImage %f\n",
            )
            .unwrap();
            let found = desktop_entry_candidates_in(&[dir.clone()], &["orcaslicer"]);
            assert!(found.is_empty());
            std::fs::remove_dir_all(&dir).ok();
        }

        // --- deterministic ordering (Opus review: MEDIUM) --------------------

        #[test]
        fn dir_candidates_are_sorted_not_filesystem_order() {
            let dir = scratch_dir("sort-order");
            std::fs::write(dir.join("orcaslicer-zzz.AppImage"), b"").unwrap();
            std::fs::write(dir.join("orcaslicer-aaa.AppImage"), b"").unwrap();
            std::fs::write(dir.join("orcaslicer-mmm.AppImage"), b"").unwrap();
            let found = dir_candidates_in(&[dir.clone()], &["orcaslicer"]);
            let names: Vec<_> = found.iter().map(|p| p.file_name().unwrap().to_str().unwrap()).collect();
            assert_eq!(names, vec!["orcaslicer-aaa.AppImage", "orcaslicer-mmm.AppImage", "orcaslicer-zzz.AppImage"]);
            std::fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn normalize_ident_collapses_case_and_punctuation() {
            assert_eq!(normalize_ident("Snapmaker Orca"), "snapmakerorca");
            assert_eq!(normalize_ident("snapmaker_orca"), "snapmakerorca");
            assert_eq!(normalize_ident("FOrcaSlicer"), "forcaslicer");
            assert_ne!(normalize_ident("FOrcaSlicer"), normalize_ident("OrcaSlicer"));
        }
    }
}
