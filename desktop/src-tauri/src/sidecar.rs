//! Sidecar process: spawn, handshake, and lifecycle.
//!
//! This module is the platform seam for the Python engine sidecar. Windows
//! behaviour is unchanged from before this extraction. Linux ships the
//! PyInstaller `onedir` build via Tauri's `bundle.resources` (not
//! `externalBin`, which cannot hold a directory — see
//! `desktop/src-tauri/tauri.linux.conf.json` and `desktop/scripts/build-sidecar.sh`),
//! so locating it needs `AppHandle::path().resource_dir()`, not the
//! Windows-shaped `current_exe().parent()` join. Linux process-lifecycle work
//! (process-group kill, the parent-death signal, the stdin EOF lifeline) lands
//! here behind `#[cfg(unix)]` in a later step, parallel to the existing
//! `#[cfg(windows)]` Job Object path.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
#[cfg(all(not(debug_assertions), target_os = "linux"))]
use tauri::Manager;

#[derive(Default, Clone, Serialize, Deserialize)]
pub struct ApiInfo {
    pub port: u16,
    pub token: String,
}

pub struct SidecarProc(pub Mutex<Option<Child>>);

/// Build the command that launches the engine sidecar, choosing dev vs bundled.
fn sidecar_command(app: &AppHandle) -> Command {
    #[cfg(debug_assertions)]
    {
        let _ = app; // only the Linux prod branch below needs it
        // DEV: live engine from <repo>/backend. CARGO_MANIFEST_DIR is
        // <repo>/desktop/src-tauri, so ../../backend points at the engine.
        let backend = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("backend");
        // Dev mode uses whatever `python` (or `SNAPSTUDIO_PYTHON` if set and
        // non-empty) resolves to on PATH. On a system where the default isn't
        // >=3.13 with the backend installed, set SNAPSTUDIO_PYTHON to an
        // explicit interpreter path.
        let python = std::env::var("SNAPSTUDIO_PYTHON")
            .ok()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| "python".to_string());
        let mut cmd = Command::new(python);
        cmd.args(["-m", "snapstudio_api"]).current_dir(backend);
        cmd
    }
    #[cfg(all(not(debug_assertions), target_os = "linux"))]
    {
        // PROD (Linux): the onedir build ships as a Tauri bundle resource
        // (bundle.resources in tauri.linux.conf.json), not externalBin — Tauri's
        // resource_dir() is the only reliable way to find it once installed,
        // since it can land under /usr/lib/<product>/ (.deb) or another
        // package-manager-specific location, never a fixed path relative to
        // the app's own executable the way externalBin's sibling-file
        // convention assumes.
        let resource_dir = app
            .path()
            .resource_dir()
            .expect("resource_dir (Linux sidecar resource)");
        let sidecar_dir = resource_dir.join("snapstudio-api");
        let exe = sidecar_dir.join("snapstudio-api-x86_64-unknown-linux-gnu");
        Command::new(exe)
    }
    #[cfg(all(not(debug_assertions), not(target_os = "linux")))]
    {
        let _ = app; // only the Linux prod branch above needs it
        // PROD (Windows): frozen sidecar sits beside the app exe (Tauri strips
        // the target triple from the externalBin name when bundling).
        let exe_dir = std::env::current_exe()
            .expect("current_exe")
            .parent()
            .expect("exe parent")
            .to_path_buf();
        let mut cmd = Command::new(exe_dir.join("snapstudio-api.exe"));
        #[cfg(windows)]
        {
            // CREATE_NO_WINDOW: keep the console sidecar invisible while still
            // giving it a real stdout pipe for the handshake.
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000);
        }
        cmd
    }
}

/// Tie the sidecar (and any children it spawns — e.g. the PyInstaller onefile
/// bootloader + its Python child) to a Windows job object that is killed when
/// its last handle closes. Since this process holds the only handle, the whole
/// sidecar tree dies when the app exits for ANY reason: graceful close, crash,
/// or force-kill. This is the authoritative no-orphan guarantee.
#[cfg(windows)]
fn bind_to_kill_on_close_job(child: &Child) {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        AssignProcessToJobObject(job, child.as_raw_handle() as _);
        // Keep the job handle open for the app's whole lifetime: the OS closes it
        // when this process dies, which kills the sidecar tree. The handle is a raw
        // pointer (Copy), so there is nothing to drop — binding to `_` is enough.
        let _ = job;
    }
}

/// Spawn the sidecar and block until its handshake line is read.
pub fn spawn_sidecar(app: &AppHandle) -> (ApiInfo, Child) {
    let mut child = sidecar_command(app)
        // The sidecar watches this PID and self-exits if the app dies for any
        // reason (close, crash, force-kill) — belt to the exit-handler braces.
        .env("SNAPSTUDIO_PARENT_PID", std::process::id().to_string())
        .stdout(Stdio::piped())
        .spawn()
        .expect("failed to start snapstudio_api sidecar");

    #[cfg(windows)]
    bind_to_kill_on_close_job(&child);

    let stdout = child.stdout.take().expect("sidecar stdout");
    let mut line = String::new();
    BufReader::new(stdout)
        .read_line(&mut line)
        .expect("failed to read sidecar handshake");
    let info: ApiInfo = serde_json::from_str(line.trim()).expect("invalid sidecar handshake");

    (info, child)
}
