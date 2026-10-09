# Third-party notices

## Box64

The plugin ZIP contains several Box64 versions built from https://github.com/ptitSeb/box64, one
per folder `bin/box64/<tag>/` (the tag and commit are in its `NOTICE.txt`). Box64 is MIT
licensed; its license is included as `bin/box64/<tag>/box64-LICENSE.txt`.

## GCC runtime libraries

`bin/box64/<tag>/x64lib/` and `bin/box64/<tag>/x86lib/` hold `libgcc_s.so.1` and
`libstdc++.so.6` for x86_64 and i386, copied from Box64's source tree. They are GCC components
under the GPL with the GCC Runtime Library Exception.

## cabextract and libmspack

`bin/tools/bin/cabextract` is cabextract 1.11, built statically for ARM64 from
https://github.com/kyz/libmspack at tag `v1.11` (commit
`305907723a4e7ab2018e58040059ffb5e77db837`) by `scripts/build-helpers.sh`. cabextract is
GPL-3.0-or-later (`bin/tools/cabextract-COPYING.txt`); the libmspack code built into it is
LGPL-2.1 (`bin/tools/libmspack-COPYING.LIB.txt`). The complete source is at that tag, and the
script rebuilds the same program from it.

## winetricks

The plugin does not ship winetricks. `bin/tools/winetricks` is a launcher written for this
plugin that runs the winetricks included with GE-Proton's protonfixes
(https://github.com/Winetricks/winetricks, LGPL-2.1).

## Box64 presets

The Box64 values of the Stability, Compatibility, Intermediate, Performance and Unity presets
match the presets of the same names in GameNative (https://github.com/utkarshdalal/GameNative,
`Box86_64PresetManager`). Only the setting values are used; no GameNative code is included.

## Decky

The frontend uses `@decky/ui`, which Decky Loader provides at runtime, and `@decky/api`, whose
small connection layer is bundled into `dist/index.js`. Both are LGPL-2.1
(https://github.com/SteamDeckHomebrew/decky-frontend-lib). The bundle also contains code from
`react-icons` (MIT).

## Proton and Wine

The plugin does not ship Proton or Wine. It links to and wraps a Proton that is already
installed on the device.
