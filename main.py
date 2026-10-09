import asyncio
import json
import os
import time

import decky

import armadabox64 as core


def _paths():
    return core.paths(decky.DECKY_USER_HOME)


def _bundle():
    return os.path.join(decky.DECKY_PLUGIN_DIR, 'bin')


def _plugin_version():
    with open(os.path.join(decky.DECKY_PLUGIN_DIR, 'package.json')) as f:
        return json.load(f)['version']


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


_tasks = set()


async def _install(job, p, game, verbs, log):
    """Runs a Windows component install to the end and records the outcome in its job."""
    def work():
        with open(log, 'w') as f:
            return core.install_components(p, game, verbs, log=f)
    reply = await _run(work)
    job['state'] = 'done' if reply['ok'] else 'failed'
    job['message'] = '' if reply['ok'] else reply['error']


class Plugin:
    # Windows component installs, one per game: {'state': running|done|failed, 'verbs', 'message', 'log'}.
    jobs = {}

    async def get_state(self):
        return await _run(core.state, _paths(), _bundle())

    async def install_runtime(self):
        return await _run(core.install_runtime, _paths(), _bundle())

    async def get_catalog(self, refresh: bool = False):
        """Box64 versions to download and a newer plugin release; needs internet."""
        def work():
            result = core.catalog(_paths(), refresh, current=_plugin_version())
            result['current'] = _plugin_version()
            return result
        return await _run(work)

    async def download_version(self, tag: str):
        return await _run(core.download_version, _paths(), tag)

    async def remove_version(self, tag: str):
        return await _run(core.remove_version, _paths(), tag)

    async def download_plugin(self):
        """Fetches the newer plugin ZIP; the frontend then hands it to Decky's installer."""
        return await _run(core.download_plugin, _paths(), _plugin_version())

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

    async def get_game(self, game: str):
        reply = await _run(core.game_info, _paths(), game)
        if reply['ok']:
            reply['result']['job'] = self.jobs.get(str(game))
        return reply

    async def install_components(self, game: str, verbs: list):
        game = str(game)
        if (self.jobs.get(game) or {}).get('state') == 'running':
            return {'ok': False, 'error': 'An install is already running for this game.'}
        # Checks the request now, so mistakes show up at once rather than at the end.
        for check in (await _run(core.components_command, _paths(), game, verbs), await _run(core.require_no_wine)):
            if not check['ok']:
                return check
        p = _paths()
        os.makedirs(p['logs'], exist_ok=True)
        log = os.path.join(p['logs'], f'components-{game}-{time.strftime("%Y%m%d-%H%M%S")}.log')
        self.jobs[game] = {'state': 'running', 'verbs': verbs, 'message': '', 'log': log}
        task = asyncio.get_running_loop().create_task(_install(self.jobs[game], p, game, verbs, log))
        # The loop keeps only a weak reference to a task.
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return {'ok': True, 'result': self.jobs[game]}

    async def _main(self):
        decky.logger.info('Armada Box64 loaded')

    async def _unload(self):
        pass

    async def _uninstall(self):
        # The tools, Box64 and settings stay: games may still use them. The README says how to remove them.
        pass
