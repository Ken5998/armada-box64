#!/usr/bin/env bash
# Installs (or updates) the Armada Box64 Decky plugin from a release ZIP.
#
#   bash install.sh                          # newest ArmadaBox64-v*.zip next to this script
#   bash install.sh ArmadaBox64-v0.1.0.zip   # a specific ZIP
#
# Only ~/homebrew/plugins/ArmadaBox64 changes. Box64, the Proton tools and the settings in
# ~/.config/armada-box64 stay as they are. sudo is needed because Decky's plugin folder
# belongs to root.
set -euo pipefail

name=ArmadaBox64
plugins="$HOME/homebrew/plugins"
here="$(cd "$(dirname "$0")" && pwd)"

say() { printf '[Armada Box64] %s\n' "$*"; }
die() { printf '[Armada Box64] ERROR: %s\n' "$*" >&2; exit 1; }

zip="${1:-}"
if [[ -z $zip ]]; then
    zip="$(find "$here" -maxdepth 1 -name "$name-v*.zip" | sort -V | tail -n 1)"
    [[ -n $zip ]] || die "No $name-v*.zip next to this script; pass the ZIP's path."
fi
[[ -f $zip ]] || die "Not found: $zip"
[[ -d $plugins ]] || die "$plugins does not exist: is Decky Loader installed?"
for cmd in unzip sha256sum sudo; do
    command -v "$cmd" >/dev/null || die "Missing command: $cmd"
done

if [[ -f "$zip.sha256" ]]; then
    (cd "$(dirname "$zip")" && sha256sum --check --quiet "$(basename "$zip").sha256") || die 'Checksum does not match.'
    say 'Checksum OK.'
fi

while IFS= read -r entry; do
    case "$entry" in
        "$name"/*) ;;
        *) die "Unexpected file in the ZIP: $entry" ;;
    esac
    case "/$entry/" in
        */../*) die "Unsafe path in the ZIP: $entry" ;;
    esac
done < <(unzip -Z1 "$zip")

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
unzip -q "$zip" -d "$tmp"
for need in main.py plugin.json package.json dist/index.js py_modules/armadabox64.py bin/box64-armada/box64; do
    [[ -f "$tmp/$name/$need" ]] || die "The ZIP has no $name/$need."
done
if find "$tmp/$name" -type l | grep -q .; then
    die 'The ZIP contains symbolic links; refusing it.'
fi

say "Installing into $plugins/$name (asks for your password)."
new="$plugins/.$name.new-$$"
old="$plugins/.$name.old-$$"
sudo rm -rf "$new" "$old"
sudo cp -a "$tmp/$name" "$new"
sudo chmod -R a+rX "$new"
if [[ -e "$plugins/$name" ]]; then
    sudo mv "$plugins/$name" "$old"
fi
if ! sudo mv "$new" "$plugins/$name"; then
    [[ -e $old ]] && sudo mv "$old" "$plugins/$name"
    die 'Could not move the new version into place; the old one was restored.'
fi
sudo rm -rf "$old"

if systemctl cat plugin_loader.service >/dev/null 2>&1; then
    sudo systemctl restart plugin_loader.service && say 'Restarted Decky Loader.'
else
    say 'Restart the device to load the plugin.'
fi
say "Done: open Decky's menu and pick Armada Box64."
