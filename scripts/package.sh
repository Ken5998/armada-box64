#!/usr/bin/env bash
# Packs the built plugin into out/ArmadaBox64-vVERSION.zip (+ .sha256) for Decky.
# Needs dist/index.js (pnpm build) and bin/box64-armada (scripts/build-box64.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"
for need in dist/index.js bin/box64-armada/box64 bin/box64-armada/NOTICE.txt; do
    [[ -f $need ]] || { echo "Missing $need: build it first (see README)." >&2; exit 1; }
done

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
pkg="$stage/ArmadaBox64"
mkdir -p "$pkg/dist" "$pkg/py_modules" "$pkg/bin"
cp dist/index.js "$pkg/dist/"
cp main.py plugin.json package.json LICENSE README.md THIRD_PARTY_NOTICES.md "$pkg/"
cp py_modules/armadabox64.py "$pkg/py_modules/"
cp -r bin/box64-armada "$pkg/bin/"

mkdir -p out
zip_name="ArmadaBox64-v${version}.zip"
rm -f "out/$zip_name"
(cd "$stage" && zip -qr -X "$OLDPWD/out/$zip_name" ArmadaBox64)
(cd out && sha256sum "$zip_name" > "$zip_name.sha256")
echo "Wrote out/$zip_name"
