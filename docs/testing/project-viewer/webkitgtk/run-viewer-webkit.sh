#!/usr/bin/env bash
# Runs viewer-webkit.mjs against an extracted (no root) Studio .deb, on WSLg's graphics session by default.
#
#   run-viewer-webkit.sh <extracted-deb-root> <project.3mf copy> <evidence-dir> [wslg|xvfb] [isolated|open]
#
# wslg     the WSLg Wayland session (graphics-enabled; compositing is NOT disabled). Default.
# xvfb     fallback only: a virtual X display, software GL; GPU-backed WebGL is then NOT exercised.
# isolated runs everything in a user+network namespace (unshare -rn) with only a loopback interface. Default.
# open     no namespace (only if unshare -rn is unavailable; the page's own request list is then the only record).
# No sudo is used anywhere.
set -euo pipefail
root="${1:?extracted deb root}"; project="${2:?project copy}"; out="${3:?evidence dir}"
gfx="${4:-wslg}"; net="${5:-isolated}"
here="$(cd "$(dirname "$0")" && pwd)"
app="$root/usr/bin/snapmaker-studio-desktop"
mkdir -p "$out"

if [[ "$net" == "isolated" && "${INSIDE_NETNS:-}" != "1" ]]; then
  exec unshare -rn env INSIDE_NETNS=1 bash "$here/$(basename "$0")" "$@"
fi
if [[ "$net" == "isolated" ]]; then
  ip link set lo up
  echo "network interfaces in the namespace: $(ip -o link show | awk -F': ' '{print $2}' | tr '\n' ' ')"
  echo "routes: $(ip route | wc -l)"
else
  echo "network: NOT isolated"
fi

home="$(mktemp -d "${TMPDIR:-/tmp}/u1-viewer-home.XXXXXX")"
cleanup() { [[ -n "${xpid:-}" ]] && kill "$xpid" 2>/dev/null || true; rm -rf "$home"; }
trap cleanup EXIT

if [[ "$gfx" == "wslg" ]]; then
  export XDG_RUNTIME_DIR="${WSLG_RUNTIME:-/mnt/wslg/runtime-dir}"
  export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
  export GDK_BACKEND=wayland
  echo "graphics: WSLg Wayland ($WAYLAND_DISPLAY), compositing NOT disabled"
else
  display=":$((120 + RANDOM % 60))"
  Xvfb "$display" -screen 0 1280x1000x24 -nolisten tcp -noreset >/dev/null 2>&1 &
  xpid=$!
  sleep 1
  export DISPLAY="$display" XDG_RUNTIME_DIR="$home/run"; mkdir -p -m 700 "$XDG_RUNTIME_DIR"
  export GDK_BACKEND=x11 WEBKIT_DISABLE_COMPOSITING_MODE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1
  echo "graphics: Xvfb $display, software GL (GPU-backed WebGL NOT exercised)"
fi

export HOME="$home" XDG_DATA_HOME="$home/data" XDG_CONFIG_HOME="$home/config" XDG_CACHE_HOME="$home/cache" LANG=C.UTF-8 LC_ALL=C.UTF-8
export SNAPSTUDIO_DATA_DIR="$home/studio-data"
# Which graphics stack did the app's processes actually load? (a GPU-backed Mesa d3d12 driver vs a software rasterizer)
(
  sleep 10  # the whole run takes less than 25 s; sample while the app is up
  {
    for d in /proc/[0-9]*; do
      p=${d#/proc/}
      c="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null || true)"
      case "$c" in *snapmaker-studio-desktop*|*WebKitWebProcess*|*WebKitGPUProcess*|*WebKitNetworkProcess*) ;; *) continue ;; esac
      echo "pid $p: $(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-60)"
      grep -oE '[^ /]*(d3d12|dxcore|llvmpipe|libLLVM|swrast|zink|radeonsi|iris|libEGL_mesa|libgallium)[^ ]*' /proc/$p/maps 2>/dev/null | sort -u | sed 's/^/    /' || true
    done
    echo "/dev/dxg: $(ls -l /dev/dxg 2>&1 | awk '{print $1, $5, $6}')"
  } > "$out/graphics-libs-loaded.txt" 2>&1
) &
node "$here/viewer-webkit.mjs" --app "$app" --project "$project" --out "$out" --driver "${TAURI_DRIVER:?set TAURI_DRIVER to the tauri-driver path}"
