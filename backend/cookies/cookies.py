from __future__ import annotations
import typing
import logging
import collections
import dataclasses
import asyncio
import os
import base64
import http.cookies
import time

import rookiepy
import aiohttp.web

from ..config import DataConfig
from .cookie_cloud import CookieCloudClient, CookieCloudServer
from .loaders import _LOADERS, NoCookieError, ValidationFailError
from .browsers import BrowserNotAvailableError, get_browser, set_browser, browser_names, appbound_browser_names


logger = logging.getLogger('cookies')


@dataclasses.dataclass
class CookieResult:
    uid: str | None
    browser: str | None
    cookies: http.cookies.SimpleCookie | None
    message: str


@dataclasses.dataclass
class AutoloadConfig(DataConfig):
    browser: str | None = None
    uid: str | None = None
    auto_reload: bool = False
    auto_reload_interval_minutes: int = 240
    try_appbound_debugger_workaround: bool = False

    @property
    def on(self):
        return bool(self.browser)

    @property
    def expect_uid(self):
        return bool(self.uid)

    @property
    def reload_interval(self):
        return self.auto_reload_interval_minutes * 60


@dataclasses.dataclass
class CookieConfig(DataConfig):
    cookie_cloud_salt: str = ''


class CookieManager:
    _LOADERS = collections.OrderedDict(((loader._key(), loader) for loader in _LOADERS))

    def __init__(self, server: Server):
        self._server = server
        self._config = CookieConfig.create_sub(server.config, 'cookies')
        self._sub_configs = {  # use this instead of _config.sub_configs for type inference
            loader_key: AutoloadConfig.create_sub(self._config, loader_key)
            for loader_key in self.site_loaders
        }
        self._cookie_result: dict[str, CookieResult] = {}
        self._auto_reload_task: asyncio.Task | None = None
        self._last_load_time: dict[str, float] = {}

    async def init(self):
        if len(self._config.cookie_cloud_salt) < 32:
            self._config.cookie_cloud_salt = base64.b64encode(os.urandom(24)).decode()
        self._cookie_cloud_server = CookieCloudServer(self._config.cookie_cloud_salt, self.on_cookie_cloud_update)
        await self._load_auto_entries(due_now=True)
        self._auto_reload_task = asyncio.create_task(self._auto_reload_worker())

    async def close(self):
        if self._auto_reload_task:
            self._auto_reload_task.cancel()

    async def _revalidate_cookies(self, loader_key: str, update_expired: bool = True):
        self._last_load_time[loader_key] = time.time()
        try:
            _ = await self.site_loaders[loader_key].validate(self.get_cookies(loader_key))
            logger.debug(f'[{loader_key}] cookies检查有效')
        except ValidationFailError as e:
            logger.debug(f'[{loader_key}] cookies检查失效: {e}')
            if update_expired:
                self._cookie_result[loader_key] = CookieResult(None, None, None, 'Cookie已过期')
        except Exception:
            # We shouldn't have NoCookieError for validated cookies
            # Not to write result for unknown error here
            logger.exception(f'[{loader_key}] 重新检查cookies时出错')

    def _since_last_load(self, loader_key: str) -> float:
        return time.time() - self._last_load_time.get(loader_key, 0)

    async def _load_auto_entries(self, browser_name: str | None = None, due_now: bool = False):
        for loader_key, sub_config in self._sub_configs.items():
            if not sub_config.on or (browser_name and sub_config.browser != browser_name):
                continue

            if not due_now:
                if not sub_config.auto_reload or self._since_last_load(loader_key) < sub_config.reload_interval:
                    continue

            logger.debug(f'[{loader_key}] 准备自动加载cookies')
            if self.status['success'].get(loader_key):
                await self._revalidate_cookies(loader_key, update_expired=True)

            if not self.status['success'].get(loader_key):
                # try only when expired or not successfully loaded
                await self.load(loader_key, sub_config.browser, sub_config.uid)

    async def _auto_reload_worker(self):
        while True:
            await asyncio.sleep(20)
            await self._load_auto_entries(due_now=False)

    def get_cookies(self, loader_key: str) -> http.cookies.SimpleCookie:
        assert loader_key in self.site_loaders, f'loader_key must be one of {list(self.site_loaders)}, got {loader_key}'
        return getattr(self._cookie_result.get(loader_key), 'cookies', None) or http.cookies.SimpleCookie()

    def on_cookie_cloud_update(self):
        if '本地CookieCloud' not in browser_names():
            logger.info('收到CookieCloud数据，将其添加为cookie源')
            set_browser('本地CookieCloud', self._cookie_cloud_server)
            asyncio.create_task(self._load_auto_entries(browser_name='本地CookieCloud', due_now=True))

    @property
    def status(self):
        return {
            'autoload': {loader_key: sub_config.as_dict()
                         for loader_key, sub_config in self._sub_configs.items()},
            'site_loaders': {key: loader._NAME for key, loader in self.site_loaders.items()},
            'results': {key: value.message for key, value in self._cookie_result.items()},
            'success': {key: value.cookies is not None for key, value in self._cookie_result.items()},
            'browsers': browser_names(),
            'appbound': appbound_browser_names(),
            'cookie_cloud_config': {
                'uuid': self._cookie_cloud_server.uuid,
                'password': self._cookie_cloud_server.password,
            },
        }

    @property
    def site_loaders(self):
        return self._LOADERS

    def configure_autoload(self, loader_key: str, on: bool, expect_uid: bool):
        sub_config = self._sub_configs[loader_key]
        if on:
            if cookie_result := self._cookie_result.get(loader_key):
                if cookie_result.cookies:
                    sub_config.browser = cookie_result.browser
                    if expect_uid:
                        sub_config.uid = cookie_result.uid
            if not expect_uid:
                sub_config.uid = None
        else:
            sub_config.browser = None
            sub_config.uid = None

    async def reset(self, loader_key: str):
        self._cookie_result.pop(loader_key, None)
        sub_config = self._sub_configs[loader_key]
        sub_config.browser = None
        sub_config.uid = None

    async def load(self, loader_key, browser_name, expect_uid=None) -> CookieResult:
        self._last_load_time[loader_key] = time.time()
        result = await self._load(loader_key, browser_name, expect_uid)
        logger.debug(f'[{loader_key}] 从 {browser_name} 加载了{len(result.cookies or {})}条有效cookies')
        if result.cookies and self._sub_configs[loader_key].on:
            self.configure_autoload(loader_key, True, self._sub_configs[loader_key].expect_uid)
        return result

    async def _load(self, loader_key, browser_name, expect_uid=None) -> CookieResult:
        def _update_success(uid: str, username: str, cookies: http.cookies.SimpleCookie):
            self._cookie_result[loader_key] = CookieResult(
                uid, browser_name, cookies, f'获取用户：{username} ({uid})')

        def _update_failed(message: str):
            self._cookie_result[loader_key] = CookieResult(None, None, None, message)

        if loader_key not in self.site_loaders:
            return CookieResult(None, None, None, f'{loader_key} is not a valid loader key')
        try:
            browser = get_browser(browser_name, self._sub_configs[loader_key].try_appbound_debugger_workaround)
            uid, username, cookies = await self.site_loaders[loader_key].load(browser)
            if expect_uid and str(uid) != str(expect_uid):
                logger.debug(f'[{loader_key}] uid不符, 处理为加载失败')
                _update_failed(f'uid={uid}与预设({expect_uid})不符')
            else:
                logger.debug(f'[{loader_key}] 共加载{len(cookies or {})}条cookies')
                _update_success(uid, username, cookies)
        except NoCookieError:
            logger.debug(f'[{loader_key}] {browser_name} 无可用cookie')
            _update_failed('无可用cookie')
        except ValidationFailError as e:
            logger.debug(f'[{loader_key}] {browser_name} cookies检查无效: {e}')
            _update_failed('Cookie已过期')
        except BrowserNotAvailableError as e:
            logger.debug(f'[{loader_key}] 浏览器不可用: {e}')
            _update_failed(f'浏览器不可用: {e}')
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if "can't find cookies file" in str(e):
                _update_failed('找不到浏览器cookie文件')
            elif 'Chrome cookies from version v130 ' in str(e):
                _update_failed('无法读取130+版本Chromium内核的浏览器（可尝试开启实验方式）')
            else:
                logger.exception(f'[{loader_key}] 读取cookies时出错')
                _update_failed(f'读取Cookie时出错: {e}')
        return self._cookie_result[loader_key]

    async def cookie_handler(self, request: aiohttp.web.Request):
        if request.method == 'POST':
            data = await request.json()
            for key, value in data.get('load', {}).items():
                if key not in self.site_loaders:
                    return aiohttp.web.json_response({'error': f'{key} is not a valid loader key'}, status=400)
                if value:
                    result = await self.load(key, value)
                    if key == 'Bilibili' and result.cookies:
                        await self._server.reset_danmaku_connections()
                else:
                    await self.reset(key)
            for key, value in data.get('autoload', {}).items():
                self.configure_autoload(key, value.get('on', False), value.get('expect_uid', False))
            for key, value in data.get('autoreload', {}).items():
                sub_config = self._sub_configs[key]
                sub_config.auto_reload = value.get('auto_reload', sub_config.auto_reload)
                sub_config.auto_reload_interval_minutes = value.get(
                    'auto_reload_interval_minutes', sub_config.auto_reload_interval_minutes)
                sub_config.try_appbound_debugger_workaround = value.get(
                    'try_appbound_debugger_workaround', sub_config.try_appbound_debugger_workaround)
            if value := data.get('cookie_cloud_url'):
                set_browser('cookie_cloud', CookieCloudClient(value))
                logger.info('CookieCloud client loader configured')
                asyncio.create_task(self._load_auto_entries(browser_name='cookie_cloud', due_now=True))
        return aiohttp.web.json_response(self.status)

    async def handle_cookie_cloud_update(self, request: aiohttp.web.Request):
        return await self._cookie_cloud_server.handle_update_request(request)


if typing.TYPE_CHECKING:
    from ..main import Server

    class Browser(typing.Protocol):
        def __call__(self, domains: typing.Optional[typing.List[str]] = None) -> rookiepy.CookieList:
            ...
