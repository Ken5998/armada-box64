"""Checks of the weekly Box64 build plan."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import box64_plan  # noqa: E402
import bundle_update  # noqa: E402

UPSTREAM = {'v0.3.8', 'v0.4.0', 'v0.4.1-1', 'v0.4.1-3', 'v0.4.3-3', 'v0.4.3-4', 'v0.4.4', 'v0.4.5-1', 'v0.4.10',
            'latest', 'v0.4.6-rc1'}


class PlanTests(unittest.TestCase):
    def test_newest_versions_one_tag_each(self):
        self.assertEqual(box64_plan.newest(UPSTREAM, 4), ['v0.4.10', 'v0.4.5-1', 'v0.4.4', 'v0.4.3-4'])

    def test_builds_only_what_has_no_release(self):
        published = {'box64-v0.4.10', 'box64-v0.4.4', 'v0.2.0'}
        self.assertEqual(box64_plan.plan(UPSTREAM, 4, published, ['v0.4.5-1', 'v0.4.3-3', 'v9']),
                         ['v0.4.5-1', 'v0.4.3-4', 'v0.4.3-3'])


class BundleTests(unittest.TestCase):
    SHIPPED = ['v0.4.5-1', 'v0.4.4', 'v0.4.3-3']

    def test_nothing_when_newest_is_shipped(self):
        self.assertIsNone(bundle_update.updated_list(UPSTREAM - {'v0.4.10'}, self.SHIPPED))

    def test_new_version_goes_first_and_oldest_drops(self):
        self.assertEqual(bundle_update.updated_list(UPSTREAM, self.SHIPPED), ['v0.4.10', 'v0.4.5-1', 'v0.4.4'])

    def test_retag_replaces_its_version(self):
        upstream = (UPSTREAM - {'v0.4.10'}) | {'v0.4.5-2'}
        self.assertEqual(bundle_update.updated_list(upstream, self.SHIPPED), ['v0.4.5-2', 'v0.4.4', 'v0.4.3-3'])

    def test_never_goes_back(self):
        self.assertIsNone(bundle_update.updated_list({'v0.4.4'}, self.SHIPPED))

    def test_bump_patch_keeps_the_rest(self):
        text = '{\n  "name": "x",\n  "version": "0.2.9",\n  "dev": "1.2.3"\n}\n'
        new, version = bundle_update.bump_patch(text)
        self.assertEqual(version, '0.2.10')
        self.assertEqual(new, text.replace('0.2.9', '0.2.10'))

    def test_ls_remote_parsing(self):
        lines = ['abc\trefs/tags/v0.4.4\n', 'def\trefs/tags/v0.4.4^{}\n', 'ghi\tHEAD\n']
        self.assertEqual(box64_plan.read_tags(lines), {'v0.4.4'})


if __name__ == '__main__':
    unittest.main()
