#!/usr/bin/env python3
import os
import sys


CHANGELOG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'Changelog.md')
)


def extract_changelog_version(version):
    start_tag = f'### {version}'
    collecting = False
    desc_lines = []

    with open(CHANGELOG_PATH, encoding='utf-8') as f:
        for line in f:
            if line.startswith('### '):
                if line.strip() == start_tag:
                    collecting = True
                    continue
                elif collecting:
                    # hit next version header → stop
                    break
            if collecting:
                desc_lines.append(line.rstrip())

    return '\n'.join(desc_lines).strip('\n')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(sys.argv[0], '<version>')
        exit(1)
    print(extract_changelog_version(sys.argv[1]))
