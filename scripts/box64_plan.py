#!/usr/bin/env python3
"""Picks the Box64 tags the weekly workflow should build and publish.

  git ls-remote --tags https://github.com/ptitSeb/box64 | python3 scripts/box64_plan.py COUNT PUBLISHED_TAGS_FILE

Reads upstream's tags on stdin and prints a JSON list of tags that have no box64-<tag> release
yet: the newest COUNT Box64 versions (for each version only its newest -N re-tag) plus the
versions the plugin ships (box64-versions).
"""
import json
import os
import re
import sys

TAG = re.compile(r'v([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9]+))?')


def key(tag):
    m = TAG.fullmatch(tag)
    return tuple(int(n or 0) for n in m.groups())


def newest(tags, count):
    """The newest `count` versions, one tag each: v0.4.3-4 stands for v0.4.3-1 to -4."""
    best = {}
    for tag in tags:
        if TAG.fullmatch(tag):
            base = key(tag)[:3]
            if base not in best or key(tag) > key(best[base]):
                best[base] = tag
    return [best[b] for b in sorted(best, reverse=True)[:count]]


def plan(upstream, count, published, shipped):
    wanted = newest(upstream, count) + [t for t in shipped if t in upstream]
    return [t for t in dict.fromkeys(wanted) if f'box64-{t}' not in published]


def main(argv):
    count = int(argv[0])
    with open(argv[1]) as f:
        published = set(f.read().split())
    upstream = set()
    for line in sys.stdin:
        ref = line.split()[-1] if line.strip() else ''
        if ref.startswith('refs/tags/') and not ref.endswith('^{}'):
            upstream.add(ref[len('refs/tags/'):])
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'box64-versions')) as f:
        shipped = f.read().split()
    print(json.dumps(plan(upstream, count, published, shipped)))


if __name__ == '__main__':
    main(sys.argv[1:])
