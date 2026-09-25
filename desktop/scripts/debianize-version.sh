#!/usr/bin/env bash
# Rewrites a built .deb's control Version: field from the project's real
# SemVer prerelease form (X.Y.Z-identifier.N — what tauri.conf.json, git
# tags, and GitHub releases all use) to the Debian-correct form
# (X.Y.Z~identifier.N) that a Debian-family package manager needs.
#
# Why this exists: Tauri's bundler passes `version` straight through
# unchanged into the .deb's control file (verified against the pinned
# tauri-utils 2.9.3 source: the version deserializer at config.rs:3460-3503
# parses it with `semver::Version::from_str`, which REJECTS `~` outright —
# there is no config key, build hook, or env var in this Tauri version that
# can make the bundler itself emit a `~`). And Debian version ordering makes
# a hyphenated prerelease sort ABOVE its eventual plain release, not below
# (`0.10.0-beta.1` is NOT less than `0.10.0` under `dpkg --compare-versions`)
# — the opposite of normal semver intuition, and the opposite of what a
# real upgrade path needs: a user on the beta must be able to `apt upgrade`
# straight into the stable release without `--allow-downgrades`. Debian's
# own convention for exactly this is `~`, which DOES sort below the plain
# release. This script is the one place that translation happens, as an
# explicit, tested, git-tracked packaging-boundary step — run after
# `tauri build --bundles deb` and before the artifact is used anywhere —
# not an ad-hoc rewrite improvised at some other point in the pipeline.
#
# The one rule this script applies, and the only thing it applies: replace
# the LAST literal `-` in the version string with `~`, but only when the
# version actually looks like a prerelease (has a `-` at all). A plain
# release version (no `-`, e.g. "0.9.0") passes through completely
# unchanged — this makes it safe to always run unconditionally in a build
# pipeline, whether or not the version being built is a prerelease.
#
# Usage: debianize-version.sh <path-to-.deb>
# Rewrites the .deb IN PLACE (same path, new contents) if it carries a
# prerelease version; leaves it byte-for-byte untouched otherwise.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: debianize-version.sh <path-to-.deb>" >&2
  exit 2
fi
deb_path="$1"
if [ ! -f "$deb_path" ]; then
  echo "No such file: $deb_path" >&2
  exit 1
fi

semver_version="$(dpkg-deb -f "$deb_path" Version)"

case "$semver_version" in
  *-*)
    # Has a prerelease identifier — translate it. Replace only the LAST
    # `-` (semver allows at most one prerelease segment introduced by `-`,
    # e.g. "0.10.0-beta.1"; build metadata after a literal `+`, if any, is
    # left completely alone — Debian's own version syntax already treats
    # `+` as a legal, ordering-significant character, so no translation is
    # needed or wanted there).
    debian_version="${semver_version%-*}~${semver_version##*-}"
    ;;
  *)
    echo "Version '$semver_version' has no prerelease identifier — nothing to translate, leaving .deb unchanged."
    exit 0
    ;;
esac

echo "Translating Debian Version: '$semver_version' -> '$debian_version'"

workdir="$(mktemp -d)"
dpkg-deb -R "$deb_path" "$workdir"
chmod 755 "$workdir"
sed -i "s/^Version: .*/Version: $debian_version/" "$workdir/DEBIAN/control"
rebuilt="$(mktemp -u --suffix=.deb)"
dpkg-deb -b "$workdir" "$rebuilt"
mv "$rebuilt" "$deb_path"

# Self-check: the whole point of this translation is correct upgrade
# ordering against the eventual plain release. Assert it here, on every
# real invocation, rather than trusting the substitution rule blind — a
# future prerelease-identifier format this rule doesn't handle correctly
# should fail loudly at build time, not silently ship a broken upgrade path.
final_version="${semver_version%%-*}"
if ! dpkg --compare-versions "$debian_version" lt "$final_version"; then
  echo "Translated version '$debian_version' does not sort below the eventual plain release '$final_version' — refusing to ship a broken upgrade path." >&2
  exit 1
fi

new_version_check="$(dpkg-deb -f "$deb_path" Version)"
if [ "$new_version_check" != "$debian_version" ]; then
  echo "Rebuilt .deb's Version does not match the intended translation (got '$new_version_check', expected '$debian_version')." >&2
  exit 1
fi

echo "Debianized: $deb_path now carries Version: $debian_version (verified: sorts below $final_version)"
