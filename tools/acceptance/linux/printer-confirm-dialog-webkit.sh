#!/usr/bin/env bash
# Runs the integrated printer-confirmation check (printer-confirm-dialog-webkit.mjs) against an installed Studio.
#
#   sudo tools/acceptance/linux/printer-confirm-dialog-webkit.sh <test-user> <evidence-dir> [app-binary]
#
# Needs: the Studio .deb installed, webkit2gtk-driver, xvfb, nodejs, and tauri-driver in <test-user>'s ~/.cargo/bin.
#
# Why root at all: only to create a network namespace that has a loopback interface and NOTHING else. The app, the
# driver and the script then run as <test-user>, inside it. A printer, the router or any other machine is simply not
# reachable from there, whatever the app tries. Nothing here touches a real printer.
set -euo pipefail

user="${1:?test user}"
out="${2:?evidence dir}"
app="${3:-/usr/bin/snapmaker-studio-desktop}"
here="$(cd "$(dirname "$0")" && pwd)"

if [[ "${INSIDE_NETNS:-}" != "1" ]]; then
  mkdir -p "$out"
  chown "$user" "$out"
  exec unshare --net env INSIDE_NETNS=1 bash "$here/$(basename "$0")" "$user" "$out" "$app"
fi

ip link set lo up
echo "network interfaces in the namespace: $(ip -o link show | awk -F': ' '{print $2}' | tr '\n' ' ')"
echo "routes: $(ip route | wc -l)"

home="$(mktemp -d /tmp/u1-webkit-home.XXXXXX)"
chown "$user" "$home"
# A runtime dir the test user owns, so desktop libraries do not try to write under the root user's /run/user.
runtime="$(mktemp -d /tmp/u1-webkit-run.XXXXXX)"
chown "$user" "$runtime"
chmod 700 "$runtime"
display=":$((120 + RANDOM % 60))"
Xvfb "$display" -screen 0 1280x900x24 -nolisten tcp -noreset >/dev/null 2>&1 &
xpid=$!
cleanup() { kill "$xpid" 2>/dev/null || true; rm -rf "$home" "$runtime"; }
trap cleanup EXIT
sleep 1

runuser -u "$user" -- env HOME="$home" XDG_RUNTIME_DIR="$runtime" XDG_DATA_HOME="$home/data" XDG_CONFIG_HOME="$home/config" XDG_CACHE_HOME="$home/cache" \
  DISPLAY="$display" LANG=C.UTF-8 LC_ALL=C.UTF-8 WEBKIT_DISABLE_COMPOSITING_MODE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  SNAPSTUDIO_DATA_DIR="$home/studio-data" PATH="/home/$user/.cargo/bin:$PATH" \
  node "$here/printer-confirm-dialog-webkit.mjs" --app "$app" --out "$out" --driver "/home/$user/.cargo/bin/tauri-driver"
