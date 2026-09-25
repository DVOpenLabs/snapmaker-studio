#!/usr/bin/env bash
# Freeze the Snapmaker Studio engine sidecar as a Linux onedir build and stage
# it for Tauri's `bundle.resources` (NOT `externalBin` — the latter works
# cross-platform in Tauri, but only holds a single file, and onedir's output
# is an executable plus a sibling `_internal/` directory that must stay
# together — this project uses `externalBin` for the Windows onefile build).
#
# L2/L3 scope split (Linux support plan, Phase 6): this script's own
# acceptance gate was "the frozen sidecar starts standalone and answers over
# loopback" (see the L2 pre-commit review record for that verification
# evidence) — it deliberately did not touch Tauri config or the Rust spawn
# path, which landed separately in L3: tauri.linux.conf.json's
# bundle.resources entry (`snapstudio-api/`) and sidecar.rs's
# `#[cfg(target_os = "linux")]` resource_dir()-based resolver now consume
# exactly the directory this script stages at
# desktop/src-tauri/bin/linux/snapstudio-api/.
#
# Requires: Python 3.13 with the backend installed (pip install -e backend)
# plus pyinstaller + lxml (pip install -r backend/requirements-build.txt).
#
# Usage (from anywhere): desktop/scripts/build-sidecar.sh
set -euo pipefail

# Resolve the script's own real location, not just the path it was invoked
# through — a symlinked invocation must still build/stage relative to this
# actual file, never to whatever directory contains the symlink.
self="${BASH_SOURCE[0]}"
while [ -L "$self" ]; do
    link="$(readlink "$self")"
    case "$link" in
        /*) self="$link" ;;
        *) self="$(dirname "$self")/$link" ;;
    esac
done
script_dir="$(cd "$(dirname "$self")" && pwd)"
backend="$(cd "$script_dir/../../backend" && pwd)"

# This script only knows how to build for the platform this repo's Linux
# support plan actually targets. Building on anything else would silently
# stage a mislabeled binary under an x86_64/glibc name.
os="$(uname -s)"
arch="$(uname -m)"
if [ "$os" != "Linux" ] || [ "$arch" != "x86_64" ]; then
    echo "This script only builds the Linux x86_64 sidecar (host reports: $os/$arch)." >&2
    echo "PyInstaller builds for the host it runs on — there is no cross-compile here." >&2
    exit 1
fi
triple="x86_64-unknown-linux-gnu"
name="snapstudio-api-$triple"

# Resolve an interpreter rather than assuming `python3` on PATH is 3.13 — a
# release build must not depend on which shell/venv it happens to run from.
# The probe checks the actual runtime requirement (Python >=3.13, per
# backend/pyproject.toml, plus the build deps), not just "some Python that
# happens to have pyinstaller+lxml importable" — a 3.12 interpreter with both
# packages installed must never be silently accepted.
python_bin=""
for candidate in python3.13 python3 python; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    if [ -z "$resolved" ]; then
        continue
    fi
    # Make it absolute if a relative PATH entry (e.g. `./.venv/bin`) produced
    # a relative match, so it still resolves correctly after `pushd` changes
    # the working directory below. Do NOT `realpath`/resolve symlinks here —
    # a venv's `bin/python3.13` is typically a symlink, and following it to
    # its real target bypasses the venv's site-packages entirely (the venv is
    # activated via the symlink's own path, not its resolved target).
    case "$resolved" in
        /*) : ;;
        *) resolved="$PWD/$resolved" ;;
    esac
    # `if sys.version_info...: sys.exit(1)`, not `assert` — an assert is
    # silently skipped when PYTHONOPTIMIZE is set, which would defeat the
    # whole point of this check. Import snapstudio_api.server (what
    # sidecar_main.py itself imports, and what actually gets frozen below),
    # not just snapstudio_core. `-P` (safe-path mode, Python 3.11+ — safe to
    # require since this probe already demands >=3.13; do NOT change this to
    # `-I`/isolated mode, which also drops PYTHONPATH and --user site
    # packages and would break venv/user installs) keeps the current
    # directory OFF sys.path, so this can't (a) false-positive by resolving a
    # relative import merely because the script happens to be invoked from
    # inside backend/ with nothing actually installed, or (b) on a shared
    # multi-user build host, pick up a module planted in whatever directory
    # this script is run from.
    if "$resolved" -P -c "
import sys
if sys.version_info[:2] < (3, 13):
    sys.exit(1)
import PyInstaller, lxml, click
import snapstudio_api.server
" >/dev/null 2>&1; then
        python_bin="$resolved"
        break
    fi
done
if [ -z "$python_bin" ]; then
    echo "No Python >=3.13 with the backend + pyinstaller + lxml installed was found." >&2
    echo "Run: pip install -e backend && pip install -r backend/requirements-build.txt" >&2
    exit 1
fi
echo "Using interpreter: $python_bin"

echo "Freezing sidecar from $backend ..."
pushd "$backend" >/dev/null
# --collect-data snapstudio_core : bundle data/*.json loaded via importlib.resources
# --collect-submodules lxml      : ensure the lxml C-extension parts are included
# --onedir                       : Linux-only — no bootloader fork/exec hop (see
#                                   Phase 3 of the Linux support plan for why this
#                                   matters for the process-lifecycle work).
# --noupx                        : matches the Windows build's choice — skip UPX
#                                   packing for a simpler, more inspectable binary.
"$python_bin" -m PyInstaller --noconfirm --clean --onedir --noupx --name "$name" \
    --collect-data snapstudio_core \
    --collect-submodules lxml \
    sidecar_main.py
popd >/dev/null

src_dir="$backend/dist/$name"
if [ ! -d "$src_dir" ]; then
    echo "PyInstaller did not produce $src_dir" >&2
    exit 1
fi

# Validate the ACTUAL produced binary's ABI, not just the host's uname — the
# host check above only proves this machine reports Linux/x86_64; it does not
# prove the built ELF is what the target-triple name (x86_64-unknown-linux-gnu,
# i.e. glibc) claims. Concrete gap this closes: an x86_64 Alpine/musl host
# would pass the uname check above but PyInstaller would produce a musl-linked
# executable that fails to run on ordinary glibc distros, silently mislabeled
# under a glibc-triple name; a 32-bit Python on an x86_64 kernel could likewise
# emit an ELF32 binary under the x86_64 name.
#
# This is an authoritative check on the raw ELF header and program headers
# (magic/class/machine, then the PT_INTERP segment), not a substring match on
# file(1)'s human-readable description — file(1)'s wording isn't a stable
# parsing interface (differs across libmagic/Toybox/etc.) and, more
# importantly, a substring match can only ever prove ABSENCE of a "musl"
# marker, never PRESENCE of glibc: a statically-linked musl binary, another
# libc, or a file(1) build that omits the interpreter string would all match
# "ELF 64-bit ... x86-64" without ever containing "musl", and would be
# silently accepted. Reading PT_INTERP directly and requiring it to name the
# real glibc dynamic linker is a positive proof, not a negative guess.
produced="$src_dir/$name"
if ! "$python_bin" -P -c "
import struct, sys

path = sys.argv[1]
with open(path, 'rb') as f:
    header = f.read(64)
    if len(header) < 64 or header[:4] != b'\x7fELF':
        sys.exit('not an ELF file')
    ei_class, ei_data = header[4], header[5]
    if ei_class != 2:
        sys.exit('not a 64-bit ELF (EI_CLASS=%d)' % ei_class)
    if ei_data != 1:
        sys.exit('not little-endian (EI_DATA=%d)' % ei_data)
    e_machine, = struct.unpack_from('<H', header, 18)
    EM_X86_64 = 0x3e
    if e_machine != EM_X86_64:
        sys.exit('not x86-64 (e_machine=0x%x)' % e_machine)
    e_phoff, = struct.unpack_from('<Q', header, 32)
    e_phentsize, e_phnum = struct.unpack_from('<HH', header, 54)

    f.seek(e_phoff)
    phdrs = f.read(e_phentsize * e_phnum)
    interp = None
    PT_INTERP = 3
    for i in range(e_phnum):
        entry = phdrs[i * e_phentsize:(i + 1) * e_phentsize]
        p_type, = struct.unpack_from('<I', entry, 0)
        if p_type == PT_INTERP:
            p_offset, p_filesz = struct.unpack_from('<QQ', entry, 8)[0], struct.unpack_from('<Q', entry, 32)[0]
            f.seek(p_offset)
            interp = f.read(p_filesz).rstrip(b'\x00').decode('ascii', 'replace')
            break

    if interp is None:
        sys.exit('no PT_INTERP segment found (statically linked, or not a normal dynamically-linked executable) — refusing a build this script cannot positively identify as glibc')
    # The real, accepted glibc dynamic linker for this arch — not a substring
    # check, an exact match against the one path glibc actually installs there.
    if interp != '/lib64/ld-linux-x86-64.so.2':
        sys.exit('PT_INTERP is %r, not the glibc dynamic linker — refusing to stage a non-glibc build under a glibc target-triple name' % interp)
" "$produced"; then
    echo "ABI validation failed for $produced — see the message above. Refusing to stage it as $name." >&2
    exit 1
fi

# Staged under bin/linux/ (not bin/, where the Windows externalBin build
# lands) as a plain "snapstudio-api" dir — bundle.resources does not apply
# Tauri's automatic target-triple stripping the way externalBin does, so the
# executable inside this directory keeps its full triple-suffixed name
# (snapstudio-api/snapstudio-api-x86_64-unknown-linux-gnu); L3's Rust spawn
# path must resolve that exact filename via app.path().resource_dir().
#
# `cp -a` (not `cp -r`) so timestamps/attributes carry over, then an explicit
# `chmod -R u+rwX,go+rX,go-w` (not `cp -a`'s inherited umask-dependent modes,
# and not a bare `chmod +x`) so the staged tree's permissions are FULLY
# deterministic regardless of the umask this script happens to run under —
# group/other get read+traverse/execute but never write, whatever the source
# tree's own permissive umask may have left on it. onedir's output includes
# the interpreter's shared library and native extension .so files, which must
# stay readable/executable by whoever runs the packaged app.
bin_dir="$script_dir/../src-tauri/bin"
linux_dir="$bin_dir/linux"
dst_dir="$linux_dir/snapstudio-api"
rm -rf "$dst_dir"
mkdir -p "$linux_dir"
# The ancestor directories mkdir -p just (potentially) created are also
# umask-governed, same as the staged tree below — normalize them too, not
# just the leaf snapstudio-api/ directory. No `|| true` here: a failure to
# chmod an ancestor (e.g. a shared checkout where bin/ is owned by another
# account) must abort the script via `set -e`, not be silently swallowed
# while the script goes on to report success with a still-umask-governed
# ancestor directory.
chmod u+rwx,go+rx,go-w "$bin_dir" "$linux_dir"
cp -a "$src_dir" "$dst_dir"
chmod -R u+rwX,go+rX,go-w "$dst_dir"
chmod a+x "$dst_dir/$name"

echo "Sidecar staged -> $dst_dir/$name (+ _internal/)"
