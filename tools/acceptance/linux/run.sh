#!/usr/bin/env bash
# Linux installed-build acceptance harness — same ROLE as tools/acceptance/run.ps1
# (Windows), not the same implementation: isolated state, the real installed
# binary, bounded checks, owned-process-only cleanup, a machine-readable
# report. Unlike linux-ci.yml's inline steps (package layout, metadata,
# install/upgrade/purge, headless launch, process-lifecycle-under-signals),
# this harness drives the installed app through an actual GUI workflow —
# launch with a file, see it render, act on it, close it for real — the
# thing none of those steps exercise. Run this AFTER a .deb is already
# proven to install/package correctly; this harness assumes that.
#
# Usage: run.sh <path-to-.deb>
# Needs root (apt-get, useradd) — run inside the CI container or any root
# shell. Requires: xvfb, openbox, wmctrl, xdotool, imagemagick, sqlite3,
# dbus-x11, jq, curl (same packages linux-ci.yml already installs, plus
# openbox/wmctrl/xdotool/imagemagick/sqlite3/jq/curl for this harness
# specifically). Deliberately NOT Python or Node — this harness itself must
# run on the same genuinely clean images (no dev tools) it's proving the
# shipped app runs on (L8).
#
# Output: $ACCEPT_WORKDIR/evidence/acceptance.json (schema_version
# "acceptance/1", same shape as the Windows harness's report — see
# tools/acceptance/run.ps1), screenshots, and app/sidecar logs, all under
# $ACCEPT_WORKDIR/evidence/. Anonymized: no real IP/hostname/username in
# the JSON (the synthetic user this script creates is not a real identity).
#
# Designed to be safe to run on a shared/real machine, not just an ephemeral
# CI container (L8/L10 may run it that way): the test account is unique per
# invocation, and this run refuses to proceed rather than touch one it
# didn't create; the package is only purged at the end if THIS run is what
# installed it — a pre-existing real install is NOT purged, but IS replaced
# on disk by the test .deb for the duration of the run and never restored,
# so this is not yet safe to run against a machine whose pre-existing
# install must survive intact (tracked as L8/L10 follow-up debt); every
# process this harness ever discovers/waits-for is tracked by real PID,
# verified by the exact uid of the test account THIS run just created plus
# an exact byte-for-byte argv[0] match (from /proc/<pid>/cmdline) — never by
# process name or cmdline substring, which could otherwise match an
# unrelated concurrent run's processes or something on the machine that
# merely happens to share a name. Final cleanup's uid-wide safety-net kill
# (see that comment for the full reasoning) is additionally scoped to only
# processes that started after this run began (real /proc start-time
# comparison), so a pre-existing process holding a recycled uid is left
# alone rather than killed. All cleanup lives in one EXIT trap, so every
# exit path — including an early failure — runs it, not just the happy
# path at the bottom of the script.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "This harness needs root (apt-get, useradd). Run it inside the CI container or as root." >&2
  exit 2
fi
if [ $# -ne 1 ]; then
  echo "usage: run.sh <path-to-.deb>" >&2
  exit 2
fi
deb_path="$1"
if [ ! -f "$deb_path" ]; then
  echo "No such file: $deb_path" >&2
  exit 1
fi

# Captured before this run creates any account or process, so cleanup can
# tell "a process this run started" from "a process that predates this run
# and merely inherited a uid this run's new account happened to be assigned"
# — see the uid-scoped-kill note in cleanup() below. /proc/<pid>/stat field
# 22 (starttime, in clock ticks since boot) is monotonic and comm-safe to
# parse this way (strip everything through the last ")" first, since comm
# itself can contain spaces/parens).
harness_start_ticks="$(awk '{ n=split($0,a,")"); split(a[n],f," "); print f[20] }' /proc/self/stat)"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
workdir="${SNAPSTUDIO_ACCEPT_WORKDIR:-$(mktemp -d)}"
mkdir -p "$workdir/evidence"
evidence_dir="$workdir/evidence"

checks_json="$evidence_dir/acceptance.json"
checks_names=()
checks_ok=()
checks_detail=()

add_check() {
  local name="$1" ok="$2" detail="${3:-}"
  checks_names+=("$name")
  checks_ok+=("$ok")
  checks_detail+=("$detail")
  if [ "$ok" = "true" ]; then
    echo "PASS  $name${detail:+  — $detail}"
  else
    echo "FAIL  $name${detail:+  — $detail}" >&2
  fi
}

write_report() {
  # jq, not python3.13 — this harness now runs on genuinely clean images
  # (L8) that have no Python at all. jq is installed as test tooling
  # alongside Xvfb/openbox/etc., never assumed part of the runtime.
  {
    echo "{"
    echo "  \"schema_version\": \"acceptance/1\","
    echo "  \"platform\": \"linux\","
    echo "  \"deb\": \"$(basename "$deb_path")\","
    echo "  \"checks\": ["
    local n=${#checks_names[@]}
    for i in "${!checks_names[@]}"; do
      local comma=","
      [ "$i" -eq $((n - 1)) ] && comma=""
      printf '    {"name": %s, "ok": %s, "detail": %s}%s\n' \
        "$(jq -Rn --arg v "${checks_names[$i]}" '$v')" \
        "${checks_ok[$i]}" \
        "$(jq -Rn --arg v "${checks_detail[$i]}" '$v')" \
        "$comma"
    done
    echo "  ]"
    echo "}"
  } > "$checks_json"
  echo "--- Report written to $checks_json ---"
  cat "$checks_json"
}

any_failed() {
  for ok in "${checks_ok[@]}"; do
    [ "$ok" = "false" ] && return 0
  done
  return 1
}

# Find a process owned by real uid $1 whose argv[0] (from /proc/<pid>/
# cmdline, NUL-separated — the exact first token, never a substring) is
# EXACTLY $2 (an absolute path). Two earlier approaches both failed for
# real, diagnosed with actual data from a failing CI run (36104236871),
# not guessed: a process-tree walk from the launcher PID (runuser's PAM
# session handling produces a tree shape that doesn't reliably traverse),
# then uid+/proc/<pid>/exe matching (readlink -f "/proc/<pid>/exe" itself
# fails — permission denied — across a UID boundary in this container,
# even for root: every uid=1000 process in that run's diagnostic dump
# showed "exe=?", including ones root definitely has ptrace-equivalent
# rights over in a normal environment — evidence of a restricted
# CAP_SYS_PTRACE in this specific container runtime). The SAME diagnostic
# dump proved /proc/<pid>/status (for uid) and /proc/<pid>/cmdline both
# stayed readable across that same boundary, which is what this uses
# instead. Exact argv[0] equality is not a "process name" or substring
# match in the sense Sol's review warned about (a `pgrep -f` regex against
# a joined command-line string) — it's the literal, exact, NUL-delimited
# first argument this script itself chose when it invoked the process,
# compared for byte-for-byte equality, combined with the exact owning uid.
find_process_by_uid_and_argv0() {
  local want_uid="$1" want_argv0="$2"
  local pid_dir pid argv0 uid
  for pid_dir in /proc/[0-9]*; do
    pid="${pid_dir#/proc/}"
    # Grouped so a failed input redirect (pid exited between the glob and
    # this read — routine under heavy launch/kill cycling) is caught by
    # THIS 2>/dev/null too. An un-grouped `cmd < file 2>/dev/null` does NOT
    # suppress a failed `< file` redirect's own error message — bash reports
    # that straight to the real stderr before the command's own redirection
    # is even reached, which is noise, not a bug, but noise this harness
    # doesn't need.
    argv0="$({ tr '\0' '\n' < "$pid_dir/cmdline"; } 2>/dev/null | head -n1 || true)"
    [ -n "$argv0" ] && [ "$argv0" = "$want_argv0" ] || continue
    uid="$(awk '/^Uid:/{print $2; exit}' "$pid_dir/status" 2>/dev/null || true)"
    [ "$uid" = "$want_uid" ] || continue
    echo "$pid"
    return 0
  done
  return 1
}

wait_for_process_by_uid_and_argv0() {
  local want_uid="$1" want_argv0="$2" tries="${3:-40}"
  local found=""
  for _ in $(seq 1 "$tries"); do
    found="$(find_process_by_uid_and_argv0 "$want_uid" "$want_argv0" || true)"
    [ -n "$found" ] && { echo "$found"; return 0; }
    sleep 0.5
  done
  return 1
}

# --- state used by cleanup, declared before anything that could fail ------
declare -a owned_pids=()
test_user=""
test_uid=""
user_created="false"
pkg_name=""
pkg_preinstalled="false"

cleanup() {
  for pid in "${owned_pids[@]:-}"; do
    # kill -0 first so a PID that already exited (most of these are killed
    # again here defensively, having already been killed earlier in the
    # happy path) is never re-signalled — narrows, though does not fully
    # close, the window where a reaped PID could be reused by an unrelated
    # process before this cleanup runs.
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  done
  if [ -n "$pkg_name" ] && [ "$pkg_preinstalled" = "false" ]; then
    apt-get purge -y "$pkg_name" >/dev/null 2>&1 || true
  fi
  if [ -n "$test_user" ] && [ "$user_created" = "true" ]; then
    # If an earlier check bailed out before finding/tracking every process
    # this run launched under $test_uid (e.g. app-detection timed out but
    # the app was actually running), a bare userdel -r would fail — it
    # refuses to remove an account with live processes — and that failure
    # was silently swallowed, leaking the account and its processes. Kill
    # everything under this uid first so userdel always has a clean account
    # to remove, regardless of what owned_pids did or didn't track.
    #
    # SCOPED to processes that started AFTER this harness run began
    # (compared against $harness_start_ticks, captured before this run did
    # anything). This closes a real gap: useradd allocates a uid from
    # account records, not from /proc, so a uid this run's new account gets
    # assigned could already be held by an orphaned process from an
    # earlier, unrelated account — verified reproducible via
    # `userdel -f <name>` with the account's process still alive (exactly
    # what desktop tools call: accountsservice's "Remove User" always runs
    # `userdel -f`, GNOME Settings included). A process that predates this
    # run can never be one this run is responsible for, so it's excluded
    # rather than killed, and userdel's own refusal (it won't remove an
    # account with live processes) is left to fire and be reported below —
    # not silently swallowed.
    if [ -n "$test_uid" ]; then
      for pid in $(pgrep -u "$test_uid" 2>/dev/null || true); do
        pid_ticks="$(awk '{ n=split($0,a,")"); split(a[n],f," "); print f[20] }' "/proc/$pid/stat" 2>/dev/null || true)"
        if [ -n "$pid_ticks" ] && [ "$pid_ticks" -ge "$harness_start_ticks" ] 2>/dev/null; then
          kill -9 "$pid" 2>/dev/null || true
        else
          echo "NOTE: pid $pid under recycled uid $test_uid predates this run (started before it) — left alone, not killed." >&2
        fi
      done
    fi
    userdel -r "$test_user" 2>/dev/null || echo "NOTE: userdel $test_user failed (rc=$?) — a pre-existing process on this recycled uid may still be alive; see NOTE lines above." >&2
  fi
}
trap cleanup EXIT

echo "=== Installing the .deb ==="
apt-get update -qq
apt-get install -y --no-install-recommends xvfb openbox wmctrl xdotool imagemagick sqlite3 dbus-x11 jq curl >/dev/null
# pkg_name stays empty (cleanup's guard) until pkg_preinstalled is fully
# determined, so an interrupt between the Package query and the preinstalled
# check can never leave cleanup thinking THIS run owns a package it doesn't.
pkg_name_candidate="$(dpkg-deb -f "$deb_path" Package)"
# dpkg's Status-Abbrev is (desired-action)(current-status)(error-flag), e.g.
# "ii" (installed), "hi" (held), "ri"/"pi" (remove/purge-requested but still
# installed), "iHR" (half-installed, reinstall-required). Match any status
# whose SECOND character is neither "n" (not-installed) nor "c"
# (config-files-only, no payload on disk) — this covers every state that
# still has package payload on disk (i, H, U, F, W, t), not just the exact
# second-character "i" this used to require, which missed half-installed/
# unpacked/half-configured/triggers states and would have let cleanup purge
# a genuinely pre-existing (if partially broken) install.
if dpkg-query -W -f='${db:Status-Abbrev}' "$pkg_name_candidate" 2>/dev/null | grep -q '^.[^nc]'; then
  pkg_preinstalled="true"
  echo "NOTE: $pkg_name_candidate was already installed before this run — this replaces its files with the test .deb (not left alone) but will NOT purge it at the end (that would remove a real pre-existing install, not something this run created)." >&2
fi
pkg_name="$pkg_name_candidate"
# --reinstall when a same-version package is already present: plain
# `apt-get install` treats a matching version as already current and skips
# it, which would leave the OLD files in place and let the harness pass
# against a pre-existing install instead of the .deb it was given to test.
if [ "$pkg_preinstalled" = "true" ]; then
  apt-get install -y --reinstall "$deb_path"
else
  apt-get install -y "$deb_path"
fi

installed_files="$(dpkg -L "$pkg_name")"
bin_path=""
sidecar_exe=""
while IFS= read -r f; do
  if [ -z "$bin_path" ] && [[ "$f" =~ ^/usr/bin/[^/]+$ ]]; then
    bin_path="$f"
  fi
  if [ -z "$sidecar_exe" ] && [[ "$f" == *"/snapstudio-api-x86_64-unknown-linux-gnu" ]]; then
    sidecar_exe="$f"
  fi
done <<< "$installed_files"
if [ -z "$bin_path" ]; then
  add_check "Installed app entry point found" "false" "no /usr/bin/* entry"
  write_report
  exit 1
fi
add_check "Installed app entry point found" "true" "$bin_path"
if [ -z "$sidecar_exe" ]; then
  add_check "Installed sidecar binary found" "false" "no *snapstudio-api-x86_64-unknown-linux-gnu entry"
  write_report
  exit 1
fi

echo "=== Creating an unprivileged test user (real installs never run as root) ==="
# PID-suffixed so this is a fresh, never-before-seen account name on every
# invocation — a genuinely pre-existing/shared/concurrent-run collision on
# this exact name is not realistically possible. Refuse to run rather than
# reuse it: reusing would mean cp/chown-ing the fixture into a home
# directory this run didn't create, which could be a real account's data
# on a shared machine (L8/L10) — the exact thing "never touch an account
# this run didn't create" promises not to do.
test_user="snapstudio-acceptance-$$"
if id "$test_user" >/dev/null 2>&1; then
  echo "FATAL: $test_user already exists. This name includes this run's own PID, so a collision should not happen — refusing to reuse or modify an account this run didn't create." >&2
  exit 1
fi
useradd -m -s /bin/bash "$test_user"
user_created="true"
user_home="$(eval echo "~$test_user")"
xdg_data_home="$user_home/.local/share"
test_uid="$(id -u "$test_user")"

echo "=== Starting Xvfb + a real window manager ==="
# Earlier steps in this same CI job use xvfb-run, whose --auto-servernum
# default starts searching FROM :99 — one of those earlier steps can still
# genuinely be holding it at this point (a `kill -9` in an earlier step not
# fully reaping its process doesn't mean the process is actually gone yet).
# Use a distinct range (150+) nothing else in this job goes near. For each
# candidate: only remove a lock file if the PID it names is verifiably NOT
# running (never touch a lock a live process might still legitimately
# hold), then actually try starting Xvfb and confirm it's still alive a
# moment later rather than trusting the lock file either way. Register
# each attempt's PID in owned_pids BEFORE the survival check, so an
# interruption during that brief window still gets cleaned up by the trap.
x_display=""
for candidate in 150 151 152 153 154 155; do
  lock_file="/tmp/.X${candidate}-lock"
  if [ -f "$lock_file" ]; then
    lock_pid="$(tr -d ' \t' < "$lock_file" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
      echo "Display :$candidate genuinely still in use (PID $lock_pid) — trying the next candidate." >&2
      continue
    fi
    rm -f "$lock_file"
  fi
  Xvfb ":$candidate" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
  candidate_pid=$!
  owned_pids+=("$candidate_pid")
  sleep 0.5
  if kill -0 "$candidate_pid" 2>/dev/null; then
    x_display="$candidate"
    xvfb_pid="$candidate_pid"
    break
  fi
  wait "$candidate_pid" 2>/dev/null || true
done
if [ -z "$x_display" ]; then
  echo "Could not start Xvfb on any candidate display (150-155)." >&2
  exit 1
fi
echo "Xvfb started on display :$x_display (PID $xvfb_pid)"
export DISPLAY=":$x_display"
for _ in $(seq 1 20); do
  xdpyinfo >/dev/null 2>&1 && break
  sleep 0.25
done
openbox --sm-disable &
wm_pid=$!
owned_pids+=("$wm_pid")
sleep 1

fixture_src="$repo_root/examples/demo_u1_showcase.3mf"
if [ ! -f "$fixture_src" ]; then
  add_check "Fixture file exists" "false" "$fixture_src not found"
  write_report
  exit 1
fi
fixture_copy="$user_home/demo_u1_showcase.3mf"
cp "$fixture_src" "$fixture_copy"
chown "$test_user:$test_user" "$fixture_copy"
fixture_sha_before="$(runuser -u "$test_user" -- sha256sum "$fixture_copy" | cut -d' ' -f1)"

echo "=== Launching the installed app as $test_user, with the fixture ==="
app_log="$evidence_dir/app.log"
runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
  "$bin_path" "$fixture_copy" > "$app_log" 2>&1 &
app_launcher_pid=$!
owned_pids+=("$app_launcher_pid")

app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 40 || true)"
if [ -z "$app_pid" ]; then
  add_check "App process started" "false" "never appeared within 20s"
  cat "$app_log" >&2 || true
  # Diagnostic dump: this has failed to find a process we have direct
  # other evidence (the app's own stderr) is actually running — dump
  # exactly what's really out there and why the match criterion (uid
  # $test_uid, argv[0] == $bin_path) isn't hitting it, instead of guessing
  # again blind. Restricted to processes owned by the test uid (and root,
  # which launched them) rather than every process on the machine, so this
  # never prints another user's cmdline on a shared/real host (L8/L10).
  {
    echo "--- DIAGNOSTIC: expected uid=$test_uid argv0='$bin_path' ---"
    echo "--- id $test_user: $(id "$test_user" 2>&1) ---"
    echo "--- processes owned by uid=$test_uid or uid=0, pid/uid/exe/cmd ---"
    for p in /proc/[0-9]*; do
      pn="${p#/proc/}"
      pu="$(awk '/^Uid:/{print $2; exit}' "$p/status" 2>/dev/null || echo '?')"
      [ "$pu" = "$test_uid" ] || [ "$pu" = "0" ] || continue
      pe="$(readlink -f "$p/exe" 2>/dev/null || echo '?')"
      pc="$({ tr '\0' ' ' < "$p/cmdline"; } 2>/dev/null || echo '?')"
      echo "pid=$pn uid=$pu exe=$pe cmd=$pc"
    done
  } >&2
  write_report
  exit 1
fi
add_check "App process started" "true" "PID $app_pid"
owned_pids+=("$app_pid")

sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 40 || true)"
if [ -z "$sidecar_pid" ]; then
  add_check "Sidecar spawned from the installed app" "false" "never appeared within 20s"
  write_report
  exit 1
fi
add_check "Sidecar spawned from the installed app" "true" "PID $sidecar_pid"
owned_pids+=("$sidecar_pid")

echo "=== Verifying an app window appears ==="
window_id=""
for _ in $(seq 1 40); do
  window_id="$(xdotool search --name '^Snapmaker Studio$' 2>/dev/null | head -n1 || true)"
  [ -n "$window_id" ] && break
  sleep 0.5
done
add_check "App window appears" "$([ -n "$window_id" ] && echo true || echo false)" "window id: ${window_id:-none}"

if [ -n "$window_id" ]; then
  echo "=== Screenshotting (proves it renders something, not a blank white window) ==="
  sleep 2  # let the React app finish its initial paint
  import_err="$evidence_dir/import.err"
  import -display ":$x_display" -window root "$evidence_dir/01-dashboard.png" 2>"$import_err" || true
  if [ -f "$evidence_dir/01-dashboard.png" ]; then
    unique_colors="$(convert "$evidence_dir/01-dashboard.png" -format %k info: 2>/dev/null || echo 0)"
    add_check "App renders (screenshot is not a uniform blank window)" "$([ "${unique_colors:-0}" -gt 5 ] && echo true || echo false)" "$unique_colors unique colors"
  else
    add_check "App renders (screenshot is not a uniform blank window)" "false" "screenshot capture failed: $(tr '\n' ' ' < "$import_err" 2>/dev/null || echo unknown)"
  fi
fi

echo "=== Verifying the launch-file path reached the engine (library.db row) ==="
db_path="$xdg_data_home/SnapmakerStudio/library.db"
db_found="false"
for _ in $(seq 1 20); do
  if [ -f "$db_path" ]; then
    row="$(sqlite3 "$db_path" "SELECT source_path FROM projects WHERE source_path LIKE '%demo_u1_showcase.3mf';" 2>/dev/null || true)"
    if [ -n "$row" ]; then
      db_found="true"
      break
    fi
  fi
  sleep 0.5
done
add_check "Launch-file path recorded a library.db row" "$db_found" "$db_path"

echo "=== Verifying the original fixture file was never modified ==="
fixture_sha_after="$(runuser -u "$test_user" -- sha256sum "$fixture_copy" | cut -d' ' -f1)"
add_check "Original file untouched (hash unchanged)" "$([ "$fixture_sha_before" = "$fixture_sha_after" ] && echo true || echo false)" "before=$fixture_sha_before after=$fixture_sha_after"

echo "=== Verifying XDG data dir permissions ==="
data_dir="$xdg_data_home/SnapmakerStudio"
if [ -d "$data_dir" ]; then
  mode="$(stat -c %a "$data_dir")"
  add_check "Data dir mode is 0700" "$([ "$mode" = "700" ] && echo true || echo false)" "mode=$mode"
else
  add_check "Data dir mode is 0700" "false" "$data_dir does not exist"
fi

echo "=== Closing the app the way a user does (real window manager close, not a kill) ==="
# EWMH _NET_CLOSE_WINDOW via wmctrl -> openbox turns it into ICCCM
# WM_DELETE_WINDOW -> GTK -> tao CloseRequested -> the exact same path a
# user clicking the X button takes. Deliberately NOT a signal (that would
# test the PDEATHSIG/lifeline layers again, already proven elsewhere) and
# NOT a debug/test-only IPC shortcut (that would test code that doesn't
# exist in the real release artifact).
graceful_close_ok="false"
if [ -n "$window_id" ]; then
  wmctrl -ic "$window_id"
  close_deadline=$(($(date +%s) + 15))
  while [ "$(date +%s)" -lt "$close_deadline" ]; do
    kill -0 "$app_pid" 2>/dev/null || break
    sleep 0.25
  done
  app_gone=1
  kill -0 "$app_pid" 2>/dev/null || app_gone=0
  sidecar_gone=1
  sidecar_deadline=$(($(date +%s) + 10))
  while [ "$(date +%s)" -lt "$sidecar_deadline" ]; do
    kill -0 "$sidecar_pid" 2>/dev/null || { sidecar_gone=0; break; }
    sleep 0.25
  done
  if [ "$app_gone" -eq 0 ] && [ "$sidecar_gone" -eq 0 ]; then
    graceful_close_ok="true"
  fi
  add_check "Real window close exits the app and its sidecar" "$graceful_close_ok" \
    "app_gone=$([ "$app_gone" -eq 0 ] && echo yes || echo no), sidecar_gone=$([ "$sidecar_gone" -eq 0 ] && echo yes || echo no)"

  # Distinguishes the graceful /shutdown path from the killpg fallback: the
  # sidecar only prints this line if serve_forever() returned on its own
  # (the /shutdown route succeeded), never on a signal death or the stdin
  # lifeline's os._exit(0). Not strict proof by itself (a real SIGINT would
  # also print it, since server.py's except KeyboardInterrupt falls through
  # to the same line) — but nothing in this harness's close path ever sends
  # SIGINT, only the wmctrl close, so the distinction holds here.
  clean_shutdown_line="false"
  if grep -q "shutdown: server stopped cleanly" "$app_log" 2>/dev/null; then
    clean_shutdown_line="true"
  fi
  add_check "Sidecar took the graceful /shutdown path, not the killpg fallback" "$clean_shutdown_line" ""
else
  add_check "Real window close exits the app and its sidecar" "false" "no window to close"
fi

if [ "$graceful_close_ok" != "true" ]; then
  kill -9 "$app_pid" 2>/dev/null || true
  kill -9 "$sidecar_pid" 2>/dev/null || true
fi

echo "=== Reopening (proves the app isn't left in a broken state after a real close) ==="
runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
  "$bin_path" > "$evidence_dir/app_reopen.log" 2>&1 &
reopen_launcher_pid=$!
owned_pids+=("$reopen_launcher_pid")
reopen_app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 40 || true)"
add_check "App reopens after a real close" "$([ -n "$reopen_app_pid" ] && echo true || echo false)" "PID ${reopen_app_pid:-none}"
if [ -n "$reopen_app_pid" ]; then
  owned_pids+=("$reopen_app_pid")
  reopen_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 20 || true)"
  [ -n "$reopen_sidecar_pid" ] && owned_pids+=("$reopen_sidecar_pid")
  kill -9 "$reopen_app_pid" 2>/dev/null || true
  [ -n "${reopen_sidecar_pid:-}" ] && kill -9 "$reopen_sidecar_pid" 2>/dev/null || true
fi

echo "=== Opening a real STL (item 12) and exiting it via SIGTERM as the test user (item 21) ==="
# Every existing SIGTERM proof in linux-ci.yml runs as root; this is the
# first proof it also works for the actual installed-app (non-root) user.
stl_fixture_src="$repo_root/examples/sample_cube.stl"
if [ ! -f "$stl_fixture_src" ]; then
  add_check "STL fixture exists" "false" "$stl_fixture_src not found"
else
  stl_fixture_copy="$user_home/sample_cube.stl"
  cp "$stl_fixture_src" "$stl_fixture_copy"
  chown "$test_user:$test_user" "$stl_fixture_copy"
  runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
    "$bin_path" "$stl_fixture_copy" > "$evidence_dir/app_stl.log" 2>&1 &
  stl_launcher_pid=$!
  owned_pids+=("$stl_launcher_pid")
  stl_app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 40 || true)"
  add_check "STL launch starts the app" "$([ -n "$stl_app_pid" ] && echo true || echo false)" "PID ${stl_app_pid:-none}"
  if [ -n "$stl_app_pid" ]; then
    owned_pids+=("$stl_app_pid")
    stl_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 20 || true)"
    [ -n "$stl_sidecar_pid" ] && owned_pids+=("$stl_sidecar_pid")
    stl_row=""
    for _ in $(seq 1 20); do
      [ -f "$db_path" ] || { sleep 0.5; continue; }
      stl_row="$(sqlite3 "$db_path" "SELECT source_path FROM projects WHERE source_path LIKE '%sample_cube.stl';" 2>/dev/null || true)"
      [ -n "$stl_row" ] && break
      sleep 0.5
    done
    add_check "STL launch-file path recorded a library.db row" "$([ -n "$stl_row" ] && echo true || echo false)" "$stl_row"

    kill -TERM "$stl_app_pid" 2>/dev/null || true
    term_deadline=$(($(date +%s) + 10))
    app_term_gone=1
    while [ "$(date +%s)" -lt "$term_deadline" ]; do
      kill -0 "$stl_app_pid" 2>/dev/null || { app_term_gone=0; break; }
      sleep 0.25
    done
    sidecar_term_gone=1
    if [ -n "${stl_sidecar_pid:-}" ]; then
      term_deadline=$(($(date +%s) + 10))
      while [ "$(date +%s)" -lt "$term_deadline" ]; do
        kill -0 "$stl_sidecar_pid" 2>/dev/null || { sidecar_term_gone=0; break; }
        sleep 0.25
      done
    fi
    add_check "SIGTERM as the test user leaves zero sidecars" \
      "$([ "$app_term_gone" -eq 0 ] && [ "$sidecar_term_gone" -eq 0 ] && echo true || echo false)" \
      "app_gone=$([ "$app_term_gone" -eq 0 ] && echo yes || echo no) sidecar_gone=$([ "$sidecar_term_gone" -eq 0 ] && echo yes || echo no)"
    [ "$app_term_gone" -ne 0 ] && { kill -9 "$stl_app_pid" 2>/dev/null || true; }
    [ -n "${stl_sidecar_pid:-}" ] && [ "$sidecar_term_gone" -ne 0 ] && { kill -9 "$stl_sidecar_pid" 2>/dev/null || true; }
  fi
fi

echo "=== SIGKILL as the test user leaves zero sidecars (item 22) ==="
runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
  "$bin_path" "$fixture_copy" > "$evidence_dir/app_sigkill.log" 2>&1 &
sigkill_launcher_pid=$!
owned_pids+=("$sigkill_launcher_pid")
sigkill_app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 40 || true)"
if [ -n "$sigkill_app_pid" ]; then
  owned_pids+=("$sigkill_app_pid")
  sigkill_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 20 || true)"
  [ -n "$sigkill_sidecar_pid" ] && owned_pids+=("$sigkill_sidecar_pid")
  kill -KILL "$sigkill_app_pid" 2>/dev/null || true
  kill_deadline=$(($(date +%s) + 10))
  sidecar_kill_gone=1
  if [ -n "${sigkill_sidecar_pid:-}" ]; then
    while [ "$(date +%s)" -lt "$kill_deadline" ]; do
      kill -0 "$sigkill_sidecar_pid" 2>/dev/null || { sidecar_kill_gone=0; break; }
      sleep 0.25
    done
  fi
  add_check "SIGKILL as the test user leaves zero sidecars" \
    "$([ "$sidecar_kill_gone" -eq 0 ] && echo true || echo false)" \
    "sidecar_gone=$([ "$sidecar_kill_gone" -eq 0 ] && echo yes || echo no) — proven by the three-layer lifeline (PDEATHSIG/process-group), not this harness"
  [ -n "${sigkill_sidecar_pid:-}" ] && { kill -9 "$sigkill_sidecar_pid" 2>/dev/null || true; }
else
  add_check "SIGKILL as the test user leaves zero sidecars" "false" "app never appeared to be killed"
fi

echo "=== Repeated launch/close cycles as the test user, zero accumulated orphans (item 23), sidecar-crash-first survival (item 24) ==="
repeat_cycles_ok="true"
for cycle in 1 2 3; do
  runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
    "$bin_path" > "$evidence_dir/app_cycle_${cycle}.log" 2>&1 &
  cyc_launcher_pid=$!
  owned_pids+=("$cyc_launcher_pid")
  cyc_app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 30 || true)"
  if [ -z "$cyc_app_pid" ]; then
    repeat_cycles_ok="false"
    break
  fi
  owned_pids+=("$cyc_app_pid")
  cyc_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 15 || true)"
  [ -n "$cyc_sidecar_pid" ] && owned_pids+=("$cyc_sidecar_pid")
  cyc_window=""
  for _ in $(seq 1 30); do
    cyc_window="$(xdotool search --name '^Snapmaker Studio$' 2>/dev/null | head -n1 || true)"
    [ -n "$cyc_window" ] && break
    sleep 0.5
  done
  if [ "$cycle" -eq 1 ] && [ -n "${cyc_sidecar_pid:-}" ]; then
    # Kill only the sidecar and prove the app itself survives — there is no
    # auto-restart mechanism anywhere in desktop/src by design; the frontend
    # polls /health every 10s and shows "Reconnecting…" (StatusBar.tsx).
    kill -9 "$cyc_sidecar_pid" 2>/dev/null || true
    sleep 12
    add_check "App survives sidecar-crash-first (no auto-restart, stays open)" \
      "$(kill -0 "$cyc_app_pid" 2>/dev/null && echo true || echo false)" ""
  fi
  if [ -n "$cyc_window" ]; then
    wmctrl -ic "$cyc_window" 2>/dev/null || true
  else
    kill -TERM "$cyc_app_pid" 2>/dev/null || true
  fi
  for _ in $(seq 1 30); do kill -0 "$cyc_app_pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$cyc_app_pid" 2>/dev/null; then
    kill -9 "$cyc_app_pid" 2>/dev/null || true
    repeat_cycles_ok="false"
  fi
done
# A few seconds' grace before the sweep: --init (tini) reaps exited
# children on SIGCHLD, but that isn't instant, especially after several
# back-to-back launch/kill cycles in quick succession.
sleep 3
leftover_after_cycles="$(pgrep -u "$test_uid" 2>/dev/null || true)"
# On the existing (non-clean) job, the only leftover was the main session
# D-Bus bus (dbus-launch/dbus-daemon --session), auto-launched once per X
# display and designed to outlive every app instance, like Xvfb/openbox.
# On a genuinely clean image (this job's whole point) the .deb's fuller
# dependency closure includes the AT-SPI accessibility stack and the
# desktop-portal stack, and the FIRST run here found their daemons also
# leftover, all ppid=1 (reparented after their launching process exited),
# all D-Bus-activated session infrastructure — confirmed via a diagnostic
# dump, not assumed: at-spi-bus-launcher, a second dbus-daemon serving
# only the AT-SPI accessibility.conf bus, at-spi2-registryd,
# xdg-desktop-portal, xdg-desktop-portal-gtk (the same package whose
# python3-gi dependency is the earlier documented, expected finding),
# xdg-permission-store. Every one of these is activated once, session-
# scoped, and meant to persist — none of them is started or owned by any
# single app launch this harness makes. Matched by argv[0] (the absolute
# executable path), not a substring of the full command line, so a flag
# change upstream can't silently stop this from matching.
real_leftover=""
for lp in $leftover_after_cycles; do
  largv0="$({ tr '\0' '\n' < "/proc/$lp/cmdline"; } 2>/dev/null | head -n1 || echo '')"
  case "$largv0" in
    dbus-launch|/usr/bin/dbus-daemon|/usr/libexec/at-spi-bus-launcher| \
    /usr/libexec/at-spi2-registryd|/usr/libexec/xdg-desktop-portal| \
    /usr/libexec/xdg-desktop-portal-gtk|/usr/libexec/xdg-permission-store)
      continue ;;
  esac
  real_leftover="$real_leftover $lp"
done
real_leftover="$(echo "$real_leftover" | xargs 2>/dev/null || true)"
if [ -n "$real_leftover" ]; then
  echo "--- DIAGNOSTIC: unexplained processes still under uid=$test_uid after 3 repeated cycles ---" >&2
  for lp in $real_leftover; do
    lstat="$(cat "/proc/$lp/stat" 2>/dev/null || echo '?')"
    lcmd="$({ tr '\0' ' ' < "/proc/$lp/cmdline"; } 2>/dev/null || echo '?')"
    lppid="$(awk '/^PPid:/{print $2; exit}' "/proc/$lp/status" 2>/dev/null || echo '?')"
    echo "pid=$lp ppid=$lppid cmd=[$lcmd] stat=[$lstat]" >&2
  done
fi
add_check "3 repeated launch/close cycles leave zero orphans under the uid" \
  "$([ "$repeat_cycles_ok" = "true" ] && [ -z "$real_leftover" ] && echo true || echo false)" \
  "leftover_pids=${real_leftover:-none} (raw, before excluding known session infrastructure: ${leftover_after_cycles:-none})"

echo "=== Headless API lane: Doctor / Prepare / fidelity / report / painted paths (items 13, 14, 16, 17) ==="
# Drives the sidecar binary DIRECTLY (not through the desktop app) — the
# exact same executable, the exact same stdin lifeline mechanism
# (SNAPSTUDIO_PARENT_LIFELINE=stdin-v1) the app itself uses, just proven
# from a script instead of Rust. This is what makes items 13/14/16/17 real
# executions against real fixtures with known-real expected results
# (backend/tests/fixtures/painted/PROVENANCE.md: the OrcaSlicer-painted
# fixture has exactly 5 referenced slots, 8 painted triangles), not GUI
# coordinate-clicking guesses.
api_workdir="$user_home/api-lane"
runuser -u "$test_user" -- mkdir -p "$api_workdir"
declare -A api_fixtures=(
  [3mf]="$repo_root/examples/demo_u1_showcase.3mf"
  [stl]="$repo_root/examples/sample_cube.stl"
  [painted]="$repo_root/backend/tests/fixtures/painted/orcaslicer-2.4.2-painted-cube.3mf"
)
api_ok="true"
for key in "${!api_fixtures[@]}"; do
  if [ ! -f "${api_fixtures[$key]}" ]; then
    add_check "API lane fixture exists ($key)" "false" "${api_fixtures[$key]} not found"
    api_ok="false"
  fi
done

if [ "$api_ok" = "true" ]; then
  for key in "${!api_fixtures[@]}"; do
    cp "${api_fixtures[$key]}" "$api_workdir/$(basename "${api_fixtures[$key]}")"
  done
  chown -R "$test_user:$test_user" "$api_workdir"

  fifo="$api_workdir/sidecar-stdin.fifo"
  runuser -u "$test_user" -- mkfifo "$fifo"
  # The child's stdin must be READ-ONLY, matching production exactly
  # (Stdio::piped() gives the sidecar a read-only pipe end; the app keeps
  # the write end). Opening this fd read-WRITE (the usual named-pipe
  # self-open trick to avoid blocking on open()) would be wrong here
  # specifically because the CHILD inherits that same read-write fd as its
  # own stdin — meaning the child would hold a write reference to its own
  # read end, so os.read() could never see true EOF no matter what root
  # closes (a real bug caught by the first run of this exact check: it
  # failed). Instead: launch the child with its stdin opened plain `<
  # "$fifo"` (O_RDONLY, blocks until a writer appears) in the background,
  # then have root open the SAME fifo for writing only (O_WRONLY, blocks
  # until a reader appears) — the two blocking opens rendezvous regardless
  # of which starts first, and root's fd is then the ONLY writer, so
  # closing it later genuinely triggers EOF on the child's read.
  handshake_file="$api_workdir/handshake.json"
  runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
    SNAPSTUDIO_PARENT_LIFELINE=stdin-v1 SNAPSTUDIO_PARENT_PID=$$ \
    "$sidecar_exe" < "$fifo" > "$handshake_file" 2>"$api_workdir/sidecar.log" &
  api_sidecar_launcher_pid=$!
  owned_pids+=("$api_sidecar_launcher_pid")
  exec 8> "$fifo"

  api_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 40 || true)"
  add_check "API lane: sidecar starts standalone (non-root, no app)" "$([ -n "$api_sidecar_pid" ] && echo true || echo false)" "PID ${api_sidecar_pid:-none}"

  if [ -n "$api_sidecar_pid" ]; then
    owned_pids+=("$api_sidecar_pid")
    api_port="" api_token=""
    for _ in $(seq 1 40); do
      if [ -s "$handshake_file" ]; then
        api_port="$(jq -r '.port // empty' "$handshake_file" 2>/dev/null || true)"
        api_token="$(jq -r '.token // empty' "$handshake_file" 2>/dev/null || true)"
        [ -n "$api_port" ] && [ -n "$api_token" ] && break
      fi
      sleep 0.5
    done
    add_check "API lane: handshake received (port+token)" "$([ -n "$api_port" ] && [ -n "$api_token" ] && echo true || echo false)" "port=${api_port:-none}"

    if [ -n "$api_port" ] && [ -n "$api_token" ]; then
      api_base="http://127.0.0.1:$api_port"
      api_curl() {
        curl -sS --max-time 15 -H "X-Auth-Token: $api_token" -H "Content-Type: application/json" \
          -d "$2" "$api_base$1" 2>/dev/null || true
      }

      doctor_3mf="$(api_curl /doctor "$(jq -n --arg p "$api_workdir/demo_u1_showcase.3mf" '{path:$p}')")"
      add_check "API /doctor on real 3MF" "$(echo "$doctor_3mf" | jq -e '.verdict' >/dev/null 2>&1 && echo true || echo false)" "$(echo "$doctor_3mf" | jq -c '{verdict}' 2>/dev/null)"

      doctor_stl="$(api_curl /doctor "$(jq -n --arg p "$api_workdir/sample_cube.stl" '{path:$p}')")"
      add_check "API /doctor on real STL" "$(echo "$doctor_stl" | jq -e '.input_type=="stl"' >/dev/null 2>&1 && echo true || echo false)" "$(echo "$doctor_stl" | jq -c '{verdict,input_type}' 2>/dev/null)"

      painted_path="$api_workdir/orcaslicer-2.4.2-painted-cube.3mf"
      doctor_painted="$(api_curl /doctor "$(jq -n --arg p "$painted_path" '{path:$p}')")"
      add_check "API /doctor detects painted colours on the real Orca-painted fixture" "$(echo "$doctor_painted" | jq -e '.painted==true' >/dev/null 2>&1 && echo true || echo false)" "$(echo "$doctor_painted" | jq -c '{painted}' 2>/dev/null)"

      color_plan_out="$(api_curl /color_plan "$(jq -n --arg p "$painted_path" '{path:$p,toolheads:4}')")"
      add_check "API /color_plan classifies the real painted fixture" \
        "$(echo "$color_plan_out" | jq -e 'type=="object" and has("verdict")' >/dev/null 2>&1 && echo true || echo false)" \
        "$(echo "$color_plan_out" | jq -c '{verdict}' 2>/dev/null)"

      mm_doctor_out="$(api_curl /mm_doctor "$(jq -n --arg p "$painted_path" '{path:$p}')")"
      # `type=="object"` alone would also pass on the server's own {"error":
      # ...} bodies (400/401/500) — check the absence of that key AND a real
      # field mm_doctor's assess() actually returns (available==true).
      add_check "API /mm_doctor runs on the real painted fixture" \
        "$(echo "$mm_doctor_out" | jq -e '(has("error") | not) and .available==true' >/dev/null 2>&1 && echo true || echo false)" \
        "$(echo "$mm_doctor_out" | jq -c '{available,overall_level}' 2>/dev/null)"

      convert_src="$api_workdir/demo_u1_showcase.3mf"
      convert_sha_before="$(runuser -u "$test_user" -- sha256sum "$convert_src" | cut -d' ' -f1)"
      convert_out="$(api_curl /convert "$(jq -n --arg p "$convert_src" --arg d "$api_workdir" '{path:$p,out_dir:$d,prepare_mode:"preserve"}')")"
      convert_output_path="$(echo "$convert_out" | jq -r '.output_path // empty' 2>/dev/null || true)"
      convert_created="false"
      [ -n "$convert_output_path" ] && [ -f "$convert_output_path" ] && convert_created="true"
      add_check "API /convert (Prepare) creates a new output file" "$convert_created" "$convert_output_path"
      convert_sha_after="$(runuser -u "$test_user" -- sha256sum "$convert_src" | cut -d' ' -f1)"
      add_check "Original untouched by /convert (hash unchanged)" "$([ "$convert_sha_before" = "$convert_sha_after" ] && echo true || echo false)" "before=$convert_sha_before after=$convert_sha_after"

      if [ "$convert_created" = "true" ]; then
        fidelity_out="$(api_curl /fidelity "$(jq -n --arg o "$convert_src" --arg p "$convert_output_path" '{original:$o,prepared:$p}')")"
        # Real field, not just "is a JSON object" — fidelity.audit() always
        # sets available==true on a real audit; its own {"error": ...} shape
        # (thrown by a genuine backend failure) would otherwise slip past a
        # bare type check.
        add_check "API /fidelity audits the real prepared output" \
          "$(echo "$fidelity_out" | jq -e '(has("error") | not) and .available==true' >/dev/null 2>&1 && echo true || echo false)" \
          "$(echo "$fidelity_out" | jq -c '{available,claims}' 2>/dev/null)"

        report_out="$(api_curl /report "$(jq -n --arg p "$convert_output_path" '{path:$p}')")"
        # readiness_report() always sets readiness_score — a real field, not
        # just "is a JSON object" (which the server's own error bodies are too).
        add_check "API /report runs on the real prepared output" \
          "$(echo "$report_out" | jq -e '(has("error") | not) and (.readiness_score != null)' >/dev/null 2>&1 && echo true || echo false)" \
          "$(echo "$report_out" | jq -c '{verdict,readiness_score}' 2>/dev/null)"
      else
        add_check "API /fidelity audits the real prepared output" "false" "no output to audit (Prepare failed above)"
        add_check "API /report runs on the real prepared output" "false" "no output to report on (Prepare failed above)"
      fi
    fi

    # Close our end of the fifo — the sidecar's stdin lifeline blocks on
    # os.read() until EOF, i.e. until every writer closes; we're the only one.
    exec 8<&-
    lifeline_deadline=$(($(date +%s) + 10))
    lifeline_exited=1
    while [ "$(date +%s)" -lt "$lifeline_deadline" ]; do
      kill -0 "$api_sidecar_pid" 2>/dev/null || { lifeline_exited=0; break; }
      sleep 0.25
    done
    add_check "Standalone sidecar exits via the stdin lifeline (non-root)" "$([ "$lifeline_exited" -eq 0 ] && echo true || echo false)" ""
    [ "$lifeline_exited" -ne 0 ] && { kill -9 "$api_sidecar_pid" 2>/dev/null || true; }
  else
    exec 8<&- 2>/dev/null || true
  fi
fi

echo "=== XDG data directory behavior across 3 configurations (item 19) ==="
xdg_case() {
  local case_name="$1" xdg_val="$2" expect_custom="$3"
  local env_args=(env DISPLAY=":$x_display" HOME="$user_home")
  [ -n "$xdg_val" ] && env_args+=(XDG_DATA_HOME="$xdg_val")
  runuser -u "$test_user" -- "${env_args[@]}" "$bin_path" > "$evidence_dir/app_xdg_${case_name}.log" 2>&1 &
  local launcher_pid=$!
  owned_pids+=("$launcher_pid")
  local pid sidecar_pid=""
  pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 30 || true)"
  if [ -z "$pid" ]; then
    add_check "XDG case ($case_name): app starts, correct dir, mode 0700" "false" "app never started"
    return
  fi
  owned_pids+=("$pid")
  sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 15 || true)"
  [ -n "$sidecar_pid" ] && owned_pids+=("$sidecar_pid")
  sleep 2

  local expected_dir mode used="false"
  if [ "$expect_custom" = "true" ]; then
    expected_dir="$xdg_val/SnapmakerStudio"
  else
    expected_dir="$user_home/.local/share/SnapmakerStudio"
  fi
  [ -d "$expected_dir" ] && used="true"
  mode="$([ -d "$expected_dir" ] && stat -c %a "$expected_dir" 2>/dev/null || true)"
  add_check "XDG case ($case_name): app starts, correct dir, mode 0700" \
    "$([ "$used" = "true" ] && [ "$mode" = "700" ] && echo true || echo false)" \
    "$expected_dir mode=${mode:-none}"

  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  kill -9 "$pid" 2>/dev/null || true
  [ -n "$sidecar_pid" ] && { kill -9 "$sidecar_pid" 2>/dev/null || true; }
}
xdg_case "unset"            ""                                           "false"
xdg_case "absolute-custom"  "$user_home/custom xdg data"                 "true"
xdg_case "relative-ignored" "relative/should/be/ignored"                 "false"

echo "=== Unicode + spaces in file paths (item 18) ==="
unicode_dir="$user_home/Mödel Ördner ✓"
runuser -u "$test_user" -- mkdir -p "$unicode_dir"
unicode_fixture="$unicode_dir/ünï cube (1).3mf"
runuser -u "$test_user" -- cp "$fixture_src" "$unicode_fixture"
runuser -u "$test_user" -- env DISPLAY=":$x_display" XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  "$bin_path" "$unicode_fixture" > "$evidence_dir/app_unicode.log" 2>&1 &
unicode_launcher_pid=$!
owned_pids+=("$unicode_launcher_pid")
unicode_app_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$bin_path" 40 || true)"
add_check "App launches with unicode+spaces path" "$([ -n "$unicode_app_pid" ] && echo true || echo false)" "PID ${unicode_app_pid:-none}"
if [ -n "$unicode_app_pid" ]; then
  owned_pids+=("$unicode_app_pid")
  unicode_sidecar_pid="$(wait_for_process_by_uid_and_argv0 "$test_uid" "$sidecar_exe" 20 || true)"
  [ -n "$unicode_sidecar_pid" ] && owned_pids+=("$unicode_sidecar_pid")
  unicode_row_found="false"
  for _ in $(seq 1 20); do
    if [ -f "$db_path" ]; then
      urow="$(sqlite3 "$db_path" "SELECT source_path FROM projects WHERE source_path = '$unicode_fixture';" 2>/dev/null || true)"
      [ -n "$urow" ] && { unicode_row_found="true"; break; }
    fi
    sleep 0.5
  done
  add_check "Unicode+spaces path recorded byte-exact in library.db" "$unicode_row_found" "$unicode_fixture"
  kill -TERM "$unicode_app_pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$unicode_app_pid" 2>/dev/null || break; sleep 0.25; done
  kill -9 "$unicode_app_pid" 2>/dev/null || true
  [ -n "$unicode_sidecar_pid" ] && { kill -9 "$unicode_sidecar_pid" 2>/dev/null || true; }
fi

kill "$wm_pid" 2>/dev/null || true
kill "$xvfb_pid" 2>/dev/null || true

echo "=== Purging and verifying nothing is left behind ==="
if [ "$pkg_preinstalled" = "true" ]; then
  echo "Skipping purge: $pkg_name was already installed before this run — not removing a real pre-existing install." >&2
  add_check "Purge leaves nothing behind" "true" "skipped: package pre-existed this run, not purged"
else
  installed_files_snapshot="$(dpkg -L "$pkg_name" | while IFS= read -r f; do if [ -f "$f" ]; then echo "$f"; fi; done)"
  apt-get purge -y "$pkg_name"
  leftover_found=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if [ -e "$f" ]; then
      echo "Leftover after purge: $f" >&2
      leftover_found=1
    fi
  done <<< "$installed_files_snapshot"
  add_check "Purge leaves nothing behind" "$([ "$leftover_found" -eq 0 ] && echo true || echo false)" ""
fi

write_report

if any_failed; then
  echo "ACCEPTANCE: FAILED (see acceptance.json)" >&2
  exit 1
fi
echo "ACCEPTANCE: ALL CHECKS PASSED"
