from __future__ import annotations
import os
import logging
import typing

import rookiepy

from .cookie_cloud import CookieCloudClient
from .appbound import chrome_appbound, edge_appbound, brave_appbound, chromium_appbound

logger = logging.getLogger('cookies.browsers')


class BrowserNotAvailableError(ValueError):
    pass


rookie_browsers = [
    'firefox',
    'chrome',
    'edge',
    'safari',
    'chromium',
    'brave',
    'opera',
    'vivaldi',
    'arc',
]
browsers: dict[str, Browser] = {name: getattr(rookiepy, name) for name in rookie_browsers if hasattr(rookiepy, name)}
if os.environ.get('COOKIE_CLOUD_URL'):
    try:
        browsers['cookie_cloud'] = CookieCloudClient(os.environ['COOKIE_CLOUD_URL'])
    except Exception:
        logger.exception('Failed to setup CookieCloud client loader')

app_bound_alt = {
    'chrome': chrome_appbound,
    'edge': edge_appbound,
    'chromium': chromium_appbound,
    'brave': brave_appbound,
}


def get_browser(browser_name: str, app_bound: bool = False) -> Browser:
    try:
        if app_bound:
            return app_bound_alt.get(browser_name, browsers[browser_name])
        return browsers[browser_name]
    except KeyError:
        raise BrowserNotAvailableError(browser_name)


def set_browser(browser_name: str, browser: Browser):
    browsers[browser_name] = browser


def browser_names() -> list[str]:
    return list(browsers)


def appbound_browser_names() -> list[str]:
    return list(app_bound_alt)


if typing.TYPE_CHECKING:
    class Browser(typing.Protocol):
        def __call__(self, domains: typing.Optional[typing.List[str]] = None) -> rookiepy.CookieList:
            ...
