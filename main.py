import asyncio
import os

import decky

import armadabox64 as core


def _paths():
    return core.paths(decky.DECKY_USER_HOME)


def _bundle():
    return os.path.join(decky.DECKY_PLUGIN_DIR, 'bin', 'box64-armada')


async def _run(fn, *args):
    """Runs core work off the event loop and turns problems into a message for the UI."""
    try:
        result = await asyncio.to_thread(fn, *args)
        return {'ok': True, 'result': result}
    except core.Box64Error as e:
        return {'ok': False, 'error': str(e)}
    except Exception as e:  # noqa: BLE001 - anything else is logged and reported, never raised into Decky
        decky.logger.exception('Armada Box64 call failed')
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


class Plugin:
    async def get_state(self):
        return await _run(core.state, _paths(), _bundle())

    async def install_runtime(self):
        return await _run(core.install_runtime, _paths(), _bundle())

    async def create_tool(self, proton: str):
        return await _run(core.create_tool, _paths(), proton)

    async def remove_tool(self, tool_dir: str):
        return await _run(core.remove_tool, _paths(), tool_dir)

    async def set_global(self, key: str, value):
        return await _run(core.set_global, _paths(), key, value)

    async def set_game(self, game: str, key: str, value):
        return await _run(core.set_game, _paths(), game, key, value)

    async def reset_game(self, game: str):
        return await _run(core.reset_game, _paths(), game)

    async def clean_prefix(self, game: str):
        return await _run(core.cleanprefix, _paths(), game)

    async def _main(self):
        decky.logger.info('Armada Box64 loaded')

    async def _unload(self):
        pass

    async def _uninstall(self):
        # The tools, Box64 and settings stay: games may still use them. The README says how to remove them.
        pass
