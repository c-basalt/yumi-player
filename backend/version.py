import subprocess
import sys
try:
    from .__version__ import __version__  # type: ignore
except ImportError:
    __version__ = None


def get_git_commit_hash():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip()


def get_git_commit_date():
    return subprocess.check_output(['git', 'log', '-1', '--format=%ad', '--date=short']).decode('utf-8').strip()


def get_git_tag():
    tag = subprocess.run(['git', 'describe', '--tags', '--abbrev=0'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()
    return tag + ' ' if tag else ''


def get_git_version():
    return f'{get_git_tag()}{get_git_commit_hash()[:7]} ({get_git_commit_date()})'


def get_version():
    if __version__:
        return __version__
    return get_git_version()


def get_environment():
    return {
        'bundled': getattr(sys, 'frozen', False),
        'has_version': __version__ is not None,
    }


if __name__ == '__main__':
    import os
    if '--write-version' in sys.argv:
        print('writing version to __version__.py:', get_git_version())
        with open(os.path.join(os.path.dirname(__file__), '__version__.py'), 'wt') as f:
            f.write(f"__version__ = '{get_git_version()}'")
    else:
        print(get_git_version())
