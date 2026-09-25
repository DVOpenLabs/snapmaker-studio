#!/usr/bin/env bash
# Linux .deb package-lifecycle verification: install, reinstall, in-place
# upgrade, purge. Extracted from linux-ci.yml (L6) as its own script during
# L8 so the exact same real behaviour can also run inside the clean-image
# matrix job (linux-clean-runtime) without duplicating ~140 lines of YAML
# `run:` block — a single script, called from two places, is the only way
# to guarantee they can't silently drift apart.
#
# Usage: package-lifecycle.sh <path-to-.deb>
# Needs root (apt-get). Requires desktop-file-utils (installed here if
# missing) plus whatever apt/dpkg already provides on the target image —
# deliberately nothing else, so this script itself stays clean-image-safe.
#
# On success prints "PACKAGE VERIFIED: ..." and exits 0. Leaves the package
# PURGED on exit (this is a full lifecycle test, not an install step —
# callers that need the app actually left installed afterward, like
# run.sh's own GUI flow, must reinstall it themselves after calling this).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "This script needs root (apt-get). Run it inside the CI container or as root." >&2
  exit 2
fi
if [ $# -ne 1 ]; then
  echo "usage: package-lifecycle.sh <path-to-.deb>" >&2
  exit 2
fi
deb_path="$1"
if [ ! -f "$deb_path" ]; then
  echo "No such file: $deb_path" >&2
  exit 1
fi
pkg_name="$(dpkg-deb -f "$deb_path" Package)"

# dpkg-query's ${db:Status-Abbrev} is the correct way to ask "is this
# package actually installed" — `dpkg -l "$pkg" | grep '^ii'` looks
# equivalent but a literal `grep -F '^ii'` never matches anything (grep -F
# treats `^` as a literal character, not an anchor) and silently kills
# every step that used it under `set -e`.
installed() {
  # ${db:Status-Abbrev} is contractually 3 characters (desired-action,
  # current-status, error-flag); a clean install is exactly "ii " (trailing
  # space, preserved by $(...) — only trailing NEWLINES get stripped).
  # Matching "ii*" would also accept "iiR" (installed but flagged
  # reinstall-required), which is a real, different state this check
  # should not call healthy.
  case "$(dpkg-query -W -f='${db:Status-Abbrev}' "$1" 2>/dev/null)" in
    "ii ") return 0 ;;
    *) return 1 ;;
  esac
}

timeout -k 5 60 apt-get install -y --no-install-recommends desktop-file-utils >/dev/null
apt-get install -y "$deb_path"
echo "--- Installed files ---"
dpkg -L "$pkg_name"
# Snapshot every real file (not directory) this package installed, BEFORE
# anything is removed — the purge check at the end asserts against this
# real, complete list rather than a hand-picked path list that can silently
# go stale as the bundle's contents change.
installed_files_snapshot="$(dpkg -L "$pkg_name" | while IFS= read -r f; do if [ -f "$f" ]; then echo "$f"; fi; done)"

echo "--- Verifying the installed .desktop file (Categories, and that it validates) ---"
desktop_file=""
while IFS= read -r f; do
  case "$f" in
    /usr/share/applications/*.desktop)
      desktop_file="$f"
      break
      ;;
  esac
done <<< "$(dpkg -L "$pkg_name")"
if [ -z "$desktop_file" ]; then
  echo "No .desktop file found under /usr/share/applications/ in the installed package." >&2
  exit 1
fi
echo "Desktop file: $desktop_file"
categories_line="$(grep -m1 '^Categories=' "$desktop_file" || true)"
echo "Categories line: ${categories_line:-<missing>}"
if [ "$categories_line" = "Categories=" ] || [ -z "$categories_line" ]; then
  echo "Categories is empty or missing — bundle.category in tauri.linux.conf.json did not take effect." >&2
  exit 1
fi
desktop-file-validate "$desktop_file"
echo "Desktop file validated with 0 errors, Categories non-empty."

echo "--- Reinstalling the SAME version (idempotent reinstall) ---"
apt-get install -y --reinstall "$deb_path"
if ! installed "$pkg_name"; then
  echo "Package $pkg_name does not report installed after --reinstall." >&2
  exit 1
fi

echo "--- Upgrading in place (rewritten .deb with a bumped patch version, no second Tauri build) ---"
# Proves version ordering and in-place package replacement — the part of
# "upgrade" that's cheap to test without a second, much slower `tauri
# build`. It does NOT prove that files removed between two real versions
# get cleaned up on upgrade (e.g. a stale file left behind in onedir's
# _internal/): the payload here is byte-identical to the version being
# replaced, only the control Version: field differs. A REAL cross-version
# upgrade test needs a prior released .deb to upgrade FROM — there is none
# yet (no Linux beta has shipped), so this stays a synthetic, honestly
# labelled proof (PACKAGE VERIFIED only, never claimed as a real upgrade).
upgrade_workdir="$(mktemp -d)"
dpkg-deb -R "$deb_path" "$upgrade_workdir"
# dpkg-deb -R doesn't preserve the extraction root's own mode, and
# `mktemp -d` creates it 0700 — since that root becomes the package's own
# "./" entry when rebuilt, an installed package could otherwise claim to
# own a locked-down root directory entry.
chmod 755 "$upgrade_workdir"
current_version="$(dpkg-deb -f "$deb_path" Version)"
upgraded_version="${current_version}+ci-upgrade-test"
sed -i "s/^Version: .*/Version: $upgraded_version/" "$upgrade_workdir/DEBIAN/control"
upgraded_deb="$(mktemp -u --suffix=.deb)"
dpkg-deb -b "$upgrade_workdir" "$upgraded_deb"
apt-get install -y "$upgraded_deb"
installed_version_after="$(dpkg-query -W -f='${Version}' "$pkg_name")"
echo "Version after upgrade: $installed_version_after (was $current_version)"
if [ "$installed_version_after" != "$upgraded_version" ]; then
  echo "Upgrade did not take effect (still $installed_version_after, expected $upgraded_version)." >&2
  exit 1
fi
echo "Upgrade-in-place verified."
rm -rf "$upgrade_workdir" "$upgraded_deb"

echo "--- Purging ---"
# Purge directly from this installed (upgraded) state, not after a separate
# `apt-get remove` first: Tauri's .deb ships no conffiles and no maintainer
# scripts, so `remove` alone already fully uninstalls it — a subsequent
# `purge` would be a meaningless no-op, which is also why an earlier
# version of this step masked its result with `|| true` instead of
# asserting it actually ran.
apt-get purge -y "$pkg_name"
echo "--- Verifying purge left nothing behind ---"
leftover_found=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if [ -e "$f" ]; then
    echo "Leftover after purge: $f" >&2
    leftover_found=1
  fi
done <<< "$installed_files_snapshot"
if [ "$leftover_found" -ne 0 ]; then
  exit 1
fi
if installed "$pkg_name"; then
  echo "Package $pkg_name still reports installed after purge." >&2
  exit 1
fi
echo "PACKAGE VERIFIED: install, reinstall, upgrade-in-place, and purge all behave correctly — every file this package installed is gone."
