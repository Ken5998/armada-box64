"""Checks of the Decky backend (main.py) with a stand-in for Decky's module."""
from pathlib import Path
import asyncio
import logging
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
decky = types.ModuleType('decky')
decky.logger = logging.getLogger('decky-test')
sys.modules['decky'] = decky
import main  # noqa: E402
import test_core  # noqa: E402
core = test_core.core


class MainTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        decky.DECKY_USER_HOME = str(self.home)
        decky.DECKY_PLUGIN_DIR = str(self.home / 'plugin')
        # The fake Proton, bundle and launch helpers of the core tests.
        self.helper = test_core.CoreTests()
        self.helper.home, self.helper.p = self.home, core.paths(str(self.home))
        self.helper.bundle = Path(decky.DECKY_PLUGIN_DIR) / 'bin'
        for tag in ('v0.4.5-1',):
            version = self.helper.bundle / 'box64' / tag
            version.mkdir(parents=True)
            (version / 'box64').write_text(f'#!/bin/sh\necho "Box64 {tag} test build"\n')
            (version / 'NOTICE.txt').write_text(f'Box64 {tag}\n')
        (self.helper.bundle / 'tools').mkdir()
        (self.helper.bundle / 'tools' / 'winetricks').write_text('#!/bin/sh\n')
        main.Plugin.jobs.clear()

    def call(self, method, *args):
        plugin = main.Plugin()
        return asyncio.run(getattr(plugin, method)(*args))

    def test_component_install_runs_in_the_background(self):
        self.helper.fake_proton('GE-Test', ge=True)
        self.assertTrue(self.call('install_runtime')['ok'])
        self.assertTrue(self.call('create_tool', 'GE-Test')['ok'])
        (Path(self.helper.p['compat']) / '123' / 'pfx').mkdir(parents=True)
        self.helper.launch('GE-Test-box64')
        state = self.call('get_state')['result']
        self.assertEqual(state['runtime']['installed'], ['v0.4.5-1'])
        self.assertIn('d3dx9', state['components'])
        self.assertFalse(self.call('install_components', '123', ['nonsense'])['ok'])

        async def install_and_wait():
            plugin = main.Plugin()
            started = await plugin.install_components('123', ['d3dx9'])
            self.assertEqual(started['result']['state'], 'running')
            again = await plugin.install_components('123', ['xact'])
            self.assertFalse(again['ok'])
            while main._tasks:
                await asyncio.sleep(0.05)
            return await plugin.get_game('123')

        info = asyncio.run(install_and_wait())['result']
        self.assertEqual(info['job']['state'], 'done', info['job'])
        self.assertEqual(info['installed'], ['d3dx9'])
        self.assertTrue(os.path.isfile(info['job']['log']))


if __name__ == '__main__':
    unittest.main()
