#!/usr/bin/env bash
# Packs the built plugin into out/ArmadaBox64-vVERSION.zip (+ .sha256) for Decky.
# Needs dist/index.js (pnpm build), bin/box64/<tag> for every tag in box64-versions
# (scripts/build-box64.sh) and bin/tools (scripts/build-helpers.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"
needs=(dist/index.js bin/tools/winetricks bin/tools/bin/cabextract bin/tools/NOTICE.txt)
while read -r tag; do
    [[ -n $tag ]] && needs+=("bin/box64/$tag/box64" "bin/box64/$tag/NOTICE.txt")
done < box64-versions
for need in "${needs[@]}"; do
    [[ -f $need ]] || { echo "Missing $need: build it first (see README)." >&2; exit 1; }
done

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
pkg="$stage/ArmadaBox64"
mkdir -p "$pkg/dist" "$pkg/py_modules" "$pkg/bin/box64"
cp dist/index.js "$pkg/dist/"
cp main.py plugin.json package.json LICENSE README.md THIRD_PARTY_NOTICES.md "$pkg/"
cp py_modules/armadabox64.py "$pkg/py_modules/"
# Only the versions listed in box64-versions, whatever else bin/box64 holds.
while read -r tag; do
    [[ -n $tag ]] && cp -r "bin/box64/$tag" "$pkg/bin/box64/"
done < box64-versions
cp -r bin/tools "$pkg/bin/"

mkdir -p out
zip_name="ArmadaBox64-v${version}.zip"
rm -f "out/$zip_name"
(cd "$stage" && zip -qr -X "$OLDPWD/out/$zip_name" ArmadaBox64)
(cd out && sha256sum "$zip_name" > "$zip_name.sha256")
echo "Wrote out/$zip_name"
