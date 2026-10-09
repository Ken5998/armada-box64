#!/usr/bin/env bash
# Builds one Box64 version for the plugin: Box64 for ARM64 Linux (with Box32) plus the x86_64
# and i386 GCC runtime libraries that Wine's Unix side needs, in bin/box64/<tag>.
#
#   bash scripts/build-box64.sh TAG [OUTPUT_DIR]    # default OUTPUT_DIR: bin/box64/TAG
#
# box64-versions lists the tags the plugin ships, newest first.
# Not on ARM64? Set CROSS_PREFIX=aarch64-linux-gnu- to cross-compile.
set -euo pipefail

ref="${1:?usage: build-box64.sh TAG [OUTPUT_DIR]}"
[[ $ref =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid Box64 tag: $ref" >&2; exit 1; }
out="$(realpath -m "${2:-bin/box64/$ref}")"
cross="${CROSS_PREFIX:-}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone --quiet --depth 1 --branch "$ref" https://github.com/ptitSeb/box64 "$work/src"
commit="$(git -C "$work/src" rev-parse HEAD)"

cmake_args=(-DARM64=1 -DBOX32=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo)
case "$(uname -m)" in
    aarch64|arm64) ;;
    *)
        [[ -n $cross ]] || { echo 'Not on ARM64: set CROSS_PREFIX=aarch64-linux-gnu- to cross-compile.' >&2; exit 1; }
        cmake_args+=(-DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 -DCMAKE_C_COMPILER="${cross}gcc")
        ;;
esac
cmake -S "$work/src" -B "$work/build" "${cmake_args[@]}"
cmake --build "$work/build" --target box64 -j "$(nproc)"

rm -rf "$out"
mkdir -p "$out/x64lib" "$out/x86lib"
install -m 755 "$work/build/box64" "$out/box64"
"${cross}strip" "$out/box64"
# The same libraries Box64's own install puts next to it; Wine's ntdll.so needs libgcc_s for unwinding.
for lib in libgcc_s.so.1 libstdc++.so.6; do
    install -m 644 "$work/src/x64lib/$lib" "$out/x64lib/$lib"
    install -m 644 "$work/src/x86lib/$lib" "$out/x86lib/$lib"
done
install -m 644 "$work/src/LICENSE" "$out/box64-LICENSE.txt"
# Per-process sections of the stock box64rc override BOX64_* variables, so none ship here.
printf '# Intentionally empty: settings come from BOX64_* variables (the plugin and launch options).\n' > "$out/box64.box64rc"
# The plugin compares the first line to tell whether the installed Box64 needs an update.
cat > "$out/NOTICE.txt" <<NOTICE
Box64 ${ref} (commit ${commit:0:12})
Source: https://github.com/ptitSeb/box64 at ${commit}
Built with: ${cmake_args[*]}
License: MIT (box64-LICENSE.txt).
x64lib/ and x86lib/ hold the x86_64 and i386 GCC runtime libraries shipped in Box64's
source tree; they are GCC components under the GPL with the GCC Runtime Library Exception.
NOTICE
cat "$out/NOTICE.txt"
