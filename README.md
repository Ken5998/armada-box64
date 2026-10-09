# Armada Box64

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for ArmadaOS and
other ARM64 Linux devices that run Steam. It turns an x86_64 Proton you already have, such as
GE-Proton10-34, into a second compatibility tool, **GE-Proton10-34 (Box64)**, that runs under
[Box64](https://github.com/ptitSeb/box64) instead of FEX. It works the same way GameNative runs
x86_64 Proton on Android. From the Quick Access menu you also pick the NTSync, WoW64 and Box64
settings and the Box64 version for all games or for one game, and install Windows components
(DirectX 9 libraries, Visual C++ runtimes, DirectMusic and others) into a game's prefix.

The original Proton is never changed. The new tool links to its files and starts every x86_64
program through Box64.

## Status

Early version. The Box64 route behind it was tested on ArmadaOS (AYN Odin 2, Adreno 740) with
GE-Proton10-34 in WoW64 mode and Box64 `v0.4.3-3`: a 32-bit Direct3D 9 game reached gameplay with
gamepad input. That is one data point, not a compatibility claim; whether Box64 or FEX works
better depends on the game. The newer Box64 versions and the Windows components have not been
tried on a device yet.

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

1. **Box64**: press **Install Box64**. The plugin copies the Box64 versions it ships to
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
| Box64 version | newest | `ARMADA_BOX64_VERSION`, an installed tag or `latest` |

The presets (Stability, Compatibility, Intermediate, Performance, Unity) use the Box64 values of
the presets with the same names in GameNative. For example, Performance with safe flags 2 is
the setup used while testing a 32-bit DirectX 9 game.

**Box64 versions.** The plugin ships the Box64 tags listed in `box64-versions` (now `v0.4.5-1`,
`v0.4.4` and `v0.4.3-3`, the one tested above). Under **Download another version** it offers the
newest eight Box64 versions published as releases of this repository; **Remove a version**
deletes one. Downloads are checked against the SHA-256 that GitHub lists for the file. Games use
the newest installed version unless you pick another, for all games or for one. If the chosen
version is removed, the game falls back to the newest.

**New Box64 releases.** Once a week the **Box64 builds** workflow looks at upstream's tags,
builds every recent version that has no `box64-<tag>` release yet, and publishes it. The plugin
finds it the next time its menu opens (it checks GitHub at most every six hours; **Check for
updates** checks now).

**Plugin updates.** When a newer `vX.Y.Z` release exists, the plugin shows **Update Armada
Box64**. It downloads the ZIP, checks it, and hands it to Decky's own installer, which asks for
confirmation and reloads the plugin. Settings, tools and Box64 versions stay.

**Windows components** (per game) installs winetricks verbs such as `d3dx9`, `vcrun2008` or
`directmusic` into the game's prefix. Start the game once with a Box64 tool based on GE-Proton
first: the install runs through that same tool. GE-Proton's protonfixes then sets up the prefix
as for a launch and runs its own winetricks with the game's Wine, under Box64. The plugin adds a
native ARM64 `cabextract`. Winetricks downloads the installers, so the device needs internet
access. Some installers open a window. The log is in `~/.config/armada-box64/logs/`. The tool
based on Valve's Proton has no protonfixes and cannot install components.

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
Decky's settings. Box64 and the helpers stay in `~/.local/share/box64-armada` and the settings in
`~/.config/armada-box64`; delete those folders if you no longer want them.

## Build

```bash
pnpm install && pnpm build                                     # dist/index.js
for tag in $(cat box64-versions); do                           # bin/box64/<tag>, on ARM64 Linux
    bash scripts/build-box64.sh "$tag"                         # elsewhere: CROSS_PREFIX=aarch64-linux-gnu-
done
bash scripts/build-helpers.sh                                  # bin/tools (needs autoconf, automake, autopoint)
bash scripts/package.sh                                        # out/ArmadaBox64-vX.Y.Z.zip
python3 -m unittest discover -s tests                         # backend tests
```

To ship another Box64 version inside the plugin, add its tag to `box64-versions` (newest first).
The downloads need the repository to be public: the device fetches releases without a login.

The device needs glibc 2.39 or newer when Box64 is built on Ubuntu 24.04, as in CI. To publish
a release, set the version in `package.json` and push a matching `vX.Y.Z` tag.

## License

MIT, see `LICENSE`. The plugin ships Box64, GCC runtime libraries and cabextract; see
`THIRD_PARTY_NOTICES.md`.
