import os
import sys
import unittest
from pathlib import Path
import logging
import asyncio

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))


# logging.basicConfig(level=logging.DEBUG)
logging.getLogger().disabled = True

from backend.cookies.appbound.appbound import kill_running_arg, get_cookies  # noqa: E402
from backend.cookies.appbound.profile import get_browser_executable, get_browser_profile, ChromiumBrowsers  # noqa: E402


class TestAppbound(unittest.IsolatedAsyncioTestCase):
    _BROWSER_NAME: ChromiumBrowsers
    executable: str
    browser_profile: str

    @classmethod
    def setUpClass(cls):
        if not hasattr(cls, '_BROWSER_NAME'):
            raise unittest.SkipTest(f'{cls.__name__}: browser name not specified')
        if not (executable := get_browser_executable(cls._BROWSER_NAME)):
            raise unittest.SkipTest(f'{cls.__name__}: {cls._BROWSER_NAME} not installed')
        if not (browser_profile := get_browser_profile(cls._BROWSER_NAME)):
            raise unittest.SkipTest(f'{cls.__name__}: can\'t find cookies file: {cls._BROWSER_NAME}')
        cls.executable = executable
        cls.browser_profile = browser_profile

    def start_process(self, extra_arg=''):
        os.system(f'start "" /B "{self.executable}" {extra_arg}')

    def assert_running_arg(self, expected: str | None):
        running_arg = kill_running_arg(self.executable)
        if expected is None:
            self.assertIsNone(running_arg)
        else:
            self.assertIsNotNone(running_arg)
            assert running_arg is not None
            self.assertEqual(running_arg.strip(), expected)

    async def test_kill_process_arg(self):
        await asyncio.sleep(10)
        kill_running_arg(self.executable)
        self.start_process(extra_arg='--test-running-arg')
        await asyncio.sleep(10)
        self.assert_running_arg('--test-running-arg')

    async def test_load_with_killed(self):
        await asyncio.sleep(10)
        kill_running_arg(self.executable)
        self.assert_running_arg(None)
        cookies = await get_cookies(self.executable, self.browser_profile)
        self.assertTrue(cookies)
        await asyncio.sleep(10)
        self.assert_running_arg(None)

    async def test_load_with_running(self):
        await asyncio.sleep(10)
        kill_running_arg(self.executable)
        self.start_process(extra_arg='--test-running-arg')
        await asyncio.sleep(10)
        cookies = await get_cookies(self.executable, self.browser_profile)
        self.assertTrue(cookies)
        await asyncio.sleep(10)
        self.assert_running_arg('--test-running-arg --restore-last-session')


class TestChrome(TestAppbound):
    _BROWSER_NAME = 'chrome'


class TestEdge(TestAppbound):
    _BROWSER_NAME = 'edge'


class TestBrave(TestAppbound):
    _BROWSER_NAME = 'brave'


class TestChromium(TestAppbound):
    _BROWSER_NAME = 'chromium'


if __name__ == '__main__':
    unittest.main()
