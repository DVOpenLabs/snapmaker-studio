//! Sidecar process: spawn, handshake, and lifecycle.
//!
//! This module is the platform seam for the Python engine sidecar. Behaviour on
//! Windows is unchanged from before this extraction — this is a pure move, not a
//! rewrite. Linux-specific process-lifecycle work (process-group kill, the
//! parent-death signal, the stdin EOF lifeline) lands here behind `#[cfg(unix)]`
//! in a later step, parallel to the existing `#[cfg(windows)]` Job Object path.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[derive(Default, Clone, Serialize, Deserialize)]
pub struct ApiInfo {
    pub port: u16,
    pub token: String,
}

pub struct SidecarProc(pub Mutex<Option<Child>>);

/// Build the command that launches the engine sidecar, choosing dev vs bundled.
fn sidecar_command() -> Command {
    #[cfg(debug_assertions)]
    {
        // DEV: live engine from <repo>/backend. CARGO_MANIFEST_DIR is
        // <repo>/desktop/src-tauri, so ../../backend points at the engine.
        let backend = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("backend");
        let mut cmd = Command::new("python");
        cmd.args(["-m", "snapstudio_api"]).current_dir(backend);
        cmd
    }
    #[cfg(not(debug_assertions))]
    {
        // PROD: frozen sidecar sits beside the app exe (Tauri strips the target
        // triple from the externalBin name when bundling).
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
pub fn spawn_sidecar() -> (ApiInfo, Child) {
    let mut child = sidecar_command()
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
