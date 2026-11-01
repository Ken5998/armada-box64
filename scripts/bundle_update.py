#!/usr/bin/env python3
"""Puts upstream's newest Box64 version into the plugin when it is not there yet.

  git ls-remote --tags https://github.com/ptitSeb/box64 | python3 scripts/bundle_update.py

Rewrites box64-versions (the newest tag first, a re-tag such as v0.4.5-2 replaces v0.4.5-1, the
list keeps its length by dropping its oldest tag) and bumps the patch version in package.json.
Prints the new tag and plugin version ("v0.4.6 0.2.6"), or nothing when the plugin is current.
Dropped tags stay downloadable from their box64-<tag> releases.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import box64_plan  # noqa: E402

VERSION = re.compile(r'("version"\s*:\s*")([0-9]+)\.([0-9]+)\.([0-9]+)(")')


def updated_list(upstream, shipped):
    """The new box64-versions list, or None when upstream's newest version is already shipped."""
    newest = box64_plan.newest(upstream, 1)
    if not newest or newest[0] in shipped:
        return None
    tag = newest[0]
    base = box64_plan.key(tag)[:3]
    rest = [t for t in shipped if not (box64_plan.TAG.fullmatch(t) and box64_plan.key(t)[:3] == base)]
    keep = max(len(shipped), 1)
    if rest and box64_plan.TAG.fullmatch(rest[0]) and box64_plan.key(rest[0]) > box64_plan.key(tag):
        return None  # The plugin already ships something newer than upstream's newest release.
    return [tag] + rest[:keep - 1]


def bump_patch(package_json):
    """package.json text with the patch version raised by one, and the new version."""
    m = VERSION.search(package_json)
    if not m:
        raise ValueError('No version in package.json')
    version = f'{m.group(2)}.{m.group(3)}.{int(m.group(4)) + 1}'
    return package_json[:m.start()] + m.group(1) + version + m.group(5) + package_json[m.end():], version


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    versions_file = os.path.join(root, 'box64-versions')
    package_file = os.path.join(root, 'package.json')
    with open(versions_file) as f:
        shipped = f.read().split()
    new = updated_list(box64_plan.read_tags(sys.stdin), shipped)
    if new is None:
        return
    with open(package_file) as f:
        text, version = bump_patch(f.read())
    with open(versions_file, 'w') as f:
        f.write('\n'.join(new) + '\n')
    with open(package_file, 'w') as f:
        f.write(text)
    print(new[0], version)


if __name__ == '__main__':
    main()
