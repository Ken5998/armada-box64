#!/usr/bin/env bash
# Builds the helpers for Windows components into bin/tools: a static ARM64 cabextract, which
# winetricks needs to unpack Microsoft's redistributables, and the winetricks launcher.
#
#   bash scripts/build-helpers.sh [OUTPUT_DIR]      # default OUTPUT_DIR: bin/tools
#
# Not on ARM64? Set CROSS_PREFIX=aarch64-linux-gnu- to cross-compile.
set -euo pipefail

# cabextract 1.11 from libmspack's repository (tag v1.11).
ref=v1.11
commit=305907723a4e7ab2018e58040059ffb5e77db837
out="$(realpath -m "${1:-bin/tools}")"
cross="${CROSS_PREFIX:-}"
here="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$ref" https://github.com/kyz/libmspack "$work/src"
[[ "$(git -C "$work/src" rev-parse HEAD)" == "$commit" ]] || { echo "libmspack $ref is not $commit" >&2; exit 1; }

host=()
case "$(uname -m)" in
    aarch64|arm64) ;;
    *)
        [[ -n $cross ]] || { echo 'Not on ARM64: set CROSS_PREFIX=aarch64-linux-gnu- to cross-compile.' >&2; exit 1; }
        host=(--host="${cross%-}")
        ;;
esac
(
    cd "$work/src/cabextract"
    autoreconf -i
    # glibc's fnmatch works; a cross build cannot test it and would ask for a replacement.
    ./configure "${host[@]}" LDFLAGS=-static ac_cv_func_fnmatch_works=yes
    make -j "$(nproc)" >/dev/null
)

rm -rf "$out"
mkdir -p "$out/bin"
install -m 755 "$work/src/cabextract/cabextract" "$out/bin/cabextract"
"${cross}strip" "$out/bin/cabextract"
# autoreconf -i adds the GPL text; the built-in libmspack code is LGPL-2.1.
install -m 644 "$work/src/cabextract/COPYING" "$out/cabextract-COPYING.txt"
install -m 644 "$work/src/libmspack/COPYING.LIB" "$out/libmspack-COPYING.LIB.txt"
install -m 755 "$here/helpers/winetricks" "$out/winetricks"
cat > "$out/NOTICE.txt" <<NOTICE
cabextract 1.11 (libmspack ${ref}, commit ${commit:0:12}), https://github.com/kyz/libmspack
License: GPL-3.0-or-later (cabextract-COPYING.txt); it contains libmspack code under
LGPL-2.1 (libmspack-COPYING.LIB.txt). Built as a static ARM64 program.
winetricks: launcher from this plugin; it runs the winetricks that ships with GE-Proton.
NOTICE
cat "$out/NOTICE.txt"
