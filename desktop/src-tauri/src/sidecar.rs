//! Sidecar process: spawn, handshake, and lifecycle.
//!
//! This module is the platform seam for the Python engine sidecar. Windows
//! behaviour is unchanged from before this extraction: `bind_to_kill_on_close_job`
//! (a Job Object bound at spawn) is still the authoritative no-orphan
//! guarantee there, and `shutdown_sidecar`'s non-Linux branch is the same
//! bare `kill()`+`wait()` the old inline handler in `main.rs` used. Linux
//! ships the PyInstaller `onedir` build via Tauri's `bundle.resources` (not
//! `externalBin`, which cannot hold a directory — see
//! `desktop/src-tauri/tauri.linux.conf.json` and `desktop/scripts/build-sidecar.sh`),
//! so locating it needs `AppHandle::path().resource_dir()`, not the
//! Windows-shaped `current_exe().parent()` join.
//!
//! L4 zero-orphan lifecycle (Linux): three independent layers, because no
//! single one covers every way the app can stop existing.
//!   - `configure_linux_lifecycle` arms PDEATHSIG on the sidecar itself
//!     (SIGTERM, delivered by the kernel) and gives it its own process
//!     group. This is the ONLY layer that runs when the app dies by signal
//!     (SIGTERM/SIGKILL) — no Rust cleanup code executes in that case at
//!     all, `RunEvent::Exit` never fires for an external signal.
//!   - `shutdown_sidecar` runs when Rust cleanup DOES execute (the app
//!     decided to quit on its own): ask the sidecar to shut down cleanly
//!     over loopback, then fall back to `killpg` (SIGTERM, then SIGKILL)
//!     bounded by a short deadline.
//!   - The sidecar's own stdin-EOF lifeline (armed by
//!     `backend/snapstudio_api/_lifeline.py`, wired up by keeping the
//!     `Stdio::piped()` write end open in `Child` for the app's whole life)
//!     is the one guarantee that holds even in the narrow fork()-to-exec()
//!     window where PDEATHSIG cannot yet be armed: the kernel closes every
//!     fd a process held, unconditionally, on any exit path it takes.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
#[cfg(target_os = "linux")]
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
#[cfg(all(not(debug_assertions), target_os = "linux"))]
use tauri::Manager;
#[cfg(target_os = "linux")]
use std::os::unix::process::CommandExt;

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
        let mut cmd = Command::new(exe);
        configure_linux_lifecycle(&mut cmd, std::process::id());
        cmd
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

/// Arm this Linux sidecar's L4 zero-orphan guarantees before it execs.
///
/// PDEATHSIG is armed in a `pre_exec` closure, which runs in the forked child
/// AFTER `fork()` but BEFORE `exec()` — the standard place for it. Right
/// after arming it, re-check `getppid()` against the PID captured before
/// `spawn()`: if the real parent already died in the fork()-to-prctl() gap,
/// the signal was armed too late to ever be delivered for that death, and
/// this process has already been silently reparented (`getppid()` no longer
/// matches). Exit immediately in that case rather than run on undetected —
/// the stdin lifeline (armed separately, by the sidecar itself once running;
/// see `backend/snapstudio_api/_lifeline.py`) is what closes the very last
/// sliver of that race that even this check cannot: the caller must keep the
/// `Stdio::piped()` stdin's write end open in the returned `Child` for the
/// app's entire life, never `.take()` it.
///
/// `process_group(0)` makes the sidecar its own process-group leader, so a
/// bounded `killpg` from `shutdown_sidecar` reaches its whole tree in one
/// call — correct today (the onedir build has no bootloader-hop child) and
/// stays correct if that ever changes.
///
/// Only called from the release (prod) Linux branch of `sidecar_command` —
/// `#[cfg_attr(debug_assertions, allow(dead_code))]` silences the resulting
/// dead-code lint on a Linux DEBUG build, where this is genuinely unused (dev
/// mode runs the live `backend/` tree directly, not the frozen sidecar).
#[cfg(target_os = "linux")]
#[cfg_attr(debug_assertions, allow(dead_code))]
fn configure_linux_lifecycle(cmd: &mut Command, parent_pid: u32) {
    let parent_pid = parent_pid as libc::pid_t;
    unsafe {
        cmd.pre_exec(move || {
            if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            if libc::getppid() != parent_pid {
                libc::_exit(1);
            }
            Ok(())
        });
    }
    cmd.process_group(0);
    cmd.env("SNAPSTUDIO_PARENT_LIFELINE", "stdin-v1");
    cmd.stdin(Stdio::piped());
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

/// Bring the sidecar down when the app is exiting via its own `RunEvent::Exit`
/// — i.e. whenever any Rust cleanup code runs at all (graceful close, menu
/// quit). This never runs for an external SIGTERM/SIGKILL of the app itself;
/// those are covered on Linux by `configure_linux_lifecycle` and the sidecar's
/// own stdin lifeline, and on Windows by the Job Object bound in
/// `bind_to_kill_on_close_job`.
pub fn shutdown_sidecar(mut child: Child, info: &ApiInfo) {
    #[cfg(target_os = "linux")]
    {
        // Already gone (crashed on its own before the app exited)? Don't
        // POST /shutdown in that case: the port it held is free the moment
        // it exits, and a since-restarted, unrelated local service could
        // occupy it by the time this runs — sending it our auth token for a
        // route it never asked for is pointless at best.
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }

        // Ask nicely first: POST /shutdown lets the sidecar's own
        // ThreadingHTTPServer wind down cleanly instead of being signalled.
        // A short timeout and an ignored error are correct here — if the
        // sidecar dies between the check above and this call, or never
        // answers, the wait loop below notices immediately via try_wait()
        // and this function still returns promptly either way.
        let _ = ureq::post(&format!("http://127.0.0.1:{}/shutdown", info.port))
            .set("X-Auth-Token", &info.token)
            .timeout(Duration::from_millis(1500))
            .call();

        if wait_briefly(&mut child, Duration::from_millis(2500)) {
            return;
        }

        // Forced fallback, scoped to the sidecar's OWN process group
        // (configure_linux_lifecycle's process_group(0)) — never anything
        // wider. SIGTERM first, bounded wait, then SIGKILL as the last
        // resort so a misbehaving sidecar can never outlive the app.
        let pgid = child.id() as libc::pid_t;
        unsafe {
            libc::killpg(pgid, libc::SIGTERM);
        }
        if wait_briefly(&mut child, Duration::from_millis(1000)) {
            return;
        }
        unsafe {
            libc::killpg(pgid, libc::SIGKILL);
        }
        // Belt for a debug build (configure_linux_lifecycle is release-only,
        // so a debug sidecar is not its own process-group leader and killpg
        // above is a silent no-op/ESRCH there): a direct kill() still
        // reaches the one process we actually hold a handle to, so
        // child.wait() below can never block forever.
        let _ = child.kill();
        let _ = child.wait();
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = info; // only the Linux path needs the loopback handshake info
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Poll `try_wait()` until the child has exited or `deadline` elapses.
/// Returns true the moment it is confirmed gone (and reaped).
#[cfg(target_os = "linux")]
fn wait_briefly(child: &mut Child, deadline: Duration) -> bool {
    let until = Instant::now() + deadline;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Ok(None) => {}
            Err(_) => return false,
        }
        if Instant::now() >= until {
            return false;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

// No CI runtime step drives the graceful RunEvent::Exit path (every zero-
// orphan CI check kills the app by signal, which never fires it — see
// linux-support-ci.yml), so shutdown_sidecar()'s own forced-fallback branch
// gets no coverage anywhere else. This exercises it directly: nothing
// listens on the bogus port, so the /shutdown POST fails and the killpg
// fallback is what actually has to end the process, bounded by its own
// deadline rather than this test's.
#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[test]
    fn shutdown_sidecar_forced_fallback_ends_a_process_with_no_shutdown_route() {
        let mut cmd = Command::new("sleep");
        cmd.arg("300");
        cmd.process_group(0);
        let child = cmd.spawn().expect("failed to spawn test sleep process");
        let pid = child.id();

        // Port 1 is a reserved, never-listened-on port — the POST is
        // guaranteed to fail fast (connection refused), forcing the killpg
        // fallback path rather than the graceful one.
        let info = ApiInfo { port: 1, token: "unused".to_string() };

        let started = Instant::now();
        shutdown_sidecar(child, &info);
        let elapsed = started.elapsed();

        assert!(
            elapsed < Duration::from_secs(6),
            "shutdown_sidecar took {elapsed:?}, expected it bounded well under its own ~5s of internal deadlines"
        );
        // shutdown_sidecar's own child.wait() already reaped it — kill(pid, 0)
        // (the standard existence probe: signal 0 sends nothing, just checks
        // whether the PID is still valid) confirms nothing is left, not even
        // an unreaped zombie.
        let still_there = unsafe { libc::kill(pid as libc::pid_t, 0) == 0 };
        assert!(!still_there, "process {pid} should be gone after shutdown_sidecar's forced fallback");
    }

    // The test above calls process_group(0) itself, which makes killpg
    // succeed on the first try — that's the RELEASE shape (configure_linux_-
    // lifecycle already does the same thing before spawn), which was never
    // the scenario M1 guarded against. A Linux DEBUG sidecar never gets
    // process_group(0) at all (configure_linux_lifecycle only runs in the
    // release branch of sidecar_command), so its real process group is
    // whatever group THIS process is in — not child.id() — and killpg(pgid =
    // child.id(), ...) targets a group nothing belongs to (ESRCH, ignored).
    // Without the direct child.kill() belt in shutdown_sidecar, the final
    // child.wait() would then block on a process nothing just sent a signal
    // to. This test reproduces exactly that: no process_group(0) call at
    // all, so it only passes because of the child.kill() belt, not because
    // of killpg.
    #[test]
    fn shutdown_sidecar_ends_a_process_that_never_got_its_own_process_group() {
        let mut cmd = Command::new("sleep");
        cmd.arg("300");
        // No process_group(0) here — this is the point of the test.
        let child = cmd.spawn().expect("failed to spawn test sleep process");
        let pid = child.id();

        let info = ApiInfo { port: 1, token: "unused".to_string() };

        let started = Instant::now();
        shutdown_sidecar(child, &info);
        let elapsed = started.elapsed();

        assert!(
            elapsed < Duration::from_secs(6),
            "shutdown_sidecar took {elapsed:?}, expected it bounded even when killpg can't reach the process"
        );
        let still_there = unsafe { libc::kill(pid as libc::pid_t, 0) == 0 };
        assert!(!still_there, "process {pid} (no process group of its own) should still be gone — the direct child.kill() belt must have caught it");
    }
}
