"""Checks of the weekly Box64 build plan."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import box64_plan  # noqa: E402

UPSTREAM = {'v0.3.8', 'v0.4.0', 'v0.4.1-1', 'v0.4.1-3', 'v0.4.3-3', 'v0.4.3-4', 'v0.4.4', 'v0.4.5-1', 'v0.4.10',
            'latest', 'v0.4.6-rc1'}


class PlanTests(unittest.TestCase):
    def test_newest_versions_one_tag_each(self):
        self.assertEqual(box64_plan.newest(UPSTREAM, 4), ['v0.4.10', 'v0.4.5-1', 'v0.4.4', 'v0.4.3-4'])

    def test_builds_only_what_has_no_release(self):
        published = {'box64-v0.4.10', 'box64-v0.4.4', 'v0.2.0'}
        self.assertEqual(box64_plan.plan(UPSTREAM, 4, published, ['v0.4.5-1', 'v0.4.3-3', 'v9']),
                         ['v0.4.5-1', 'v0.4.3-4', 'v0.4.3-3'])


if __name__ == '__main__':
    unittest.main()
