from __future__ import annotations
import asyncio
import http.cookies
import re
import time
import logging
import typing

from ..config import aiohttp_session


logger = logging.getLogger('cookies.loaders')
_UA = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
}
_LOADERS: list[typing.Type['CookieLoader']] = []


def register_loader(cls: T) -> T:
    _LOADERS.append(cls)
    return cls


class NoCookieError(ValueError):
    pass


class ValidationFailError(ValueError):
    pass


class CookieLoader:
    _NAME: str
    _DOMAIN: str

    @classmethod
    def _key(cls):
        suffix = 'CookieLoader'
        assert cls.__name__.endswith(suffix)
        return cls.__name__[:-len(suffix)]

    @classmethod
    async def _load(cls, browser: Browser) -> http.cookies.SimpleCookie:
        cookie_list = await asyncio.get_running_loop().run_in_executor(
            None, browser, [cls._DOMAIN])
        logger.debug(f'[{cls._key()}] 获取 {cls._DOMAIN} 下的{len(cookie_list)}条cookies')
        cookies = http.cookies.SimpleCookie()
        for cookie in cookie_list:
            cookies[cookie['name']] = cookie['value']
            cookies[cookie['name']]['domain'] = cookie['domain']
            cookies[cookie['name']]['path'] = cookie['path']
            cookies[cookie['name']]['httponly'] = cookie['http_only']
        return cookies

    @classmethod
    async def validate(cls, cookies: http.cookies.SimpleCookie) -> tuple[str, str]:
        raise NotImplementedError

    @classmethod
    async def load(cls, browser: Browser):
        cookies = await cls._load(browser)
        uid, username = await cls.validate(cookies)
        return uid, username, cookies


@register_loader
class BilibiliCookieLoader(CookieLoader):
    _NAME = 'Bilibili'
    _DOMAIN = '.bilibili.com'

    @classmethod
    async def validate(cls, cookies: http.cookies.SimpleCookie) -> tuple[str, str]:
        if not cookies.get('SESSDATA'):
            raise NoCookieError
        async with aiohttp_session() as session:
            async with session.get('https://api.bilibili.com/x/web-interface/nav',
                                   cookies=cookies,
                                   headers={'referer': 'https://t.bilibili.com/', **_UA}) as r:
                if r.status != 200:
                    raise ValidationFailError
                data = (await r.json())['data']
                if not data.get('mid'):
                    raise ValidationFailError
                return str(data['mid']), data['uname']


@register_loader
class QQMusicCookieLoader(CookieLoader):
    _NAME = 'QQ音乐'
    _DOMAIN = '.qq.com'

    @staticmethod
    def _get_g_tk(cookies: http.cookies.SimpleCookie):
        n = 5381
        for c in getattr(cookies.get('qqmusic_key'), 'value', ''):
            n += (n << 5) + ord(c)
        return n & 2147483647

    @classmethod
    async def validate(cls, cookies: http.cookies.SimpleCookie) -> tuple[str, str]:
        if not cookies.get('uin') or not cookies.get('fqm_pvqid'):
            raise NoCookieError
        url = 'https://c6.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg'
        params = {
            '_': int(time.time() * 1e3),
            'cv': 4747474,
            'ct': 24,
            'format': 'json',
            'platform': 'yqq.json',
            'uin': cookies['uin'].value,
            'g_tk_new_20200303': cls._get_g_tk(cookies),
            'g_tk': cls._get_g_tk(cookies),
            'cid': '205360838',
            'reqfrom': 1,
        }
        async with aiohttp_session() as session:
            async with session.get(url, params=params, cookies=cookies,
                                   headers={'referer': 'https://y.qq.com/', **_UA}) as r:
                if r.status != 200:
                    raise ValidationFailError(f'status code: {r.status}')
                data = (await r.json())['data']
                if not data.get('creator'):
                    raise ValidationFailError(f'missing user info: {data}')
                return str(cookies['uin'].value), str(data['creator']['nick'])


@register_loader
class NeteaseMusicCookieLoader(CookieLoader):
    _NAME = '网易云'
    _DOMAIN = '.163.com'

    @classmethod
    async def validate(cls, cookies: http.cookies.SimpleCookie) -> tuple[str, str]:
        if not cookies.get('MUSIC_U') or not cookies.get('__csrf'):
            raise NoCookieError(f"{cookies.get('MUSIC_U')} {cookies.get('__csrf')}")
        async with aiohttp_session() as session:
            async with session.get('https://music.163.com/', cookies=cookies,
                                   headers={**_UA}) as r:
                if r.status != 200:
                    raise ValidationFailError(f'status code: {r.status}')
                user_info = re.search(
                    r'var\s+GUser\s*=\s*{\s*userId\s*:\s*(\d+)\s*,\s*nickname\s*:"([^"]+)"',
                    (await r.text()))
                if not user_info:
                    raise ValidationFailError
                return user_info[1], user_info[2]


if typing.TYPE_CHECKING:
    from .browsers import Browser
    T = typing.TypeVar('T', bound=typing.Type['CookieLoader'])
