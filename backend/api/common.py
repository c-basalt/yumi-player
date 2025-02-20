from __future__ import annotations
import dataclasses
import abc
import re
import typing
import json
import http.cookies
import logging

from ..db import PlaylistInfo, PlaylistCacheEntry
from .cjk_normalize import cjk_norm

logger = logging.getLogger('api.common')


class NoPlayurlError(ValueError):
    pass


@dataclasses.dataclass
class SearchResult:
    id: str
    title: str
    singer: str
    meta: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class UserPlaylistResult:
    url: str
    title: str
    count: int | None


@dataclasses.dataclass
class ParsedPlaylistUrl:
    type: str
    cache_id: str
    extra: dict


@dataclasses.dataclass
class PlaylistResult:
    type: str
    cache_id: str
    extra: dict
    title: str
    song_ids: list[str]
    songs_meta: dict[str, dict]


@dataclasses.dataclass
class InfoResult:
    id: str
    url: str
    title: str
    singer: str | None
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    meta: dict = dataclasses.field(default_factory=dict)


T = typing.TypeVar('T')


class API(abc.ABC):
    _NAME: str  # human-readable name

    @staticmethod
    def _norm_domain(domain: str):
        return f'.{domain}' if not domain.startswith('.') else domain

    @property
    def key(self):
        return self.__class__.__name__[:-3]

    def __init__(self, request_func: ARequestFunc, cookies_getter: CookiesGetter):
        self._cookies_getter = cookies_getter
        self._request = request_func

    @property
    def cookies(self) -> http.cookies.SimpleCookie:
        if self._cookies_getter:
            return self._cookies_getter()
        return http.cookies.SimpleCookie()

    def _get_cookie(self, cookie_key: str, domain: str, default: T = None) -> str | T:
        if cookie := self.cookies.get(cookie_key):
            if self._norm_domain(cookie['domain']).endswith(self._norm_domain(domain)):
                return cookie.value
            else:
                logger.warning(f'cookie "{cookie_key}" domain mismatch, expected {domain}, got {cookie["domain"]}')
        return default

    def _get_cookie_dict(self, cookie_keys: list[str], domain: str) -> dict[str, str]:
        cookies = {key: self._get_cookie(key, domain) for key in cookie_keys}
        return {key: value for key, value in cookies.items() if value}

    async def _request_json(self, method: str, url: str, data: bytes | None = None, params: dict = {},
                            headers: dict = {}, cookies: Cookies | None = None, proxy: str | None = None):
        return json.loads((await self._request(
            method, url, data=data, params=params, headers=headers, cookies=(cookies or self.cookies), proxy=proxy)))

    @staticmethod
    def _check_full_match(query: str, title: str, columns: typing.Iterable[str]):
        """helper method to check if all keywords in query, separated by whitespace,
        are found in title or at least one of columns, and at least one keyword
        is found in title. Comparing as case-insensitive"""
        query = cjk_norm(query)
        columns_normed = [cjk_norm(title), *[cjk_norm(column) for column in columns]]
        title_matched_once = False

        def _check_keyword(keyword: str):
            nonlocal title_matched_once
            for (index, column) in enumerate(columns_normed):
                if re.match(r'[a-z]', keyword):
                    # for Eng-word keyword, test against partial-word match like "a" in "apple"
                    is_matched = bool(re.search(rf'(^|[^a-z]){keyword}([^a-z]|$)', column, flags=re.IGNORECASE))
                else:
                    # for non-Eng keyword, use simple substring test
                    is_matched = keyword in column

                if is_matched:
                    if index == 0:
                        title_matched_once = True
                    return True
            return False

        for keyword in query.strip().split():
            if keyword := keyword.strip():
                if not _check_keyword(keyword):
                    return False

        if not title_matched_once:
            return False

        return True

    @staticmethod
    def _strip_cover_text(title: str) -> str:
        """helper method to strip "cover" text from the end of song title"""
        return re.sub(r'[\(（]cover[^\(\)（）]+[\)）]$', '', title, flags=re.IGNORECASE).strip()

    @abc.abstractmethod
    async def search(self, query: str, limit=5) -> list[SearchResult]:
        raise NotImplementedError

    @abc.abstractmethod
    async def songinfo(self, song_id: str | SearchResult, proxy: str | None = None) -> InfoResult:
        raise NotImplementedError

    @abc.abstractmethod
    def _to_playlist_url(self, parsed: ParsedPlaylistUrl | PlaylistResult) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def _parse_playlist_url(self, url: str) -> ParsedPlaylistUrl | None:
        raise NotImplementedError

    async def _load_playlist_cache(self, parsed: ParsedPlaylistUrl) -> PlaylistInfo | None:
        return await PlaylistCacheEntry.get_playlist(self.key, parsed.type, parsed.cache_id, self._to_playlist_url(parsed))

    async def _save_playlist_cache(self, result: PlaylistResult) -> PlaylistInfo:
        entry = await PlaylistCacheEntry.save_playlist(
            self.key, result.type, result.cache_id,
            title=result.title,
            song_ids=result.song_ids,
            songs_meta=result.songs_meta)
        return entry.as_playlist_info(self._to_playlist_url(result), self.key)

    @abc.abstractmethod
    async def playlist_from_url(self, url: str, refresh: bool = False) -> PlaylistInfo | None:
        '''Get playlist info from URL, return None if URL is no match'''
        raise NotImplementedError

    @abc.abstractmethod
    async def user_playlists(self) -> list[UserPlaylistResult]:
        raise NotImplementedError

    @abc.abstractmethod
    def match_song_id(self, query: str) -> str | None:
        raise NotImplementedError


if typing.TYPE_CHECKING:
    Cookies = dict[str, str] | http.cookies.SimpleCookie

    class ARequestFunc(typing.Protocol):
        def __call__(self, method: str, url: str, data: bytes | None = None, params: dict | None = None,
                     headers: dict | None = None, cookies: Cookies | None = None, proxy: str | None = None) -> typing.Coroutine[typing.Any, typing.Any, bytes]:
            ...

    class CookiesGetter(typing.Protocol):
        def __call__(self) -> http.cookies.SimpleCookie:
            ...
