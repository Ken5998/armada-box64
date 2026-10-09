"""Offline checks of the plugin core against a fake Steam home."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armadabox64 as core  # noqa: E402


def fake_elf(machine):
    return b'\x7fELF\x02\x01\x01' + bytes(11) + machine.to_bytes(2, 'little') + bytes(44)


# A stand-in proton script that records the environment it was started with.
FAKE_PROTON = '''#!/usr/bin/env python3
# PROTON_USE_WOW64
import json, os, sys
keys = [k for k in os.environ if k.startswith(('PROTON_', 'BOX64_', 'ARMADA_')) or k == 'HODLL']
if 'ENV_DUMP' in os.environ:
    with open(os.environ['ENV_DUMP'], 'w') as f:
        json.dump({'argv0': sys.argv[0], 'argv': sys.argv[1:], 'env': {k: os.environ[k] for k in keys}}, f)
'''
# What GE-Proton does when protonfixes is asked to run winetricks: it records the installed verbs.
FAKE_GE = FAKE_PROTON + '''# protonfixes.winetricks( is called by GE-Proton here
if os.environ.get('UMU_ID') and os.environ.get('EXE', '').endswith('winetricks'):
    with open(os.path.join(os.environ['STEAM_COMPAT_DATA_PATH'], 'pfx', 'winetricks.log'), 'a') as f:
        f.writelines(v + '\\n' for v in sys.argv[4:] if v != 'corefonts')
    sys.exit(1 if 'corefonts' in sys.argv else 0)
'''


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        self.p = core.paths(str(self.home))
        self.bundle = self.home / 'bundle'
        for tag in ('v0.4.3-3', 'v0.4.5-1'):
            version = self.bundle / 'box64' / tag
            version.mkdir(parents=True)
            (version / 'box64').write_text(f'#!/bin/sh\necho "Box64 {tag} test build"\n')
            (version / 'NOTICE.txt').write_text(f'Box64 {tag} (commit abc)\nmore\n')
        (self.bundle / 'tools').mkdir()
        (self.bundle / 'tools' / 'winetricks').write_text('#!/bin/sh\n')

    def fake_proton(self, name, machine=core.X86_64, base='tools', wow64=True, ge=False):
        src = Path(self.p[base]) / name
        (src / 'files' / 'bin').mkdir(parents=True)
        (src / 'files' / 'lib').mkdir()
        script = FAKE_GE if ge else FAKE_PROTON
        (src / 'proton').write_text(script if wow64 else script.replace('# PROTON_USE_WOW64\n', ''))
        (src / 'files' / 'bin' / 'wine').write_bytes(fake_elf(machine))
        (src / 'files' / 'bin' / 'notes.txt').write_text('not an ELF\n')
        (src / 'toolmanifest.vdf').write_text('"manifest"\n{\n  "require_tool_appid" "1628350"\n  "commandline" "/proton %verb%"\n}\n')
        (src / 'version').write_text('1 test\n')
        return src

    def launch(self, tool_dir, game='123', **launch_options):
        dump = self.home / 'dump.json'
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home), 'ENV_DUMP': str(dump), 'HODLL': 'wowbox64.dll',
               'STEAM_COMPAT_DATA_PATH': f"{self.p['compat']}/{game}", **launch_options}
        subprocess.run([os.environ.get('TEST_SH', 'sh'), f"{self.p['tools']}/{tool_dir}/proton", 'waitforexitandrun', 'game.exe'],
                       env=env, check=True)
        return json.loads(dump.read_text())

    def test_runtime_install_and_status(self):
        self.assertTrue(core.runtime_status(self.p, str(self.bundle))['update'])
        self.assertEqual(core.install_runtime(self.p, str(self.bundle)), 'Box64 v0.4.5-1 test build')
        status = core.runtime_status(self.p, str(self.bundle))
        self.assertEqual(status['installed'], ['v0.4.5-1', 'v0.4.3-3'])
        self.assertEqual(status['bundled'], ['v0.4.5-1', 'v0.4.3-3'])
        self.assertEqual(status['version'], 'Box64 v0.4.5-1 test build')
        self.assertFalse(status['update'])
        # Tools made by older installers use the top-level paths, which lead to the newest version.
        self.assertEqual(core.box64_version(os.path.join(self.p['runtime'], 'box64')), 'Box64 v0.4.5-1 test build')
        (self.bundle / 'box64' / 'v0.4.5-1' / 'NOTICE.txt').write_text('Box64 v0.4.5-1 (commit def)\n')
        self.assertTrue(core.runtime_status(self.p, str(self.bundle))['update'])
        # A plugin update with another set of versions replaces the old set.
        shutil.rmtree(self.bundle / 'box64' / 'v0.4.3-3')
        core.install_runtime(self.p, str(self.bundle))
        self.assertEqual(core.runtime_status(self.p, str(self.bundle))['installed'], ['v0.4.5-1'])
        os.remove(os.path.join(self.p['helpers'], 'winetricks'))
        self.assertTrue(core.runtime_status(self.p, str(self.bundle))['update'])

    def test_version_order(self):
        tags = ['v0.4.3-3', 'v0.4.10', 'v0.4.4', 'v0.4.3-4']
        self.assertEqual(sorted(tags, key=core.version_key, reverse=True), ['v0.4.10', 'v0.4.4', 'v0.4.3-4', 'v0.4.3-3'])

    def test_box64_version_choice(self):
        self.fake_proton('GE-Test')
        core.install_runtime(self.p, str(self.bundle))
        core.create_tool(self.p, 'GE-Test')
        versions = self.p['versions']
        self.assertEqual(self.launch('GE-Test-box64')['env']['ARMADA_BOX64'], f'{versions}/latest/box64')
        core.set_global(self.p, 'box64', 'v0.4.3-3')
        env = self.launch('GE-Test-box64')['env']
        self.assertEqual(env['ARMADA_BOX64'], f'{versions}/v0.4.3-3/box64')
        self.assertEqual(env['BOX64_RCFILE'], f'{versions}/v0.4.3-3/box64.box64rc')
        # A version that is no longer installed falls back to the newest one.
        core.set_game(self.p, '123', 'box64', 'v0.4.0')
        self.assertEqual(self.launch('GE-Test-box64')['env']['ARMADA_BOX64'], f'{versions}/latest/box64')
        core.set_global(self.p, 'box64', '../x')
        self.assertEqual(core.load_settings(self.p)['global']['box64'], 'v0.4.3-3')
        # The wrapped Wine programs run the chosen Box64.
        wine = Path(self.p['tools']) / 'GE-Test-box64' / 'files' / 'bin' / 'wine'
        out = subprocess.run(['sh', str(wine)], env={'PATH': os.environ['PATH'], 'ARMADA_BOX64': f'{versions}/v0.4.3-3/box64'},
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, 'Box64 v0.4.3-3 test build\n')

    def test_lists_only_x86_64_protons(self):
        self.fake_proton('GE-Test')
        self.fake_proton('ARM64-Proton', machine=core.AARCH64)
        self.fake_proton('Proton 9.0', base='common', wow64=False)
        found = {x['name']: x['wow64'] for x in core.protons(self.p)}
        self.assertEqual(found, {'GE-Test': True, 'Proton 9.0': False})

    def test_create_wraps_binaries_and_drops_runtime(self):
        src = self.fake_proton('GE-Test 10')
        with self.assertRaises(core.Box64Error):
            core.create_tool(self.p, 'GE-Test 10')
        core.install_runtime(self.p, str(self.bundle))
        made = core.create_tool(self.p, 'GE-Test 10')
        self.assertEqual(made, {'dir': 'GE-Test-10-box64', 'name': 'GE-Test 10 (Box64)'})
        dst = Path(self.p['tools']) / 'GE-Test-10-box64'
        self.assertIn(self.p['box64'], (dst / 'files' / 'bin' / 'wine').read_text())
        self.assertTrue((dst / 'files' / 'bin' / 'notes.txt').is_symlink())
        self.assertEqual(os.readlink(dst / 'files' / 'lib'), str(src / 'files' / 'lib'))
        self.assertNotIn('require_tool_appid', (dst / 'toolmanifest.vdf').read_text())
        self.assertIn('"display_name" "GE-Test 10 (Box64)"', (dst / 'compatibilitytool.vdf').read_text())
        self.assertEqual([t['dir'] for t in core.tools(self.p)], ['GE-Test-10-box64'])
        self.assertEqual([x['name'] for x in core.protons(self.p)], ['GE-Test 10'])
        # The original Proton stays untouched.
        self.assertEqual((src / 'files' / 'bin' / 'wine').read_bytes(), fake_elf(core.X86_64))
        core.remove_tool(self.p, 'GE-Test-10-box64')
        self.assertFalse(dst.exists())
        self.assertTrue((src / 'proton').exists())

    def test_tool_goes_out_of_date_when_its_proton_changes(self):
        src = self.fake_proton('Proton 10.0', base='common')
        core.install_runtime(self.p, str(self.bundle))
        core.create_tool(self.p, 'Proton 10.0')
        self.assertFalse(core.tools(self.p)[0]['outdated'])
        # A Steam update in place: a new proton script, then a new program in bin/.
        (src / 'proton').write_text(FAKE_PROTON + '# updated\n')
        self.assertTrue(core.tools(self.p)[0]['outdated'])
        core.create_tool(self.p, 'Proton 10.0')
        self.assertFalse(core.tools(self.p)[0]['outdated'])
        (src / 'files' / 'bin' / 'wine-preloader').write_bytes(fake_elf(core.X86_64))
        self.assertTrue(core.tools(self.p)[0]['outdated'])
        core.create_tool(self.p, 'Proton 10.0')
        tool = Path(self.p['tools']) / 'Proton-10.0-box64'
        self.assertIn(self.p['box64'], (tool / 'files' / 'bin' / 'wine-preloader').read_text())
        self.assertFalse(core.tools(self.p)[0]['outdated'])

    def test_rebuild_keeps_the_name_of_an_older_tool(self):
        src = self.fake_proton('GE-Proton10-34')
        old = Path(self.p['tools']) / 'GE-Proton10-34-box64-wow64'
        old.mkdir()
        (old / core.MARKER).write_text(f'Created by armada-box64 from {src}\n')
        (old / 'compatibilitytool.vdf').write_text('"display_name" "GE-Proton10-34 (Box64 WoW64)"\n')
        core.install_runtime(self.p, str(self.bundle))
        self.assertTrue(core.tools(self.p)[0]['outdated'])
        made = core.create_tool(self.p, 'GE-Proton10-34')
        self.assertFalse(core.tools(self.p)[0]['outdated'])
        self.assertEqual(made, {'dir': 'GE-Proton10-34-box64-wow64', 'name': 'GE-Proton10-34 (Box64 WoW64)'})
        self.assertFalse((Path(self.p['tools']) / 'GE-Proton10-34-box64').exists())

    def test_waits_for_a_running_game(self):
        self.fake_proton('GE-Test')
        core.install_runtime(self.p, str(self.bundle))
        # A process started like Box64 starts a wineserver: an interpreter with the program as argument.
        script = self.home / 'wineserver'
        script.write_text('sleep 30\n')
        fake = subprocess.Popen(['sh', str(script)], start_new_session=True)
        self.addCleanup(fake.wait)
        self.addCleanup(os.killpg, fake.pid, 9)
        time.sleep(0.2)
        with self.assertRaisesRegex(core.Box64Error, 'still running'):
            core.create_tool(self.p, 'GE-Test')

    def test_refuses_foreign_folders(self):
        self.fake_proton('Mine')
        core.install_runtime(self.p, str(self.bundle))
        foreign = Path(self.p['tools']) / 'Mine-box64'
        foreign.mkdir()
        with self.assertRaises(core.Box64Error):
            core.create_tool(self.p, 'Mine')
        for bad in ('Mine', '../x', '..', 'Mine-box64'):
            with self.assertRaises(core.Box64Error):
                core.remove_tool(self.p, bad)
        self.assertTrue(foreign.is_dir())

    def test_settings_reach_the_game_in_order(self):
        self.fake_proton('GE-Test')
        core.install_runtime(self.p, str(self.bundle))
        core.create_tool(self.p, 'GE-Test')
        # Defaults: NTSync off, WoW64 on, no Box64 code cache.
        run = self.launch('GE-Test-box64')
        env = run['env']
        self.assertTrue(run['argv0'].endswith('/GE-Test-box64/proton.py'))
        self.assertEqual((env['PROTON_NO_NTSYNC'], env['PROTON_USE_WOW64'], env['BOX64_DYNACACHE']), ('1', '1', '0'))
        self.assertNotIn('HODLL', env)
        self.assertNotIn('BOX64_DYNAREC_SAFEFLAGS', env)
        # Global preset, a per-game override, and a launch option that beats both.
        core.set_global(self.p, 'preset', 'performance')
        core.set_game(self.p, '123', 'safeflags', '2')
        core.set_game(self.p, '123', 'ntsync', True)
        env = self.launch('GE-Test-box64', BOX64_DYNAREC_BIGBLOCK='0')['env']
        self.assertEqual(env['PROTON_NO_NTSYNC'], '0')
        self.assertEqual(env['BOX64_DYNAREC_SAFEFLAGS'], '2')
        self.assertEqual(env['BOX64_DYNAREC_FORWARD'], '512')
        self.assertEqual(env['BOX64_MMAP32'], '1')
        self.assertEqual(env['BOX64_DYNAREC_BIGBLOCK'], '0')
        # Another game only gets the global settings.
        env = self.launch('GE-Test-box64', game='456')['env']
        self.assertEqual((env['PROTON_NO_NTSYNC'], env['BOX64_DYNAREC_SAFEFLAGS']), ('1', '1'))
        # Back to the defaults for game 123.
        core.set_game(self.p, '123', 'ntsync', None)
        self.assertEqual(core.load_settings(self.p)['games'], {'123': {'safeflags': '2'}})
        core.reset_game(self.p, '123')
        self.assertFalse(Path(self.p['games'], '123.env').exists())
        self.assertEqual(core.recent_games(self.p), ['456', '123'])
        self.assertEqual(core.last_tool(self.p, '123'), 'GE-Test-box64')

    def test_settings_reject_bad_input(self):
        core.set_global(self.p, 'preset', 'nonsense')
        core.set_global(self.p, 'ntsync', 'yes')
        self.assertEqual(core.load_settings(self.p)['global'], core.DEFAULTS)
        with self.assertRaises(core.Box64Error):
            core.set_game(self.p, '../1', 'ntsync', True)
        Path(self.p['settings']).write_text('{"games": {"x/../1": {"ntsync": true}}, "global": [1]}')
        self.assertEqual(core.load_settings(self.p), {'global': core.DEFAULTS, 'games': {}})

    def test_components_install_through_the_games_tool(self):
        self.fake_proton('GE-Test', ge=True)
        self.fake_proton('Proton 9.0', base='common')
        core.install_runtime(self.p, str(self.bundle))
        core.create_tool(self.p, 'GE-Test')
        core.create_tool(self.p, 'Proton 9.0')
        self.assertEqual({t['dir']: t['components'] for t in core.tools(self.p)},
                         {'GE-Test-box64': True, 'Proton-9.0-box64': False})
        with self.assertRaisesRegex(core.Box64Error, 'prefix'):
            core.components_command(self.p, '123', ['d3dx9'])
        (Path(self.p['compat']) / '123' / 'pfx').mkdir(parents=True)
        with self.assertRaisesRegex(core.Box64Error, 'Box64 tool first'):
            core.components_command(self.p, '123', ['d3dx9'])
        self.launch('Proton-9.0-box64')
        with self.assertRaisesRegex(core.Box64Error, 'GE-Proton'):
            core.components_command(self.p, '123', ['d3dx9'])
        self.launch('GE-Test-box64')
        for bad in ([], ['d3dx9', 'rm -rf'], ['vlc']):
            with self.assertRaisesRegex(core.Box64Error, 'Unknown component'):
                core.components_command(self.p, '123', bad)
        with self.assertRaises(core.Box64Error):
            core.components_command(self.p, '123', ['d3dx9'], tool='../GE-Test-box64')
        argv, env = core.components_command(self.p, '123', ['d3dx9', 'xact', 'd3dx9'])
        winetricks = os.path.join(self.p['helpers'], 'winetricks')
        self.assertEqual(argv, [f"{self.p['tools']}/GE-Test-box64/proton", 'waitforexitandrun', winetricks,
                                '--unattended', 'd3dx9', 'xact'])
        self.assertEqual((env['UMU_ID'], env['EXE'], env['PROTON_VERB']), ('armada-box64', winetricks, 'waitforexitandrun'))
        self.assertEqual(env['STEAM_COMPAT_DATA_PATH'], f"{self.p['compat']}/123")
        info = core.game_info(self.p, '123')
        self.assertEqual(info, {'prefix': True, 'tool': 'GE-Test (Box64)', 'components_ok': True, 'installed': []})
        # The install runs the tool's proton script, which hands the verbs to winetricks.
        self.assertEqual(core.install_components(self.p, '123', ['xact', 'd3dx9']), ['d3dx9', 'xact'])
        with self.assertRaisesRegex(core.Box64Error, 'did not install: corefonts'):
            core.install_components(self.p, '123', ['vcrun2005', 'corefonts'])
        # An install is not a launch: the game keeps its tool.
        self.assertEqual(core.last_tool(self.p, '123'), 'GE-Test-box64')
        self.assertEqual(core.game_info(self.p, '123')['installed'], ['d3dx9', 'xact', 'vcrun2005'])

    def test_cleanprefix_moves_arm64_leftovers(self):
        pfx = Path(self.p['compat']) / '123' / 'pfx'
        sys32 = pfx / 'drive_c/windows/system32'
        sys32.mkdir(parents=True)
        pe = bytearray(512)
        pe[0:2] = b'MZ'
        pe[0x3c:0x40] = (0x80).to_bytes(4, 'little')
        pe[0x80:0x84] = b'PE\0\0'
        pe[0x84:0x86] = (0xaa64).to_bytes(2, 'little')
        (sys32 / 'wowbox64.dll').write_bytes(bytes(pe))
        pe[0x84:0x86] = (0x8664).to_bytes(2, 'little')
        (sys32 / 'ntdll.dll').write_bytes(bytes(pe))
        (pfx / 'system.reg').write_text('[Software\\\\Microsoft\\\\Wow64\\\\x86] 1\n@="libwow64fex.dll"\n\n'
                                        '[Software\\\\Wine] 1\n"Keep"="1"\n')
        result = core.cleanprefix(self.p, '123')
        self.assertIn('Moved system32/wowbox64.dll (ARM64)', result['report'])
        self.assertEqual(result['moved'], 2)
        self.assertTrue((sys32 / 'ntdll.dll').exists())
        self.assertFalse((sys32 / 'wowbox64.dll').exists())
        reg = (pfx / 'system.reg').read_text()
        self.assertNotIn('Wow64', reg)
        self.assertIn('"Keep"="1"', reg)
        self.assertEqual(len(list(pfx.glob('arm64-leftovers-*/system32/wowbox64.dll'))), 1)
        with self.assertRaises(core.Box64Error):
            core.cleanprefix(self.p, '999')


if __name__ == '__main__':
    unittest.main()
