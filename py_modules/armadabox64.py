"""Core of the Armada Box64 plugin. Decky's main.py calls it; it also runs on its own:

  python3 armadabox64.py status
  python3 armadabox64.py install-runtime BUNDLE_DIR
  python3 armadabox64.py create PROTON
  python3 armadabox64.py remove TOOL_DIR
  python3 armadabox64.py cleanprefix ID

It creates Steam compatibility tools that run an existing, unmodified x86_64 Proton under
Box64 instead of FEX, and keeps the global and per-game settings those tools read at launch.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# Same marker as the Proton-GameNative box64/ installer, so tools it created are adopted.
MARKER = '.box64-shadow'
RUNTIME = '.local/share/box64-armada'
CONFIG = '.config/armada-box64'

# Box64 settings of GameNative's presets (Winlator's Box86_64PresetManager), BOX64 part only.
PRESETS = {
    'stability': {'SAFEFLAGS': '2', 'FASTNAN': '0', 'FASTROUND': '0', 'X87DOUBLE': '1', 'BIGBLOCK': '0',
                  'STRONGMEM': '2', 'FORWARD': '128', 'CALLRET': '0', 'WAIT': '0',
                  'AVX': '0', 'UNITYPLAYER': '1', 'MMAP32': '0'},
    'compatibility': {'SAFEFLAGS': '2', 'FASTNAN': '0', 'FASTROUND': '0', 'X87DOUBLE': '1', 'BIGBLOCK': '0',
                      'STRONGMEM': '1', 'FORWARD': '128', 'CALLRET': '0', 'WAIT': '1',
                      'AVX': '0', 'UNITYPLAYER': '1', 'MMAP32': '0'},
    'intermediate': {'SAFEFLAGS': '2', 'FASTNAN': '1', 'FASTROUND': '0', 'X87DOUBLE': '1', 'BIGBLOCK': '1',
                     'STRONGMEM': '0', 'FORWARD': '128', 'CALLRET': '0', 'WAIT': '1',
                     'AVX': '0', 'UNITYPLAYER': '0', 'MMAP32': '1'},
    'performance': {'SAFEFLAGS': '1', 'FASTNAN': '1', 'FASTROUND': '1', 'X87DOUBLE': '0', 'BIGBLOCK': '3',
                    'STRONGMEM': '0', 'FORWARD': '512', 'CALLRET': '1', 'WAIT': '1',
                    'AVX': '0', 'UNITYPLAYER': '0', 'MMAP32': '1'},
    'unity': {'SAFEFLAGS': '1', 'FASTNAN': '1', 'FASTROUND': '1', 'X87DOUBLE': '0', 'BIGBLOCK': '3',
              'STRONGMEM': '1', 'FORWARD': '512', 'CALLRET': '1', 'WAIT': '0',
              'AVX': '2', 'UNITYPLAYER': '0', 'MMAP32': '0'},
}
# Not dynarec settings: these go without the DYNAREC_ part of the name.
PLAIN_BOX64 = {'AVX', 'UNITYPLAYER', 'MMAP32'}

# Defaults for every game. They are the settings that worked on ArmadaOS (AYN Odin 2).
DEFAULTS = {
    # Wine's NTSync waits fault under Box64 (ntdll inproc_wait), which kills Wine's XInput
    # thread and with it all gamepad input.
    'ntsync': False,
    # 32-bit games run inside the 64-bit Wine; the classic mode needs Box32, which has no Vulkan.
    'wow64': True,
    # Box64 0.4.3 caches translated code in ~/.cache/box64; a stale cache made wineboot crash.
    'dynacache': False,
    'preset': 'default',
    'safeflags': 'preset',
    'log': False,
}
CHOICES = {
    'preset': ['default', *PRESETS],
    'safeflags': ['preset', '0', '1', '2'],
}
# Fallbacks in every wrapper, for a game started before any settings file exists.
WRAPPER_DEFAULTS = {'PROTON_NO_NTSYNC': '1', 'PROTON_USE_WOW64': '1', 'BOX64_DYNACACHE': '0'}

GAME_ID = re.compile(r'[0-9]{1,20}')
# Written into every tool's proton script; a tool without it predates the current settings support.
WRAPPER_TAG = '# armada-box64 wrapper 1'


class Box64Error(Exception):
    """A problem the user can act on; the message is shown as is."""


def paths(home=None):
    home = home or os.path.expanduser('~')
    steam = os.path.join(home, '.local/share/Steam')
    runtime = os.path.join(home, RUNTIME)
    config = os.path.join(home, CONFIG)
    return {
        'home': home,
        'steam': steam,
        'tools': os.path.join(steam, 'compatibilitytools.d'),
        'common': os.path.join(steam, 'steamapps/common'),
        'compat': os.path.join(steam, 'steamapps/compatdata'),
        'runtime': runtime,
        'box64': os.path.join(runtime, 'box64'),
        'rcfile': os.path.join(runtime, 'box64.box64rc'),
        'config': config,
        'settings': os.path.join(config, 'settings.json'),
        'games': os.path.join(config, 'games'),
        'launches': os.path.join(config, 'launches'),
    }


def sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def write(path, text, executable=False):
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w') as f:
        f.write(text)
    if executable:
        os.chmod(tmp, 0o755)
    os.replace(tmp, path)


def system_env():
    """Decky's backend is a PyInstaller build that points LD_LIBRARY_PATH at its own libraries;
    programs started from it get the system's value back."""
    env = dict(os.environ)
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    else:
        env.pop('LD_LIBRARY_PATH', None)
    return env


def wine_running():
    """True while a wineserver runs, natively or as box64's first argument."""
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                args = f.read().split(b'\0')[:2]
        except OSError:
            continue
        if any(os.path.basename(a) == b'wineserver' for a in args):
            return True
    return False


def require_no_wine():
    if wine_running():
        raise Box64Error('A game is still running: close it and wait a few seconds.')


def elf_machine(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(20)
    except OSError:
        return None
    if head[:4] != b'\x7fELF' or len(head) < 20:
        return None
    return int.from_bytes(head[18:20], 'little' if head[5] == 1 else 'big')


X86_64, AARCH64 = 0x3e, 0xb7


# --- Box64 runtime -------------------------------------------------------------------

def read_notice(directory):
    try:
        with open(os.path.join(directory, 'NOTICE.txt')) as f:
            return f.readline().strip() or None
    except OSError:
        return None


def box64_version(p):
    if not os.access(p['box64'], os.X_OK):
        return None
    try:
        out = subprocess.run([p['box64'], '--version'], capture_output=True, text=True, timeout=20,
                             env=system_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if out.returncode == 0 and text else None


def runtime_status(p, bundle=None):
    installed = read_notice(p['runtime']) if os.path.isfile(p['box64']) else None
    bundled = read_notice(bundle) if bundle else None
    return {
        'version': box64_version(p),
        'installed': installed,
        'bundled': bundled,
        'update': bool(bundled) and installed != bundled,
    }


def install_runtime(p, bundle):
    """Copies the Box64 bundle shipped with the plugin to ~/.local/share/box64-armada, where
    the tools find it even after the plugin is updated or removed."""
    if not os.path.isfile(os.path.join(bundle, 'box64')):
        raise Box64Error(f'No Box64 in {bundle}')
    require_no_wine()
    parent = os.path.dirname(p['runtime'])
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.box64-armada-', dir=parent)
    try:
        shutil.copytree(bundle, os.path.join(staging, 'new'), symlinks=True)
        os.chmod(os.path.join(staging, 'new', 'box64'), 0o755)
        if os.path.lexists(p['runtime']):
            os.replace(p['runtime'], os.path.join(staging, 'old'))
        os.replace(os.path.join(staging, 'new'), p['runtime'])
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    version = box64_version(p)
    if not version:
        raise Box64Error('Box64 was copied but does not run on this system.')
    return version


# --- Proton tools --------------------------------------------------------------------

def read_meta(tool_dir):
    """The marker holds JSON; the older installer wrote 'Created by armada-box64 from SRC'."""
    try:
        with open(os.path.join(tool_dir, MARKER)) as f:
            text = f.read()
    except OSError:
        return None
    try:
        meta = json.loads(text)
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        m = re.search(r'from (.+)$', text.strip())
        return {'source': m.group(1)} if m else {}


def display_name(tool_dir):
    try:
        with open(os.path.join(tool_dir, 'compatibilitytool.vdf')) as f:
            m = re.search(r'"display_name"\s+"([^"]*)"', f.read())
        return m.group(1) if m else os.path.basename(tool_dir)
    except OSError:
        return os.path.basename(tool_dir)


def tools(p):
    if not os.path.isdir(p['tools']):
        return []
    found = []
    for entry in sorted(os.listdir(p['tools'])):
        path = os.path.join(p['tools'], entry)
        meta = read_meta(path)
        if meta is None:
            continue
        source = meta.get('source', '')
        try:
            with open(os.path.join(path, 'proton'), errors='replace') as f:
                outdated = WRAPPER_TAG not in f.read()
        except OSError:
            outdated = True
        found.append({'dir': entry, 'name': display_name(path), 'source': source, 'outdated': outdated,
                      'source_exists': os.path.isfile(os.path.join(source, 'proton'))})
    return found


def proton_arch(path):
    for sub in ('files/bin/wine64', 'files/bin/wine', 'files/bin-wow64/wine'):
        machine = elf_machine(os.path.join(path, sub))
        if machine is not None:
            return machine
    return None


def protons(p):
    """x86_64 Protons that Steam has installed, Box64 tools excluded."""
    found = []
    for base in (p['tools'], p['common']):
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            path = os.path.join(base, entry)
            if not os.path.isfile(os.path.join(path, 'proton')) or os.path.isfile(os.path.join(path, MARKER)):
                continue
            if proton_arch(path) != X86_64:
                continue
            with open(os.path.join(path, 'proton'), errors='replace') as f:
                wow64 = 'PROTON_USE_WOW64' in f.read()
            found.append({'name': entry, 'path': path, 'wow64': wow64})
    return found


def tool_for(p, source):
    for t in tools(p):
        if os.path.realpath(t['source']) == os.path.realpath(source):
            return t
    return None


def wrapper_script(p, source_name):
    defaults = ''.join(f'export {k}="${{{k}-{v}}}"\n' for k, v in WRAPPER_DEFAULTS.items())
    return f'''#!/bin/sh
# Runs {source_name} with Box64 instead of FEX (created by Armada Box64).
{WRAPPER_TAG}
here=$(dirname "$(readlink -f "$0")")
# HODLL selects an ARM64 Proton's 32-bit emulator DLL; it must not leak into an x86_64 Wine.
unset HODLL
export BOX64_RCFILE={sh_quote(p['rcfile'])}
export BOX64_LD_LIBRARY_PATH={sh_quote(p['runtime'] + '/x64lib:' + p['runtime'] + '/x86lib')}
cfg="${{XDG_CONFIG_HOME:-$HOME/.config}}/armada-box64"
# The prefix folder's name is the game's app id, also for non-Steam shortcuts.
game=
[ -n "$STEAM_COMPAT_DATA_PATH" ] && game=$(basename "$STEAM_COMPAT_DATA_PATH")
# Settings files hold KEY=VALUE lines. A variable that is already set, for example in the
# game's launch options, keeps its value.
load() {{
    [ -f "$1" ] || return 1
    while IFS='=' read -r key value; do
        case $key in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
        eval "[ -n \\"\\${{$key+set}}\\" ]" || export "$key=$value"
    done < "$1"
}}
if [ -n "$game" ]; then
    load "$cfg/games/$game.env" || load "$cfg/defaults.env"
    case $1 in run|waitforexitandrun) [ -d "$cfg" ] && echo "$game $(date +%s)" >> "$cfg/launches" ;; esac
else
    load "$cfg/defaults.env"
fi
{defaults}exec python3 "$here/proton.py" "$@"
'''


def create_tool(p, proton_name):
    """Creates (or rebuilds) the Box64 tool for an installed x86_64 Proton. A rebuilt tool keeps
    its folder and display name, so games that already use it keep working."""
    source = next((x for x in protons(p) if x['name'] == proton_name), None)
    if not source:
        raise Box64Error(f'No x86_64 Proton named "{proton_name}" found.')
    if not os.path.isfile(p['box64']):
        raise Box64Error('Install Box64 first.')
    require_no_wine()
    src = source['path']
    existing = tool_for(p, src)
    if existing:
        name, display = existing['dir'], existing['name']
    else:
        name = re.sub(r'[^A-Za-z0-9._-]+', '-', proton_name).strip('-') + '-box64'
        display = f'{proton_name} (Box64)'
    dst = os.path.join(p['tools'], name)
    if os.path.lexists(dst):
        if read_meta(dst) is None:
            raise Box64Error(f'{dst} exists and was not created by Armada Box64; not touching it.')
        shutil.rmtree(dst)
    os.makedirs(dst)
    write(os.path.join(dst, MARKER), json.dumps({'source': src, 'created': int(time.time())}) + '\n')

    for entry in os.listdir(src):
        if entry not in ('files', 'proton', 'compatibilitytool.vdf', 'toolmanifest.vdf'):
            os.symlink(os.path.join(src, entry), os.path.join(dst, entry))

    # Proton finds its files next to sys.argv[0], so a copy of the script here uses the wrapped bin/ below.
    shutil.copy2(os.path.join(src, 'proton'), os.path.join(dst, 'proton.py'))
    write(os.path.join(dst, 'proton'), wrapper_script(p, proton_name), executable=True)

    # Every bin* folder (bin, and bin-wow64 in newer Protons) gets Box64 wrappers; the rest is linked.
    os.makedirs(os.path.join(dst, 'files'))
    for entry in sorted(os.listdir(os.path.join(src, 'files'))):
        real_dir = os.path.join(src, 'files', entry)
        if not (entry.startswith('bin') and os.path.isdir(real_dir) and not os.path.islink(real_dir)):
            os.symlink(real_dir, os.path.join(dst, 'files', entry))
            continue
        os.makedirs(os.path.join(dst, 'files', entry))
        for item in sorted(os.listdir(real_dir)):
            real = os.path.join(real_dir, item)
            link = os.path.join(dst, 'files', entry, item)
            if os.path.isfile(real) and elf_machine(real) is not None:
                # Box64 then runs every x86 program Wine starts (wineserver, loaders) by itself.
                write(link, f'#!/bin/sh\nexec {sh_quote(p["box64"])} {sh_quote(real)} "$@"\n', executable=True)
            else:
                os.symlink(real, link)

    write(os.path.join(dst, 'compatibilitytool.vdf'), f'''"compatibilitytools"
{{
  "compat_tools"
  {{
    "{name}"
    {{
      "install_path" "."
      "display_name" "{display}"
      "from_oslist" "windows"
      "to_oslist" "linux"
    }}
  }}
}}
''')
    # No Steam Linux Runtime: that container is x86_64 and would run everything under FEX again.
    manifest = os.path.join(src, 'toolmanifest.vdf')
    if os.path.isfile(manifest):
        with open(manifest) as f:
            lines = f.read().splitlines()
    else:
        lines = ['"manifest"', '{', '  "version" "2"', '  "commandline" "/proton %verb%"', '}']
    lines = [line for line in lines if not re.search(r'"(require_tool_appid|compatmanager_layer_name)"', line)]
    write(os.path.join(dst, 'toolmanifest.vdf'), '\n'.join(lines) + '\n')
    write_env_files(p, load_settings(p))
    return {'dir': name, 'name': display}


def remove_tool(p, tool_dir):
    if os.path.basename(tool_dir) != tool_dir or tool_dir in ('', '.', '..'):
        raise Box64Error(f'Invalid tool: {tool_dir}')
    path = os.path.join(p['tools'], tool_dir)
    if read_meta(path) is None:
        raise Box64Error(f'{tool_dir} was not created by Armada Box64.')
    require_no_wine()
    shutil.rmtree(path)


# --- Settings ------------------------------------------------------------------------

def clean(values, partial):
    """Keeps known keys with valid values; a partial (per-game) set may leave keys out."""
    out = {}
    for key, default in DEFAULTS.items():
        if key not in values or values[key] is None:
            if not partial:
                out[key] = default
            continue
        value = values[key]
        if isinstance(default, bool):
            if isinstance(value, bool):
                out[key] = value
        elif value in CHOICES[key]:
            out[key] = value
    if not partial:
        for key, default in DEFAULTS.items():
            out.setdefault(key, default)
    return out


def load_settings(p):
    try:
        with open(p['settings']) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    games = data.get('games') if isinstance(data.get('games'), dict) else {}
    return {
        'global': clean(data.get('global') or {}, partial=False),
        'games': {k: clean(v, partial=True) for k, v in games.items()
                  if GAME_ID.fullmatch(k) and isinstance(v, dict)},
    }


def to_env(values):
    env = {
        'PROTON_NO_NTSYNC': '0' if values['ntsync'] else '1',
        'PROTON_USE_WOW64': '1' if values['wow64'] else '0',
        'BOX64_DYNACACHE': '1' if values['dynacache'] else '0',
        'BOX64_LOG': '1' if values['log'] else '0',
    }
    for key, value in PRESETS.get(values['preset'], {}).items():
        env[f'BOX64_{key}' if key in PLAIN_BOX64 else f'BOX64_DYNAREC_{key}'] = value
    if values['safeflags'] != 'preset':
        env['BOX64_DYNAREC_SAFEFLAGS'] = values['safeflags']
    return env


def env_text(env):
    return '# Written by Armada Box64; change it from the plugin.\n' + ''.join(f'{k}={v}\n' for k, v in env.items())


def write_env_files(p, settings):
    """defaults.env serves games without their own settings; games/<id>.env holds the complete
    set for one game, so the wrapper reads exactly one file."""
    os.makedirs(p['games'], exist_ok=True)
    write(os.path.join(p['config'], 'defaults.env'), env_text(to_env(settings['global'])))
    keep = set()
    for game, overrides in settings['games'].items():
        if overrides:
            keep.add(f'{game}.env')
            write(os.path.join(p['games'], f'{game}.env'), env_text(to_env({**settings['global'], **overrides})))
    for entry in os.listdir(p['games']):
        if entry.endswith('.env') and entry not in keep:
            os.remove(os.path.join(p['games'], entry))


def save_settings(p, settings):
    os.makedirs(p['config'], exist_ok=True)
    settings = {'global': clean(settings['global'], partial=False),
                'games': {k: v for k, v in settings['games'].items() if v}}
    write(p['settings'], json.dumps(settings, indent=2, sort_keys=True) + '\n')
    write_env_files(p, settings)
    return settings


def set_global(p, key, value):
    settings = load_settings(p)
    settings['global'] = clean({**settings['global'], key: value}, partial=False)
    return save_settings(p, settings)


def set_game(p, game, key, value):
    """value None returns the setting to the global default."""
    if not GAME_ID.fullmatch(str(game)):
        raise Box64Error(f'Invalid game id: {game}')
    game = str(game)
    settings = load_settings(p)
    current = dict(settings['games'].get(game, {}))
    current.pop(key, None)
    if value is not None:
        current[key] = value
    settings['games'][game] = clean(current, partial=True)
    return save_settings(p, settings)


def reset_game(p, game):
    settings = load_settings(p)
    settings['games'].pop(str(game), None)
    return save_settings(p, settings)


def recent_games(p, limit=12):
    """Games started with a Box64 tool, newest first. Also trims the launch log."""
    try:
        with open(p['launches']) as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    seen = []
    for line in reversed(lines):
        game = line.split(' ', 1)[0]
        if GAME_ID.fullmatch(game) and game not in seen:
            seen.append(game)
    if len(lines) > 400:
        write(p['launches'], ''.join(f'{g} 0\n' for g in reversed(seen)))
    return seen[:limit]


# --- Prefix cleanup ------------------------------------------------------------------

ARM_MACHINES = {0xaa64: 'ARM64', 0xa641: 'ARM64EC', 0x01c4: 'ARMNT', 0xa64e: 'ARM64X'}


def pe_machine(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(4096)
        off = int.from_bytes(head[0x3c:0x40], 'little')
        if head[:2] != b'MZ' or head[off:off + 4] != b'PE\0\0':
            return None
        return int.from_bytes(head[off + 4:off + 6], 'little')
    except (OSError, ValueError):
        return None


def cleanprefix(p, game):
    """A prefix first created by an ARM64 Proton keeps ARM64 DLLs and Wow64 registry keys
    that make x86_64 Wine fail with c000007b. Moves them aside; nothing is deleted."""
    game = str(game)
    if not GAME_ID.fullmatch(game):
        raise Box64Error(f'Invalid game id: {game}')
    pfx = os.path.join(p['compat'], game, 'pfx')
    if not os.path.isdir(pfx):
        raise Box64Error('This game has no Proton prefix yet.')
    require_no_wine()
    keep = os.path.join(pfx, f'arm64-leftovers-{time.strftime("%Y%m%d-%H%M%S")}')
    report = []
    for sub in ('system32', 'syswow64'):
        base = os.path.join(pfx, 'drive_c', 'windows', sub)
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            path = os.path.join(base, entry)
            why = None
            if os.path.islink(path) and re.search(r'aarch64|arm64', os.readlink(path)):
                why = 'link to ' + os.readlink(path)
            elif os.path.isfile(path) and not os.path.islink(path) and pe_machine(path) in ARM_MACHINES:
                why = ARM_MACHINES[pe_machine(path)]
            if why:
                os.makedirs(os.path.join(keep, sub), exist_ok=True)
                os.replace(path, os.path.join(keep, sub, entry))
                report.append(f'Moved {sub}/{entry} ({why})')
    reg = os.path.join(pfx, 'system.reg')
    if os.path.isfile(reg):
        out, skip, removed = [], False, []
        with open(reg, encoding='utf-8', errors='surrogateescape') as f:
            lines = f.read().split('\n')
        for line in lines:
            if line.startswith('['):
                skip = bool(re.match(r'^\[Software\\\\(Wow6432Node\\\\)?Microsoft\\\\Wow64(\\\\|\])', line, re.I))
                if skip:
                    removed.append(line.split(']')[0] + ']')
            if not skip:
                out.append(line)
        if removed:
            os.makedirs(keep, exist_ok=True)
            shutil.copy2(reg, os.path.join(keep, 'system.reg'))
            with open(reg + '.tmp', 'w', encoding='utf-8', errors='surrogateescape') as f:
                f.write('\n'.join(out))
            os.replace(reg + '.tmp', reg)
            report += [f'Removed registry key {key}' for key in removed]
    return {'moved': len(report), 'backup': keep if report else None, 'report': report}


# --- Command line --------------------------------------------------------------------

def state(p, bundle=None):
    return {
        'runtime': runtime_status(p, bundle),
        'protons': protons(p),
        'tools': tools(p),
        'settings': load_settings(p),
        'recent': recent_games(p),
        'presets': CHOICES['preset'],
    }


def main(argv):
    p = paths()
    mode, args = (argv[0] if argv else 'status'), argv[1:]
    try:
        if mode == 'status':
            print(json.dumps(state(p), indent=2))
        elif mode == 'install-runtime' and len(args) == 1:
            print(install_runtime(p, args[0]))
        elif mode == 'create' and len(args) == 1:
            print('Created', create_tool(p, args[0])['name'], '- restart Steam to see it.')
        elif mode == 'remove' and len(args) == 1:
            remove_tool(p, args[0])
        elif mode == 'cleanprefix' and len(args) == 1:
            result = cleanprefix(p, args[0])
            print('\n'.join(result['report']) or 'Nothing ARM64-specific found in the prefix.')
        else:
            sys.exit(__doc__)
    except Box64Error as e:
        sys.exit(str(e))


if __name__ == '__main__':
    main(sys.argv[1:])
