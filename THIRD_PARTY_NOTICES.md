# Third-party notices

## Box64

The plugin ZIP contains Box64 built from https://github.com/ptitSeb/box64 (the tag and commit
are in `bin/box64-armada/NOTICE.txt`). Box64 is MIT licensed; its license is included as
`bin/box64-armada/box64-LICENSE.txt`.

## GCC runtime libraries

`bin/box64-armada/x64lib/` and `bin/box64-armada/x86lib/` hold `libgcc_s.so.1` and
`libstdc++.so.6` for x86_64 and i386, copied from Box64's source tree. They are GCC components
under the GPL with the GCC Runtime Library Exception.

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
