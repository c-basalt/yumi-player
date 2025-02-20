from __future__ import annotations
import typing
import logging

from .profile import get_browser_profile, get_browser_executable
from .appbound import get_cookies
from ..utils import filter_cookies_by_domains, run_as_sync

from rookiepy import (
    chrome as chrome_rookie,
    edge as edge_rookie,
    brave as brave_rookie,
    chromium as chromium_rookie
)

logger = logging.getLogger('cookies.appbound')


def run_browser(rookie_browser: Browser, browser_name: ChromiumBrowsers, domains: list[str] | None = None):
    try:
        return rookie_browser(domains)
    except Exception as e:
        if 'Chrome cookies from version v130 ' not in str(e):
            logger.info(f'appbound cookies读取失败, 使用远程调试方案: {browser_name}')
            raise  # only fallback for v130+ appbound

    if not (browser_path := get_browser_executable(browser_name)):
        raise RuntimeError(f"can't find browser executable: {browser_name}")
    if not (browser_profile := get_browser_profile(browser_name)):
        raise RuntimeError(f"can't find cookies file: {browser_name}")
    cookies = run_as_sync(get_cookies(browser_path, browser_profile))
    return filter_cookies_by_domains(cookies, domains)


def edge_appbound(domains: list[str] | None = None):
    return run_browser(edge_rookie, 'edge', domains)


def chrome_appbound(domains: list[str] | None = None):
    return run_browser(chrome_rookie, 'chrome', domains)


def brave_appbound(domains: list[str] | None = None):
    return run_browser(brave_rookie, 'brave', domains)


def chromium_appbound(domains: list[str] | None = None):
    return run_browser(chromium_rookie, 'chromium', domains)


if typing.TYPE_CHECKING:
    from ..cookies import Browser
    from .profile import ChromiumBrowsers
