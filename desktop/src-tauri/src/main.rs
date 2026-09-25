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
// The sidecar child is tracked in app state and killed on exit — no orphan process
// (Windows: the Job Object binding in sidecar.rs; Linux: the exit-handler kill()
// below only, today — process-group kill and the parent-death lifeline are L4).

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

#[cfg(not(windows))]
fn orca_candidates() -> Vec<PathBuf> {
    Vec::new()
}

/// First candidate that is a real file on disk (never a guessed path).
fn first_existing(candidates: &[PathBuf]) -> Option<PathBuf> {
    candidates.iter().find(|p| p.is_file()).cloned()
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

#[cfg(not(windows))]
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
        "https://api.github.com/repos/DeadlyVirusIn/snapmaker-studio/releases/latest",
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
            .unwrap_or("https://github.com/DeadlyVirusIn/snapmaker-studio/releases/latest")
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

    #[cfg(not(windows))]
    #[test]
    fn non_windows_has_no_candidates() {
        assert!(orca_candidates().is_empty());
    }
}
