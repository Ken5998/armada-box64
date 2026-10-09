# Armada Box64

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for ArmadaOS and
other ARM64 Linux devices that run Steam. It turns an x86_64 Proton you already have, such as
GE-Proton10-34, into a second compatibility tool, **GE-Proton10-34 (Box64)**, that runs under
[Box64](https://github.com/ptitSeb/box64) instead of FEX. It works the same way GameNative runs
x86_64 Proton on Android. From the Quick Access menu you also pick the NTSync, WoW64 and Box64
settings for all games or for one game.

The original Proton is never changed. The new tool links to its files and starts every x86_64
program through Box64.

## Status

Early version. The Box64 route behind it was tested on ArmadaOS (AYN Odin 2, Adreno 740) with
GE-Proton10-34 in WoW64 mode and Box64 `v0.4.3-3`: a 32-bit Direct3D 9 game reached gameplay with
gamepad input. That is one data point, not a compatibility claim; whether Box64 or FEX works
better depends on the game.

## Install

1. Get `ArmadaBox64-vX.Y.Z.zip` and `install.sh` from a release, or from a run of
   **Actions → Build plugin** (the artifact holds both).
2. Copy both to the device, then in Desktop Mode (Konsole) or over ssh:
   ```bash
   bash install.sh
   ```
   It checks the ZIP, asks for your password (Decky's plugin folder belongs to root), replaces
   `~/homebrew/plugins/ArmadaBox64` and restarts Decky Loader.
3. Open the Quick Access menu → Decky → **Armada Box64**.

## Use

1. **Box64**: press **Install Box64**. The plugin copies the Box64 it ships to
   `~/.local/share/box64-armada`, so the tools keep working when the plugin is updated or removed.
2. **Proton**: switch on each x86_64 Proton you want a Box64 version of, then press
   **Restart Steam**.
3. In the game's Properties → Compatibility, pick **<Proton> (Box64)**.
4. Change settings under **Defaults for every game**, or pick the game under **Per game**. A game
   shows up there while it runs, and after it was started once with a Box64 tool.

Settings apply the next time the game starts. Steam launch options always win: a variable set
there, for example `BOX64_DYNAREC_BIGBLOCK=0 %command%`, overrides the plugin.

| Setting | Default | Variables |
| --- | --- | --- |
| NTSync | off | `PROTON_NO_NTSYNC=1`. NTSync waits fault under Box64 (`inproc_wait` in ntdll). This kills Wine's XInput thread, so gamepads stop working |
| WoW64 | on | `PROTON_USE_WOW64=1`. 32-bit games run inside the 64-bit Wine. The classic mode needs Box32, which cannot load Vulkan, so 32-bit DXVK games do not start there |
| Box64 code cache | off | `BOX64_DYNACACHE=0`. A stale cache in `~/.cache/box64` made `wineboot` crash at startup |
| Box64 preset | Box64 defaults | `BOX64_DYNAREC_*`, `BOX64_AVX`, `BOX64_UNITYPLAYER`, `BOX64_MMAP32` |
| Box64 safe flags | from the preset | `BOX64_DYNAREC_SAFEFLAGS` |
| Box64 log | off | `BOX64_LOG`; read it in the Proton log (`PROTON_LOG=1 %command%`) |

The presets (Stability, Compatibility, Intermediate, Performance, Unity) use the Box64 values of
the presets with the same names in GameNative. For example, Performance with safe flags 2 is
the setup used while testing a 32-bit DirectX 9 game.

**Clean the prefix** (per game) helps when a game whose prefix an ARM64 Proton created fails
with `c000007b`: it moves the ARM64 DLLs and the `Wow64` registry keys into
`pfx/arm64-leftovers-<time>/`. Nothing is deleted.

## How it works

- Every ELF file in the Proton's `files/bin*` folders gets a small wrapper that runs it with
  Box64. Box64 then runs every x86_64 process Wine starts. Everything else is a link to the
  original Proton.
- The tool has no Steam Linux Runtime: that container is x86_64 and would bring FEX back.
- The tool's `proton` script reads the settings at every start: `~/.config/armada-box64/games/<app id>.env`
  for a game with its own settings, otherwise `defaults.env`. The app id comes from the prefix
  folder, so non-Steam shortcuts work too. Variables already set (launch options) are kept.
- When Steam updates a Proton in place, its tool still holds the old `proton` script. The plugin
  notices the change and offers **Update this tool**.
- Tools made by the `box64/` installer of
  [Proton-GameNative](https://github.com/Ken5998/Proton-GameNative) are recognized. They ignore the
  plugin's settings until you press **Update this tool**, which rebuilds the tool under its old
  name, so games keep their compatibility tool.
- The core is `py_modules/armadabox64.py`, which also runs without Decky:
  `python3 py_modules/armadabox64.py status`.

## Troubleshooting

- **`wineboot` or `explorer` crashes right away** with many `cannot add DynaCache Block` lines:
  move `~/.cache/box64` aside and keep the Box64 code cache off.
- **Gamepad listed but dead**: `wait failed in the update thread` in the Proton log means NTSync
  is on; switch it off for the game.
- **A new tool does not appear in Steam**: restart Steam.

## Remove

Switch off each Proton in the plugin (this removes the tools), then remove the plugin from
Decky's settings. Box64 stays in `~/.local/share/box64-armada` and the settings in
`~/.config/armada-box64`; delete those folders if you no longer want them.

## Build

```bash
pnpm install && pnpm build                                     # dist/index.js
bash scripts/build-box64.sh                                    # bin/box64-armada, on ARM64 Linux
CROSS_PREFIX=aarch64-linux-gnu- bash scripts/build-box64.sh    # elsewhere
bash scripts/package.sh                                        # out/ArmadaBox64-vX.Y.Z.zip
python3 -m unittest tests.test_core                            # backend tests
```

The device needs glibc 2.39 or newer when Box64 is built on Ubuntu 24.04, as in CI. To publish
a release, set the version in `package.json` and push a matching `vX.Y.Z` tag.

## License

MIT, see `LICENSE`. The plugin ships Box64 and GCC runtime libraries; see
`THIRD_PARTY_NOTICES.md`.
