// Model Connect policy: which hosts the in-app Model Browser may reach, and how a
// browser-initiated download is accepted into Studio's own downloads folder.
//
// Three separate concepts, each with the minimum permission it needs:
//   * SITE hosts      - the six approved model sites (browsing).
//   * DOWNLOAD hosts  - the CDNs those sites hand files out from (navigation only so
//                       a browser-initiated download can start).
//   * AUTH hosts      - sign-in / identity-provider hosts (same-window navigation only
//                       unless a popup is proven necessary).
// Everything else stays blocked. The remote page has no Tauri IPC (no capability is
// granted to the `model-browser` label) and Studio never reads cookies or tokens.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

use tauri::Url;

pub const SITE_HOSTS: &[&str] = &[
    "printables.com",
    "thingiverse.com",
    "myminifactory.com",
    "cults3d.com",
    "thangs.com",
    "makerworld.com",
];

/// File hosts a site hands downloads out from, each observed live (never guessed): a Printables
/// "Download" navigates to files.printables.com; MakerWorld's own download button navigates to
/// makerworld.bblmw.com (read from the blocked-hosts log, hostname only).
pub const DOWNLOAD_HOSTS: &[&str] = &["files.printables.com", "makerworld.bblmw.com"];

/// One sign-in host and the paths on it that may be reached. `path_ok` keeps a login
/// host from becoming general browsing of that company's whole site.
pub struct AuthRule {
    pub host: &'static str,
    pub path_ok: fn(&str) -> bool,
}

fn any_path(_: &str) -> bool {
    true
}

/// `/sign-in` or `/<locale>/sign-in` (for example `/en-us/sign-in`) on Bambu Lab's account site.
pub fn bambu_signin_path(path: &str) -> bool {
    let mut segs = path.trim_matches('/').split('/');
    let first = segs.next().unwrap_or("");
    let is_locale = |s: &str| {
        let b = s.as_bytes();
        (b.len() == 2 && b.iter().all(|c| c.is_ascii_lowercase()))
            || (b.len() == 5 && b[2] == b'-' && b[..2].iter().chain(&b[3..]).all(|c| c.is_ascii_lowercase()))
    };
    match (first, segs.next(), segs.next()) {
        ("sign-in", None, _) => true,
        (loc, Some("sign-in"), None) if is_locale(loc) => true,
        _ => false,
    }
}

/// Sign-in hosts, observed in the live spike: Printables signs in at Prusa Account (same
/// window, and "Continue with Google" is a same-window redirect to accounts.google.com);
/// MakerWorld signs in at bambulab.com/<locale>/sign-in and returns to makerworld.com.
pub const AUTH_RULES: &[AuthRule] = &[
    AuthRule { host: "account.prusa3d.com", path_ok: any_path },
    AuthRule { host: "bambulab.com", path_ok: bambu_signin_path },
    AuthRule { host: "accounts.google.com", path_ok: any_path },
];

pub fn host_matches(host: &str, domain: &str) -> bool {
    let h = host.to_ascii_lowercase();
    h == domain || h.ends_with(&format!(".{domain}"))
}

fn matches_any(url: &Url, list: &[&str]) -> bool {
    match url.host_str() {
        Some(h) => list.iter().any(|d| host_matches(h, d)),
        None => false,
    }
}

pub fn is_site(url: &Url) -> bool {
    url.scheme() == "https" && matches_any(url, SITE_HOSTS)
}

/// A file host is matched EXACTLY, never by suffix: a subdomain of an observed file host is a
/// different host that nobody observed.
pub fn is_download_host(url: &Url) -> bool {
    url.scheme() == "https"
        && url
            .host_str()
            .is_some_and(|h| DOWNLOAD_HOSTS.iter().any(|d| h.eq_ignore_ascii_case(d)))
}

pub fn is_auth_host(url: &Url) -> bool {
    if url.scheme() != "https" {
        return false;
    }
    let Some(h) = url.host_str() else { return false };
    AUTH_RULES.iter().any(|r| host_matches(h, r.host) && (r.path_ok)(url.path()))
}

/// Navigation the model browser itself may perform. `about:blank` is the initial
/// document; everything else must be https and on one of the three lists.
pub fn navigation_allowed(url: &Url) -> bool {
    url.scheme() == "about" || is_site(url) || is_download_host(url) || is_auth_host(url)
}

/// Hosts a sign-in POPUP may visit. A popup exists only because the site opened one with
/// `window.open` (MakerWorld's Google / Apple / Facebook buttons do). It is https-only, has
/// no Tauri capability and no IPC, shares only the Model Connect browser profile, and may
/// stay on these hosts: the identity providers, and the two sites a sign-in returns to.
/// Observed from the real flow, never guessed; a host not listed here is refused and its
/// hostname alone is recorded in the blocked-hosts log.
pub const POPUP_HOSTS: &[&str] = &[
    "accounts.google.com",
    "appleid.apple.com",
    "idmsa.apple.com",
    "facebook.com",
    "bambulab.com",
    "makerworld.com",
];

/// May a popup open at, or navigate to, this URL? `about:blank` is the window's initial
/// document; everything else must be https on a popup host.
pub fn popup_allowed(url: &Url) -> bool {
    url.as_str() == "about:blank" || (url.scheme() == "https" && matches_any(url, POPUP_HOSTS))
}

/// At most one sign-in popup at a time.
pub struct PopupGate(AtomicBool);

impl PopupGate {
    pub const fn new() -> Self {
        PopupGate(AtomicBool::new(false))
    }
    /// True when the caller now owns the one popup slot.
    pub fn claim(&self) -> bool {
        !self.0.swap(true, Ordering::SeqCst)
    }
    pub fn release(&self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

pub fn popup_gate() -> &'static PopupGate {
    static GATE: PopupGate = PopupGate::new();
    &GATE
}

const RESERVED: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

const MAX_NAME: usize = 120;

/// A filename that is safe to create inside Studio's downloads folder, or None.
/// Takes only the last path component, strips control characters and the characters
/// Windows forbids, removes trailing dots and spaces, refuses reserved device names,
/// and bounds the length while keeping the extension.
pub fn sanitize_filename(raw: &str) -> Option<String> {
    let last = raw.rsplit(['/', '\\']).next().unwrap_or("");
    let cleaned: String = last
        .chars()
        .filter(|c| !c.is_control() && !matches!(c, '<' | '>' | ':' | '"' | '|' | '?' | '*'))
        .collect();
    let cleaned = cleaned.trim().trim_end_matches(['.', ' ']).to_string();
    if cleaned.is_empty() || cleaned == "." || cleaned == ".." || cleaned.starts_with("..") {
        return None;
    }
    let stem = cleaned.split('.').next().unwrap_or("");
    if RESERVED.iter().any(|r| r.eq_ignore_ascii_case(stem)) {
        return None;
    }
    if cleaned.chars().count() <= MAX_NAME {
        return Some(cleaned);
    }
    let ext = Path::new(&cleaned)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| format!(".{e}"))
        .unwrap_or_default();
    let keep = MAX_NAME.saturating_sub(ext.chars().count()).max(1);
    let stem: String = cleaned.chars().take(keep).collect();
    Some(format!("{stem}{ext}"))
}

/// The lower-case extension Studio imports, or None for anything else.
pub fn supported_extension(name: &str) -> Option<&'static str> {
    let ext = Path::new(name).extension()?.to_str()?.to_ascii_lowercase();
    match ext.as_str() {
        "3mf" => Some("3mf"),
        "stl" => Some("stl"),
        _ => None,
    }
}

/// `dir/name`, or `dir/name (1)`, `dir/name (2)` ... so an existing file is never overwritten.
#[cfg(test)]
pub fn unique_path(dir: &Path, name: &str) -> PathBuf {
    pick_path(dir, name, &HashSet::new())
}

fn reserved() -> &'static Mutex<HashSet<PathBuf>> {
    static R: OnceLock<Mutex<HashSet<PathBuf>>> = OnceLock::new();
    R.get_or_init(|| Mutex::new(HashSet::new()))
}

/// Choose a destination AND claim it in one step under one lock, so two downloads with
/// the same file name that start together can never be handed the same path. The claim
/// lasts until `release_path` (the download finished or failed); no placeholder file is
/// created, so nothing empty is left behind.
pub fn reserve_path(dir: &Path, name: &str) -> PathBuf {
    let mut held = reserved().lock().unwrap();
    let chosen = pick_path(dir, name, &held);
    held.insert(chosen.clone());
    chosen
}

/// Give a claimed destination back. True when it was claimed by `reserve_path`.
pub fn release_path(path: &Path) -> bool {
    reserved().lock().unwrap().remove(path)
}

fn pick_path(dir: &Path, name: &str, held: &HashSet<PathBuf>) -> PathBuf {
    let first = dir.join(name);
    if !first.exists() && !held.contains(&first) {
        return first;
    }
    let p = Path::new(name);
    let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("download");
    let ext = p.extension().and_then(|e| e.to_str()).map(|e| format!(".{e}")).unwrap_or_default();
    for n in 1..10_000 {
        let candidate = dir.join(format!("{stem} ({n}){ext}"));
        if !candidate.exists() && !held.contains(&candidate) {
            return candidate;
        }
    }
    dir.join(format!("{stem} (copy){ext}"))
}

/// What the download hook remembers between Requested and Finished.
#[derive(Clone, Debug)]
pub struct Pending {
    pub site: String,
    pub page_url: String,
    pub title: String,
}

fn pending() -> &'static Mutex<Vec<(PathBuf, Pending)>> {
    static P: OnceLock<Mutex<Vec<(PathBuf, Pending)>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(Vec::new()))
}

pub fn remember(dest: PathBuf, p: Pending) {
    let mut v = pending().lock().unwrap();
    if v.len() > 64 {
        v.remove(0);
    }
    v.push((dest, p));
}

pub fn take(dest: &Path) -> Option<Pending> {
    let mut v = pending().lock().unwrap();
    let i = v.iter().position(|(d, _)| d == dest)?;
    Some(v.remove(i).1)
}

fn title_slot() -> &'static Mutex<String> {
    static T: OnceLock<Mutex<String>> = OnceLock::new();
    T.get_or_init(|| Mutex::new(String::new()))
}

/// The page title the browser last reported (shown on the "Added from" card).
pub fn set_title(t: String) {
    *title_slot().lock().unwrap() = t.chars().take(200).collect();
}

pub fn title() -> String {
    title_slot().lock().unwrap().clone()
}

/// A page URL with the query string and fragment removed, https only. Query strings can
/// carry session or signed-download tokens, so they are never stored or sent anywhere.
pub fn strip_url(raw: &str) -> String {
    match Url::parse(raw) {
        Ok(u) if u.scheme() == "https" => {
            let mut u = u;
            let _ = u.set_username("");
            let _ = u.set_password(None);
            u.set_query(None);
            u.set_fragment(None);
            u.to_string()
        }
        _ => String::new(),
    }
}

const BLOCKED_LOG: &str = "model-browser-blocked-hosts.log";
const BLOCKED_LOG_MAX: u64 = 64 * 1024;

/// Record that a navigation was refused: scheme and hostname ONLY (never a path, query,
/// cookie or token), in a small bounded file under Studio's own state folder. It is how a
/// site's real download or sign-in host is discovered without guessing.
pub fn note_blocked(base: &Path, url: &Url) {
    use std::io::Write;
    let host = url.host_str().unwrap_or("?").to_ascii_lowercase();
    let line = format!("{} {}", url.scheme(), host);
    let path = base.join(BLOCKED_LOG);
    if let Ok(meta) = std::fs::metadata(&path) {
        if meta.len() > BLOCKED_LOG_MAX {
            let _ = std::fs::remove_file(&path);
        }
    }
    if let Ok(existing) = std::fs::read_to_string(&path) {
        if existing.lines().any(|l| l == line) {
            return;
        }
    }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(f, "{line}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn sites_are_allowed_over_https_only() {
        assert!(is_site(&u("https://www.printables.com/model/1")));
        assert!(is_site(&u("https://makerworld.com/en/models/1")));
        assert!(!is_site(&u("http://www.printables.com/model/1")));
        assert!(!is_site(&u("https://printables.com.evil.example/")));
        assert!(!is_site(&u("https://notprintables.com/")));
    }

    #[test]
    fn download_and_auth_hosts_are_narrow() {
        assert!(is_download_host(&u("https://files.printables.com/media/x.3mf")));
        assert!(!is_download_host(&u("http://files.printables.com/x")));
        assert!(!is_download_host(&u("https://files.printables.com.evil.example/x")));
        assert!(is_auth_host(&u("https://account.prusa3d.com/login/?next=/o/authorize/")));
        assert!(is_auth_host(&u("https://bambulab.com/en-us/sign-in?ticket=1")));
        assert!(is_auth_host(&u("https://bambulab.com/sign-in")));
        // a login host is not general browsing of that company's site
        assert!(!is_auth_host(&u("https://bambulab.com/en-us/store")));
        assert!(!is_auth_host(&u("https://bambulab.com/en-us/sign-in/extra/deep")));
        assert!(!is_auth_host(&u("https://bambulab.com/sign-in-evil")));
        assert!(!is_auth_host(&u("http://bambulab.com/en-us/sign-in")));
        assert!(!is_auth_host(&u("https://evilbambulab.com/en-us/sign-in")));
    }

    #[test]
    fn navigation_off_every_list_is_blocked() {
        assert!(navigation_allowed(&u("about:blank")));
        assert!(!navigation_allowed(&u("https://example.com/")));
        assert!(!navigation_allowed(&u("file:///C:/Windows/win.ini")));
        assert!(!navigation_allowed(&u("javascript:alert(1)")));
    }

    #[test]
    fn traversal_filenames_are_reduced_or_refused() {
        assert_eq!(sanitize_filename("..\\..\\Windows\\evil.3mf").as_deref(), Some("evil.3mf"));
        assert_eq!(sanitize_filename("../../etc/passwd.stl").as_deref(), Some("passwd.stl"));
        assert_eq!(sanitize_filename("..").as_deref(), None);
        assert_eq!(sanitize_filename("...").as_deref(), None);
        assert_eq!(sanitize_filename("").as_deref(), None);
        assert_eq!(sanitize_filename("dir/").as_deref(), None);
    }

    #[test]
    fn reserved_windows_names_are_refused() {
        for n in ["CON.3mf", "con.stl", "NUL", "aux.3mf", "COM1.stl", "LPT9.3mf", "Prn.3mf"] {
            assert_eq!(sanitize_filename(n), None, "{n}");
        }
        assert_eq!(sanitize_filename("CONSOLE.3mf").as_deref(), Some("CONSOLE.3mf"));
    }

    #[test]
    fn forbidden_characters_and_trailing_dots_are_removed() {
        assert_eq!(sanitize_filename("a<b>c:d\"e|f?g*h.3mf").as_deref(), Some("abcdefgh.3mf"));
        assert_eq!(sanitize_filename("model.3mf. . ").as_deref(), Some("model.3mf"));
        assert_eq!(sanitize_filename("tab\tname\n.stl").as_deref(), Some("tabname.stl"));
    }

    #[test]
    fn long_names_keep_their_extension() {
        let long = format!("{}.3mf", "x".repeat(400));
        let got = sanitize_filename(&long).unwrap();
        assert!(got.chars().count() <= MAX_NAME);
        assert!(got.ends_with(".3mf"));
    }

    #[test]
    fn only_3mf_and_stl_are_supported() {
        assert_eq!(supported_extension("a.3MF"), Some("3mf"));
        assert_eq!(supported_extension("a.Stl"), Some("stl"));
        for n in ["a.zip", "a.gcode", "a.exe", "a.3mf.exe", "a", "a.obj", ".3mf"] {
            assert_eq!(supported_extension(n), None, "{n}");
        }
    }

    // --- security: what a remote model-site page can and cannot reach --------------------

    #[test]
    fn only_the_main_window_has_a_capability() {
        let caps = include_str!("../capabilities/default.json");
        let v: serde_json::Value = serde_json::from_str(caps).unwrap();
        assert_eq!(v["windows"], serde_json::json!(["main"]), "no other window may gain IPC");
        assert!(v.get("remote").is_none(), "no remote-URL capability");
        assert!(!caps.contains("model-browser"));
        let dir = std::fs::read_dir(concat!(env!("CARGO_MANIFEST_DIR"), "/capabilities")).unwrap();
        let files: Vec<_> = dir.filter_map(|e| e.ok()).map(|e| e.file_name()).collect();
        assert_eq!(files.len(), 1, "a new capability file needs a security review: {files:?}");
    }

    #[test]
    fn no_global_tauri_or_remote_ipc_in_the_app_config() {
        let conf = include_str!("../tauri.conf.json");
        for banned in ["withGlobalTauri", "dangerousRemoteDomainIpcAccess", "\"remote\""] {
            assert!(!conf.contains(banned), "{banned} must not appear in tauri.conf.json");
        }
    }

    #[test]
    fn studio_code_never_reads_cookies() {
        // Built with concat! so this test does not contain the strings it forbids.
        let banned = [concat!(".cook", "ies("), concat!("cook", "ies_for_url"), concat!("Cook", "ie::")];
        for (name, src) in [
            ("main.rs", include_str!("main.rs")),
            ("model_browser.rs", include_str!("model_browser.rs")),
            ("sidecar.rs", include_str!("sidecar.rs")),
        ] {
            // the test module itself is excluded from the scan
            let code = src.split("#[cfg(test)]").next().unwrap();
            for b in banned {
                assert!(!code.contains(b), "{name} must not use {b}: Studio never reads site cookies");
            }
        }
    }

    #[test]
    fn popups_are_denied_except_the_one_sign_in_popup() {
        let main = include_str!("main.rs").replace("\r\n", "\n");
        let code = main.split("#[cfg(test)]").next().unwrap();
        assert!(code.contains("NewWindowResponse::Deny"));
        // The default "open it however the page asked" response is never used.
        assert!(!code.contains("NewWindowResponse::Allow"));
        // A popup is created in exactly one place, the sign-in popup function ...
        assert_eq!(code.matches("NewWindowResponse::Create").count(), 1);
        let start = code.find("fn auth_popup").expect("auth_popup exists");
        let end = code[start..].find("\n}\n").map(|i| start + i).unwrap();
        assert!(code[start..end].contains("NewWindowResponse::Create"));
        // ... and the Model Browser routes every popup request through it.
        assert!(code.contains("auth_popup(&app_for_popup"));
    }

    #[test]
    fn downloads_are_only_ever_taken_from_the_browser_not_fetched_by_studio() {
        let mb = include_str!("model_browser.rs").split("#[cfg(test)]").next().unwrap();
        assert!(!mb.contains("ureq") && !mb.contains("reqwest"), "no independent HTTP fetch");
    }

    #[test]
    fn page_urls_lose_their_query_and_fragment() {
        assert_eq!(strip_url("https://www.printables.com/model/1-x/files?token=abc#frag"),
                   "https://www.printables.com/model/1-x/files");
        assert_eq!(strip_url("http://www.printables.com/model/1"), "");
        assert_eq!(strip_url("not a url"), "");
        assert_eq!(strip_url("javascript:alert(1)"), "");
    }

    #[test]
    fn blocked_hosts_are_logged_without_paths_or_queries() {
        let dir = std::env::temp_dir().join(format!("mb-blocked-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let url = Url::parse("https://cdn.example.test/secret/path?token=SECRET#f").unwrap();
        note_blocked(&dir, &url);
        note_blocked(&dir, &url); // de-duplicated
        let text = std::fs::read_to_string(dir.join(BLOCKED_LOG)).unwrap();
        assert_eq!(text, "https cdn.example.test\n");
        assert!(!text.contains("SECRET") && !text.contains("secret"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn existing_files_are_never_overwritten() {
        let dir = std::env::temp_dir().join(format!("mb-unique-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("a.3mf"), b"x").unwrap();
        std::fs::write(dir.join("a (1).3mf"), b"x").unwrap();
        assert_eq!(unique_path(&dir, "a.3mf"), dir.join("a (2).3mf"));
        assert_eq!(unique_path(&dir, "fresh.3mf"), dir.join("fresh.3mf"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}

#[cfg(test)]
mod repair_tests {
    use super::*;

    #[test]
    fn strip_url_drops_credentials_query_and_fragment() {
        let s = strip_url("https://user:pw@printables.com/model/1?token=abc#x");
        assert_eq!(s, "https://printables.com/model/1");
    }

    #[test]
    fn download_host_is_checked_on_the_real_url() {
        assert!(is_download_host(&Url::parse("https://files.printables.com/m/a.stl").unwrap()));
        assert!(!is_download_host(&Url::parse("https://evil.example/a.stl").unwrap()));
        assert!(!is_download_host(&Url::parse("https://printables.com/a.stl").unwrap()));
    }
}

#[cfg(test)]
mod reservation_tests {
    use super::*;

    #[test]
    fn simultaneous_downloads_with_one_name_get_distinct_paths() {
        let dir = std::env::temp_dir().join(format!("mb-reserve-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let handles: Vec<_> = (0..32)
            .map(|_| {
                let d = dir.clone();
                std::thread::spawn(move || reserve_path(&d, "same.3mf"))
            })
            .collect();
        let got: Vec<PathBuf> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        let unique: HashSet<_> = got.iter().cloned().collect();
        assert_eq!(unique.len(), 32, "every download needs its own path");
        assert!(got.contains(&dir.join("same.3mf")));
        assert!(got.contains(&dir.join("same (1).3mf")));
        for p in &got {
            assert!(release_path(p));
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_released_name_is_reusable_and_release_is_exact() {
        let dir = std::env::temp_dir().join(format!("mb-release-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let a = reserve_path(&dir, "x.stl");
        assert_eq!(a, dir.join("x.stl"));
        assert_eq!(reserve_path(&dir, "x.stl"), dir.join("x (1).stl"));
        assert!(release_path(&a));
        assert!(!release_path(&a), "already released");
        assert_eq!(reserve_path(&dir, "x.stl"), dir.join("x.stl"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}

#[cfg(test)]
mod popup_tests {
    use super::*;

    fn u(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn a_popup_is_https_only() {
        assert!(popup_allowed(&u("https://accounts.google.com/o/oauth2/auth")));
        assert!(!popup_allowed(&u("http://accounts.google.com/o/oauth2/auth")));
        assert!(!popup_allowed(&u("file:///C:/Windows/win.ini")));
        assert!(!popup_allowed(&u("javascript:alert(1)")));
        assert!(!popup_allowed(&u("data:text/html,hi")));
    }

    #[test]
    fn about_blank_is_the_only_non_https_popup_url() {
        assert!(popup_allowed(&u("about:blank")));
        assert!(!popup_allowed(&u("about:srcdoc")));
    }

    #[test]
    fn an_unapproved_popup_host_is_refused() {
        for bad in [
            "https://evil.example/login",
            "https://accounts.google.com.evil.example/",
            "https://notfacebook.com/",
            "https://printables.com/",
            "https://example.com/",
        ] {
            assert!(!popup_allowed(&u(bad)), "{bad}");
        }
    }

    #[test]
    fn the_identity_providers_and_return_sites_are_allowed() {
        for ok in [
            "https://accounts.google.com/signin",
            "https://appleid.apple.com/auth/authorize",
            "https://www.facebook.com/login.php",
            "https://m.facebook.com/dialog/oauth",
            "https://bambulab.com/en-us/sign-in",
            "https://makerworld.com/en/",
        ] {
            assert!(popup_allowed(&u(ok)), "{ok}");
        }
    }

    #[test]
    fn a_second_simultaneous_popup_is_refused_until_the_first_closes() {
        let gate = PopupGate::new();
        assert!(gate.claim(), "first popup gets the slot");
        assert!(!gate.claim(), "second popup is refused");
        assert!(!gate.claim());
        gate.release();
        assert!(gate.claim(), "a closed popup frees the slot");
    }

    #[test]
    fn popup_hosts_do_not_widen_the_main_browsers_navigation() {
        // Facebook, Apple and the wider bambulab.com site are popup-only: the main model
        // browser still refuses them, and still refuses anything off its three lists.
        assert!(!navigation_allowed(&u("https://www.facebook.com/login.php")));
        assert!(!navigation_allowed(&u("https://appleid.apple.com/auth/authorize")));
        assert!(!navigation_allowed(&u("https://bambulab.com/en-us/account")));
        assert!(!navigation_allowed(&u("https://evil.example/")));
        assert!(!navigation_allowed(&u("http://makerworld.com/")));
        assert!(navigation_allowed(&u("https://makerworld.com/en/")));
    }

    #[test]
    fn the_popup_is_built_without_a_profile_of_its_own_and_without_privileges() {
        let main_rs = include_str!("main.rs").replace("
", "
");
        let start = main_rs.find("fn auth_popup").expect("auth_popup exists");
        let body = &main_rs[start..];
        let end = body.find("
}
").map(|i| i + 3).unwrap_or(body.len());
        let body = &body[..end];
        // Shares the opener's environment (and so only the Model Connect profile) ...
        assert!(body.contains(".window_features("), "popup must inherit the opener's environment");
        // ... and never names a data directory, an invoke handler, a script, or a capability.
        for forbidden in [".data_directory(", "initialization_script", "invoke_handler", "with_global_tauri", "add_capability", "capabilit"] {
            assert!(!body.contains(forbidden), "popup must not use {forbidden}");
        }
        // Its own popups, downloads and navigation are locked down.
        assert!(body.contains("NewWindowResponse::Deny"));
        assert!(body.contains("popup_allowed"));
        assert!(body.contains("release()"), "closing the popup frees the single slot");
    }

    #[test]
    fn only_the_main_window_label_has_a_capability_so_the_popup_has_none() {
        let caps = include_str!("../capabilities/default.json");
        let v: serde_json::Value = serde_json::from_str(caps).unwrap();
        let windows = v["windows"].as_array().unwrap();
        assert_eq!(windows.len(), 1);
        assert_eq!(windows[0], "main");
        assert!(!caps.contains("model-auth") && !caps.contains('*'));
    }

    #[test]
    fn clear_site_data_targets_the_model_browser_profile_and_nothing_of_studio() {
        let main_rs = include_str!("main.rs").replace("
", "
");
        let start = main_rs.find("fn clear_model_browser_data").unwrap();
        let body = &main_rs[start..start + 700.min(main_rs.len() - start)];
        assert!(body.contains("MODEL_BROWSER_LABEL"));
        assert!(body.contains("clear_all_browsing_data"));
        assert!(!body.contains("\"main\""), "must never clear the main Studio webview");
    }
}

#[cfg(test)]
mod makerworld_host_tests {
    use super::*;

    #[test]
    fn the_observed_makerworld_file_host_is_a_download_host_and_nothing_wider() {
        let u = |s: &str| Url::parse(s).unwrap();
        assert!(is_download_host(&u("https://makerworld.bblmw.com/makerworld/model/x.3mf")));
        assert!(!is_download_host(&u("http://makerworld.bblmw.com/x.3mf")));
        assert!(!is_download_host(&u("https://bblmw.com/x.3mf")));
        assert!(!is_download_host(&u("https://evil.makerworld.bblmw.com/x.3mf")));
        assert!(!is_download_host(&u("https://a.files.printables.com/x.stl")));
        assert!(is_download_host(&u("https://MakerWorld.BBLMW.com/x.3mf")));
        assert!(is_download_host(&u("https://files.printables.com/x.stl")));
        assert!(!is_download_host(&u("https://evilmakerworld.bblmw.com.example/x.3mf")));
        // A file host is not a place to browse to or sign in at.
        assert!(navigation_allowed(&u("https://makerworld.bblmw.com/a")));
        assert!(!popup_allowed(&u("https://makerworld.bblmw.com/a")));
    }
}
