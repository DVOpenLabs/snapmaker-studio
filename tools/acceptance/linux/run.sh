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
# dbus-x11 (same packages linux-ci.yml already installs, plus openbox/
# wmctrl/xdotool/imagemagick/sqlite3 for this harness specifically).
#
# Output: $ACCEPT_WORKDIR/evidence/acceptance.json (schema_version
# "acceptance/1", same shape as the Windows harness's report — see
# tools/acceptance/run.ps1), screenshots, and app/sidecar logs, all under
# $ACCEPT_WORKDIR/evidence/. Anonymized: no real IP/hostname/username in
# the JSON (the synthetic user this script creates is not a real identity).
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

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
        "$(printf '%s' "${checks_names[$i]}" | python3.13 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
        "${checks_ok[$i]}" \
        "$(printf '%s' "${checks_detail[$i]}" | python3.13 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
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

# Every process this harness signals, it started itself — tracked here,
# never a bare pkill/killall by name (this project has been bitten before
# by loose process matching touching something it shouldn't).
declare -a owned_pids=()
cleanup() {
  for pid in "${owned_pids[@]:-}"; do
    kill -9 "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

echo "=== Installing the .deb ==="
apt-get update -qq
apt-get install -y --no-install-recommends xvfb openbox wmctrl xdotool imagemagick sqlite3 dbus-x11 >/dev/null
apt-get install -y "$deb_path"
pkg_name="$(dpkg-deb -f "$deb_path" Package)"

installed_files="$(dpkg -L "$pkg_name")"
bin_path=""
while IFS= read -r f; do
  if [[ "$f" =~ ^/usr/bin/[^/]+$ ]]; then
    bin_path="$f"
    break
  fi
done <<< "$installed_files"
if [ -z "$bin_path" ]; then
  add_check "Installed app entry point found" "false" "no /usr/bin/* entry"
  write_report
  exit 1
fi
add_check "Installed app entry point found" "true" "$bin_path"

echo "=== Creating an unprivileged test user (real installs never run as root) ==="
test_user="snapstudio-acceptance"
if ! id "$test_user" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$test_user"
fi
user_home="$(eval echo "~$test_user")"
xdg_data_home="$user_home/.local/share"
chown -R "$test_user:$test_user" "$user_home"

echo "=== Starting Xvfb + a real window manager ==="
Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
xvfb_pid=$!
owned_pids+=("$xvfb_pid")
export DISPLAY=:99
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
fixture_sha_before="$(sudo -u "$test_user" sha256sum "$fixture_copy" | cut -d' ' -f1)"

echo "=== Launching the installed app as $test_user, with the fixture ==="
app_log="$evidence_dir/app.log"
sudo -u "$test_user" env DISPLAY=:99 XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
  "$bin_path" "$fixture_copy" > "$app_log" 2>&1 &
app_shell_pid=$!
owned_pids+=("$app_shell_pid")

# Poll for the real app PID (sudo/env wrap it — find the actual binary
# process, not the wrapper), then its sidecar, by exact executable path.
app_pid=""
for _ in $(seq 1 40); do
  app_pid="$(pgrep -o -u "$test_user" -f "^$bin_path" || true)"
  [ -n "$app_pid" ] && break
  sleep 0.5
done
if [ -z "$app_pid" ]; then
  add_check "App process started" "false" "never appeared within 20s"
  cat "$app_log" >&2 || true
  write_report
  exit 1
fi
add_check "App process started" "true" "PID $app_pid"
owned_pids+=("$app_pid")

sidecar_pid=""
for _ in $(seq 1 40); do
  sidecar_pid="$(pgrep -o -u "$test_user" -f 'snapstudio-api-x86_64-unknown-linux-gnu' || true)"
  [ -n "$sidecar_pid" ] && break
  sleep 0.5
done
if [ -z "$sidecar_pid" ]; then
  add_check "Sidecar spawned from the installed app" "false" "never appeared within 20s"
  write_report
  exit 1
fi
add_check "Sidecar spawned from the installed app" "true" "PID $sidecar_pid"
owned_pids+=("$sidecar_pid")

echo "=== Verifying exactly one app window appears ==="
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
  import -display :99 -window root "$evidence_dir/01-dashboard.png" 2>/dev/null || true
  if [ -f "$evidence_dir/01-dashboard.png" ]; then
    unique_colors="$(convert "$evidence_dir/01-dashboard.png" -format %k info: 2>/dev/null || echo 0)"
    add_check "App renders (screenshot is not a uniform blank window)" "$([ "${unique_colors:-0}" -gt 5 ] && echo true || echo false)" "$unique_colors unique colors"
  else
    add_check "App renders (screenshot is not a uniform blank window)" "false" "screenshot capture failed"
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
fixture_sha_after="$(sudo -u "$test_user" sha256sum "$fixture_copy" | cut -d' ' -f1)"
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
  # lifeline's os._exit(0).
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
sudo -u "$test_user" env DISPLAY=:99 XDG_DATA_HOME="$xdg_data_home" HOME="$user_home" \
  "$bin_path" > "$evidence_dir/app_reopen.log" 2>&1 &
reopen_shell_pid=$!
owned_pids+=("$reopen_shell_pid")
reopen_app_pid=""
for _ in $(seq 1 40); do
  reopen_app_pid="$(pgrep -o -u "$test_user" -f "^$bin_path" || true)"
  [ -n "$reopen_app_pid" ] && break
  sleep 0.5
done
add_check "App reopens after a real close" "$([ -n "$reopen_app_pid" ] && echo true || echo false)" "PID ${reopen_app_pid:-none}"
if [ -n "$reopen_app_pid" ]; then
  owned_pids+=("$reopen_app_pid")
  reopen_sidecar_pid="$(pgrep -o -u "$test_user" -f 'snapstudio-api-x86_64-unknown-linux-gnu' || true)"
  [ -n "$reopen_sidecar_pid" ] && owned_pids+=("$reopen_sidecar_pid")
  kill -9 "$reopen_app_pid" 2>/dev/null || true
  [ -n "$reopen_sidecar_pid" ] && kill -9 "$reopen_sidecar_pid" 2>/dev/null || true
fi

kill "$wm_pid" 2>/dev/null || true
kill "$xvfb_pid" 2>/dev/null || true

echo "=== Purging and verifying nothing is left behind ==="
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

userdel -r "$test_user" 2>/dev/null || true

write_report

if any_failed; then
  echo "ACCEPTANCE: FAILED (see acceptance.json)" >&2
  exit 1
fi
echo "ACCEPTANCE: ALL CHECKS PASSED"
