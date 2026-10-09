"""Core of the Armada Box64 plugin. Decky's main.py calls it; it also runs on its own:

  python3 armadabox64.py status
  python3 armadabox64.py install-runtime BUNDLE_DIR      # the plugin's bin/ folder
  python3 armadabox64.py create PROTON
  python3 armadabox64.py remove TOOL_DIR
  python3 armadabox64.py cleanprefix ID
  python3 armadabox64.py components ID VERB...          # install Windows components with winetricks
  python3 armadabox64.py versions                       # Box64 versions to download
  python3 armadabox64.py download TAG                   # download one Box64 version
  python3 armadabox64.py remove-version TAG

It creates Steam compatibility tools that run an existing, unmodified x86_64 Proton under
Box64 instead of FEX, and keeps the global and per-game settings those tools read at launch.
"""
import hashlib
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
    # A Box64 tag from the runtime, or the newest one.
    'box64': 'latest',
}
CHOICES = {
    'preset': ['default', *PRESETS],
    'safeflags': ['preset', '0', '1', '2'],
}
# Fallbacks in every wrapper, for a game started before any settings file exists.
WRAPPER_DEFAULTS = {'PROTON_NO_NTSYNC': '1', 'PROTON_USE_WOW64': '1', 'BOX64_DYNACACHE': '0'}

GAME_ID = re.compile(r'[0-9]{1,20}')
BOX64_TAG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
# Written into every tool's proton script; a tool without it predates the current settings support.
WRAPPER_TAG = '# armada-box64 wrapper 2'

# Windows components offered per game, as winetricks verbs. They install through GE-Proton's
# protonfixes, which runs winetricks with the game's own Wine and prefix.
COMPONENTS = [
    'd3dx9', 'd3dcompiler_47', 'd3dx11_43', 'xact', 'xinput', 'dsound', 'dinput8',
    'directmusic', 'directplay', 'directshow',
    'vcrun2005', 'vcrun2008', 'vcrun2010', 'vcrun2012', 'vcrun2013', 'vcrun2022',
    'corefonts', 'physx',
]


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
        'versions': os.path.join(runtime, 'versions'),
        # The newest version, through the 'latest' link.
        'box64': os.path.join(runtime, 'versions', 'latest', 'box64'),
        'helpers': os.path.join(runtime, 'tools'),
        'logs': os.path.join(config, 'logs'),
        'config': config,
        # Plugin updates wait here for Decky to install them.
        'cache': os.path.join(home, '.cache/armada-box64'),
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
#
# The plugin's bin/ folder holds box64/<tag>/ for the Box64 versions it ships and tools/ with
# the helpers for Windows components. The runtime in ~/.local/share/box64-armada has
# versions/<tag>/ (shipped or downloaded), versions/latest (a link to the newest tag) and
# tools/. Top-level links to the newest version keep tools made by older installers working.

LEGACY_LINKS = ('box64', 'x64lib', 'x86lib', 'box64.box64rc')
# Box64 builds and plugin releases are published as GitHub releases of this repository:
# box64-<tag> holds box64-<tag>-arm64.tar.gz, v<version> holds the plugin ZIP.
RELEASES_URL = 'https://api.github.com/repos/Ken5998/armada-box64/releases?per_page=100'
# How many Box64 versions the plugin offers for download, newest first.
KEEP_VERSIONS = 8
CATALOG_MAX_AGE = 6 * 3600


def read_notice(directory):
    try:
        with open(os.path.join(directory, 'NOTICE.txt')) as f:
            return f.readline().strip() or None
    except OSError:
        return None


def version_key(tag):
    return [int(n) for n in re.findall(r'[0-9]+', tag)]


def versions_in(directory):
    """Box64 tags found in a folder, newest first."""
    if not os.path.isdir(directory):
        return []
    tags = [d for d in os.listdir(directory) if d != 'latest' and BOX64_TAG.fullmatch(d)
            and os.path.isfile(os.path.join(directory, d, 'box64'))]
    return sorted(tags, key=version_key, reverse=True)


def box64_version(path):
    if not os.access(path, os.X_OK):
        return None
    try:
        out = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=20,
                             env=system_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if out.returncode == 0 and text else None


def runtime_status(p, bundle=None):
    installed = versions_in(p['versions'])
    bundled = versions_in(os.path.join(bundle, 'box64')) if bundle else []
    stale = [t for t in bundled if read_notice(os.path.join(p['versions'], t))
             != read_notice(os.path.join(bundle, 'box64', t))]
    return {
        'version': box64_version(p['box64']),
        'installed': installed,
        'bundled': bundled,
        # Downloaded versions are not part of this: the plugin's own versions are new or changed.
        'update': bool(bundled) and (bool(stale) or not os.path.isfile(os.path.join(p['helpers'], 'winetricks'))),
    }


def link_latest(p):
    """Points versions/latest and the top-level links of older tools at the newest version."""
    tags = versions_in(p['versions'])
    if not tags:
        return
    tmp = os.path.join(p['versions'], f'.latest-{os.getpid()}')
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(tags[0], tmp)
    os.replace(tmp, os.path.join(p['versions'], 'latest'))
    for name in LEGACY_LINKS:
        path = os.path.join(p['runtime'], name)
        target = os.path.join('versions', 'latest', name)
        if os.path.islink(path) and os.readlink(path) == target:
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        os.symlink(target, path)


def put_version(p, tag, source_dir):
    """Moves a prepared Box64 folder into versions/<tag>, replacing an older copy."""
    dst = os.path.join(p['versions'], tag)
    os.chmod(os.path.join(source_dir, 'box64'), 0o755)
    old = os.path.join(p['versions'], f'.{tag}.old-{os.getpid()}')
    if os.path.lexists(dst):
        os.replace(dst, old)
    os.replace(source_dir, dst)
    shutil.rmtree(old, ignore_errors=True)


def install_runtime(p, bundle):
    """Copies the Box64 versions and helpers shipped with the plugin to ~/.local/share/box64-armada,
    where the tools find them even after the plugin is updated or removed. Versions downloaded
    from the plugin stay."""
    tags = versions_in(os.path.join(bundle, 'box64'))
    if not tags:
        raise Box64Error(f'No Box64 in {bundle}/box64')
    require_no_wine()
    os.makedirs(p['versions'], exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.staging-', dir=p['runtime'])
    try:
        for tag in tags:
            src = os.path.join(bundle, 'box64', tag)
            if read_notice(src) != read_notice(os.path.join(p['versions'], tag)) \
                    or not os.path.isfile(os.path.join(p['versions'], tag, 'box64')):
                copy = os.path.join(staging, tag)
                shutil.copytree(src, copy, symlinks=True)
                put_version(p, tag, copy)
        if os.path.isdir(os.path.join(bundle, 'tools')):
            copy = os.path.join(staging, 'tools')
            shutil.copytree(os.path.join(bundle, 'tools'), copy, symlinks=True)
            old = os.path.join(staging, 'tools.old')
            if os.path.lexists(p['helpers']):
                os.replace(p['helpers'], old)
            os.replace(copy, p['helpers'])
        link_latest(p)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    broken = [t for t in tags if not box64_version(os.path.join(p['versions'], t, 'box64'))]
    if broken:
        raise Box64Error(f'Box64 was copied but does not run on this system: {", ".join(broken)}')
    return box64_version(p['box64'])


def remove_version(p, tag):
    """Removes one Box64 version. Games set to it use the newest version from then on."""
    installed = versions_in(p['versions'])
    if tag not in installed:
        raise Box64Error(f'Box64 {tag} is not installed.')
    if len(installed) == 1:
        raise Box64Error('This is the only Box64 version: the tools need it.')
    require_no_wine()
    shutil.rmtree(os.path.join(p['versions'], tag))
    link_latest(p)
    return versions_in(p['versions'])


# --- Downloads -------------------------------------------------------------------------

def ssl_context():
    import ssl
    try:
        import certifi  # Decky's backend ships it; the system store may be out of its reach.
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def open_url(url, timeout=30):
    import urllib.request
    request = urllib.request.Request(url, headers={'User-Agent': 'armada-box64', 'Accept': 'application/vnd.github+json'})
    kwargs = {'context': ssl_context()} if url.startswith('https:') else {}
    try:
        return urllib.request.urlopen(request, timeout=timeout, **kwargs)
    except OSError as e:
        raise Box64Error(f'Download failed: {getattr(e, "reason", e)}') from e


def download(url, dst, sha256):
    """Downloads to dst and checks the SHA-256 the release lists for the file."""
    digest = hashlib.sha256()
    try:
        with open_url(url, timeout=60) as response, open(dst, 'wb') as f:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                f.write(chunk)
    except OSError as e:
        raise Box64Error(f'Download failed: {e}') from e
    if digest.hexdigest() != sha256:
        os.remove(dst)
        raise Box64Error('The download does not match its checksum; nothing was changed.')


def releases(p, refresh=False):
    """The repository's releases, cached for a few hours (GitHub allows 60 requests an hour)."""
    cache = os.path.join(p['config'], 'releases.json')
    try:
        if not refresh and time.time() - os.path.getmtime(cache) < CATALOG_MAX_AGE:
            with open(cache) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    with open_url(RELEASES_URL) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise Box64Error('GitHub answered with something unexpected.')
    os.makedirs(p['config'], exist_ok=True)
    write(cache, json.dumps(data))
    return data


def asset_sha256(asset):
    digest = asset.get('digest') or ''
    return digest[7:] if digest.startswith('sha256:') and len(digest) == 71 else None


def catalog(p, refresh=False, current=None):
    """Box64 versions to download (newest first) and a newer plugin release, if any."""
    versions, plugin = [], None
    for rel in releases(p, refresh):
        if not isinstance(rel, dict) or rel.get('draft'):
            continue
        tag = str(rel.get('tag_name', ''))
        for asset in rel.get('assets') or []:
            name, sha = asset.get('name', ''), asset_sha256(asset)
            if not sha:
                continue
            m = re.fullmatch(r'box64-(.+)-arm64\.tar\.gz', name)
            if tag.startswith('box64-') and m and m.group(1) == tag[6:] and BOX64_TAG.fullmatch(m.group(1)):
                versions.append({'tag': m.group(1), 'url': asset['browser_download_url'], 'sha256': sha,
                                 'size': asset.get('size', 0)})
            m = re.fullmatch(r'ArmadaBox64-v([0-9]+\.[0-9]+\.[0-9]+)\.zip', name)
            if m and not rel.get('prerelease') and tag == f'v{m.group(1)}' and \
                    (plugin is None or version_key(m.group(1)) > version_key(plugin['version'])):
                plugin = {'version': m.group(1), 'url': asset['browser_download_url'], 'sha256': sha}
    versions.sort(key=lambda v: version_key(v['tag']), reverse=True)
    if plugin and current and version_key(plugin['version']) <= version_key(current):
        plugin = None
    return {'versions': versions[:KEEP_VERSIONS], 'plugin': plugin}


def safe_members(tar, tag):
    """Only regular files and folders inside <tag>/ are unpacked."""
    for member in tar.getmembers():
        parts = member.name.split('/')
        if parts[0] != tag or '..' in parts or member.name.startswith('/') or not (member.isfile() or member.isdir()):
            raise Box64Error(f'Unexpected entry in the download: {member.name}')
        member.mode = 0o755 if member.isdir() or parts[-1] == 'box64' else 0o644
        yield member


def download_version(p, tag, refresh=False):
    """Downloads one Box64 version from the plugin's releases into the runtime."""
    import tarfile
    entry = next((v for v in catalog(p, refresh)['versions'] if v['tag'] == tag), None)
    if not entry:
        raise Box64Error(f'Box64 {tag} is not available for download.')
    if not os.path.isdir(p['versions']):
        raise Box64Error('Install Box64 first.')
    staging = tempfile.mkdtemp(prefix='.download-', dir=p['runtime'])
    try:
        archive = os.path.join(staging, 'box64.tar.gz')
        download(entry['url'], archive, entry['sha256'])
        with tarfile.open(archive) as tar:
            tar.extractall(staging, members=safe_members(tar, tag))
        folder = os.path.join(staging, tag)
        if not os.path.isfile(os.path.join(folder, 'box64')):
            raise Box64Error('The download holds no box64.')
        os.chmod(os.path.join(folder, 'box64'), 0o755)
        if not box64_version(os.path.join(folder, 'box64')):
            raise Box64Error(f'Box64 {tag} does not run on this system.')
        require_no_wine()
        put_version(p, tag, folder)
        link_latest(p)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return versions_in(p['versions'])


def download_plugin(p, current):
    """Downloads a newer plugin ZIP for Decky to install; returns what Decky needs."""
    update = catalog(p, refresh=True, current=current)['plugin']
    if not update:
        raise Box64Error('The plugin is up to date.')
    folder = p['cache']
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.startswith('ArmadaBox64-v') and old.endswith('.zip'):
            os.remove(os.path.join(folder, old))
    dst = os.path.join(folder, f'ArmadaBox64-v{update["version"]}.zip')
    download(update['url'], dst, update['sha256'])
    return {'path': dst, 'version': update['version'], 'sha256': update['sha256']}


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


def fingerprint(src):
    """Changes when the Proton changes in a way its tool would not follow, as after a Steam update
    in place: the copied proton script, or the set of files that are linked or wrapped."""
    digest = hashlib.sha256()
    try:
        with open(os.path.join(src, 'proton'), 'rb') as f:
            digest.update(f.read())
        names = sorted(os.listdir(src))
        for entry in sorted(os.listdir(os.path.join(src, 'files'))):
            names.append(f'files/{entry}')
            path = os.path.join(src, 'files', entry)
            if entry.startswith('bin') and os.path.isdir(path) and not os.path.islink(path):
                names += [f'files/{entry}/{item}' for item in sorted(os.listdir(path))]
    except OSError:
        return None
    digest.update('\0'.join(names).encode('utf-8', 'surrogateescape'))
    return digest.hexdigest()


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
        source_exists = os.path.isfile(os.path.join(source, 'proton'))
        try:
            with open(os.path.join(path, 'proton'), errors='replace') as f:
                outdated = WRAPPER_TAG not in f.read()
        except OSError:
            outdated = True
        # Older installers and the plugin's first version wrote no fingerprint: rebuilding adds one.
        if source_exists and meta.get('fingerprint') != fingerprint(source):
            outdated = True
        found.append({'dir': entry, 'name': display_name(path), 'source': source, 'outdated': outdated,
                      'source_exists': source_exists, 'components': supports_components(path)})
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
    # Remembers which tool started the game; Windows components install with the same one.
    case $1 in run|waitforexitandrun)
        [ -d "$cfg" ] && [ -z "$UMU_ID" ] && echo "$game $(date +%s) $(basename "$here")" >> "$cfg/launches" ;;
    esac
else
    load "$cfg/defaults.env"
fi
{defaults}# The Box64 version: the one chosen in the plugin if it is installed, else the newest.
box64={sh_quote(p['versions'])}/"${{ARMADA_BOX64_VERSION:-latest}}"
[ -x "$box64/box64" ] || box64={sh_quote(p['versions'])}/latest
export ARMADA_BOX64="$box64/box64"
export BOX64_RCFILE="$box64/box64.box64rc"
export BOX64_LD_LIBRARY_PATH="$box64/x64lib:$box64/x86lib"
exec python3 "$here/proton.py" "$@"
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
    write(os.path.join(dst, MARKER),
          json.dumps({'source': src, 'fingerprint': fingerprint(src), 'created': int(time.time())}) + '\n')

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
                # ARMADA_BOX64 comes from the tool's proton script; the default covers direct starts.
                write(link, f'#!/bin/sh\nbox64={sh_quote(p["box64"])}\n'
                            f'exec "${{ARMADA_BOX64:-$box64}}" {sh_quote(real)} "$@"\n', executable=True)
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
        elif key == 'box64':
            if isinstance(value, str) and BOX64_TAG.fullmatch(value):
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
        'ARMADA_BOX64_VERSION': values['box64'],
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
    # An invalid value leaves the setting as it was.
    settings['global'].update(clean({key: value}, partial=True))
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


def launches(p):
    """(game, tool) per start, oldest first; the tool is missing in older lines."""
    try:
        with open(p['launches']) as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        parts = line.split()
        if parts and GAME_ID.fullmatch(parts[0]):
            out.append((parts[0], parts[2] if len(parts) > 2 else None))
    return out


def recent_games(p, limit=12):
    """Games started with a Box64 tool, newest first. Also trims the launch log."""
    entries = launches(p)
    seen, last = [], {}
    for game, tool in reversed(entries):
        if game not in seen:
            seen.append(game)
        if tool and game not in last:
            last[game] = tool
    if len(entries) > 400:
        write(p['launches'], ''.join(f'{g} 0 {last.get(g, "")}'.rstrip() + '\n' for g in reversed(seen)))
    return seen[:limit]


def last_tool(p, game):
    for g, tool in reversed(launches(p)):
        if g == game and tool:
            return tool
    return None


# --- Windows components ----------------------------------------------------------------

def supports_components(tool_dir):
    """GE-Proton runs winetricks inside its own environment when started for it (protonfixes)."""
    try:
        with open(os.path.join(tool_dir, 'proton.py'), errors='replace') as f:
            return 'protonfixes.winetricks(' in f.read()
    except OSError:
        return False


def installed_components(p, game):
    found = []
    for name in ('winetricks.log', 'winetricks.log.forced'):
        try:
            with open(os.path.join(p['compat'], game, 'pfx', name), errors='replace') as f:
                found += [line.strip() for line in f if line.strip()]
        except OSError:
            pass
    return sorted(set(found) & set(COMPONENTS), key=COMPONENTS.index)


def components_command(p, game, verbs, tool=None):
    """The command that installs winetricks verbs into a game's prefix through its Box64 tool:
    GE-Proton prepares the prefix as for a launch, runs winetricks with that Wine, then exits."""
    game = str(game)
    if not GAME_ID.fullmatch(game):
        raise Box64Error(f'Invalid game id: {game}')
    verbs = list(dict.fromkeys(verbs))
    if not verbs or any(v not in COMPONENTS for v in verbs):
        raise Box64Error(f'Unknown component: {", ".join(v for v in verbs if v not in COMPONENTS) or "none"}')
    if not os.path.isdir(os.path.join(p['compat'], game, 'pfx')):
        raise Box64Error('Start the game once first, so that it has a Proton prefix.')
    tool = tool or last_tool(p, game)
    if not tool:
        raise Box64Error('Start the game once with a Box64 tool first.')
    tool_dir = os.path.join(p['tools'], tool)
    if os.path.basename(tool) != tool or read_meta(tool_dir) is None:
        raise Box64Error(f'{tool} is not an Armada Box64 tool.')
    if not supports_components(tool_dir):
        raise Box64Error('Windows components need a GE-Proton based Box64 tool.')
    winetricks = os.path.join(p['helpers'], 'winetricks')
    if not os.path.isfile(winetricks):
        raise Box64Error('Install Box64 again from the plugin: the winetricks helper is missing.')
    env = system_env()
    env.update({
        'STEAM_COMPAT_DATA_PATH': os.path.join(p['compat'], game),
        'STEAM_COMPAT_CLIENT_INSTALL_PATH': p['steam'],
        # protonfixes runs winetricks instead of a game when these three are set.
        'UMU_ID': 'armada-box64',
        'EXE': winetricks,
        'PROTON_VERB': 'waitforexitandrun',
        'WINETRICKS_LATEST_VERSION_CHECK': 'disabled',
    })
    # Installers open windows; gamescope's X display is :0 when the backend has none.
    env.setdefault('DISPLAY', ':0')
    argv = [os.path.join(tool_dir, 'proton'), 'waitforexitandrun', winetricks, '--unattended', *verbs]
    return argv, env


def game_info(p, game):
    game = str(game)
    if not GAME_ID.fullmatch(game):
        raise Box64Error(f'Invalid game id: {game}')
    tool = last_tool(p, game)
    tool_dir = os.path.join(p['tools'], tool) if tool else None
    return {
        'prefix': os.path.isdir(os.path.join(p['compat'], game, 'pfx')),
        'tool': display_name(tool_dir) if tool_dir and os.path.isdir(tool_dir) else None,
        'components_ok': bool(tool_dir) and supports_components(tool_dir),
        'installed': installed_components(p, game),
    }


def install_components(p, game, verbs, tool=None, log=None):
    """Runs the install and waits; returns the components installed afterwards."""
    argv, env = components_command(p, game, verbs, tool)
    require_no_wine()
    if log is None:
        rc = subprocess.run(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL).returncode
    else:
        rc = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
    done = installed_components(p, str(game))
    missing = [v for v in verbs if v not in done]
    if rc or missing:
        raise Box64Error(f'winetricks did not install: {", ".join(missing) or ", ".join(verbs)} (exit {rc})')
    return done


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
        'components': COMPONENTS,
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
        elif mode == 'components' and len(args) >= 2:
            print('Installed:', ', '.join(install_components(p, args[0], args[1:], log=sys.stdout)))
        elif mode == 'versions' and not args:
            installed = versions_in(p['versions'])
            for v in catalog(p, refresh=True)['versions']:
                print(v['tag'], 'installed' if v['tag'] in installed else f'{v["size"] >> 20} MB')
        elif mode == 'download' and len(args) == 1:
            print('Installed:', ', '.join(download_version(p, args[0], refresh=True)))
        elif mode == 'remove-version' and len(args) == 1:
            print('Installed:', ', '.join(remove_version(p, args[0])))
        elif mode == 'cleanprefix' and len(args) == 1:
            result = cleanprefix(p, args[0])
            print('\n'.join(result['report']) or 'Nothing ARM64-specific found in the prefix.')
        else:
            sys.exit(__doc__)
    except Box64Error as e:
        sys.exit(str(e))


if __name__ == '__main__':
    main(sys.argv[1:])
