from __future__ import annotations
import unittest
import aiohttp
import asyncio
import json
import typing
import pathlib
import sys
import contextlib
import dataclasses
import base64
import os
import urllib.parse
import http.cookies
import logging
import argparse

project_root = pathlib.Path(__file__).parent.parent
sys.path.append(str(project_root))

if typing.TYPE_CHECKING:
    from backend.api.common import Cookies

from backend.api.common import API, PlaylistResult, ParsedPlaylistUrl  # noqa: E402
from backend.api import BilibiliAPI, NeteaseMusicAPI, QQMusicAPI  # noqa: E402


@contextlib.contextmanager
def disable_logger(logger_name: str):
    logger = logging.getLogger(logger_name)
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = False


@dataclasses.dataclass
class RequestParams:
    method: str
    url: str
    data: bytes | None
    params: dict | None
    headers: dict | None
    cookies: Cookies | None
    proxy: str | None


class CollectedTestData:
    """Container for collected test data."""
    def __init__(self):
        self.requests: list[RequestParams] = []
        self.responses: list[bytes] = []

    @staticmethod
    def _serialize_bytes(data: bytes) -> str:
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return base64.b64encode(data).decode()

    def to_dict(self) -> dict:
        """Convert to serializable dictionary."""
        return {
            'requests': [
                {
                    **dataclasses.asdict(req),
                    'data': self._serialize_bytes(req.data) if req.data else None
                }
                for req in self.requests
            ],
            'responses': [self._serialize_bytes(resp) for resp in self.responses]
        }


API_TYPE = typing.TypeVar('API_TYPE', bound=API)


class RequestProvider(typing.Generic[API_TYPE]):
    def __init__(self, api_cls: type[API_TYPE], cookies: http.cookies.SimpleCookie = http.cookies.SimpleCookie()):
        self._session: typing.Optional[aiohttp.ClientSession] = None
        self._hook_callback: typing.Callable[[RequestParams], bytes | None] | None = None
        self._collected_data: CollectedTestData | None = None
        self._cookies: http.cookies.SimpleCookie = cookies
        self.api = api_cls(self, self._get_cookies)

    def _get_cookies(self) -> http.cookies.SimpleCookie:
        """Cookie getter for API instance."""
        return self._cookies

    def set_cookies(self, cookies: http.cookies.SimpleCookie):
        """Configure cookies for API requests."""
        self._cookies = cookies

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    @contextlib.asynccontextmanager
    async def collect(self, key: str, filepath: str = 'test_api_data.json'):
        """Context manager to collect real requests and responses for test case building."""
        self._collected_data = CollectedTestData()
        try:
            yield self._collected_data
            with open(filepath, 'rt') as f:
                data = json.load(f)
            data[key] = self._collected_data.to_dict()
            with open(filepath, 'wt') as f:
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
        finally:
            self._collected_data = None

    async def __call__(self, method: str, url: str, data: bytes | None = None,
                       params: dict | None = None, headers: dict | None = None,
                       cookies: Cookies | None = None, proxy: str | None = None) -> bytes:

        request_params = RequestParams(method, url, data, params, headers, cookies, proxy)
        if self._hook_callback:
            if hook_response := self._hook_callback(request_params):
                return hook_response

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
            **(headers or {})
        }

        try:
            async with self.session.request(method, url, data=data, params=params, headers=headers,
                                            cookies=cookies, proxy=proxy) as response:
                response_data = await response.read()

                if self._collected_data is not None:
                    self._collected_data.requests.append(request_params)
                    self._collected_data.responses.append(response_data)

                return response_data

        except aiohttp.ClientError as e:
            raise ValueError(f"Request failed: {e}")

    async def close(self):
        """Close the aiohttp session if it exists."""
        if self._session:
            await self._session.close()
            self._session = None

    @contextlib.contextmanager
    def hook_request(self, callback: typing.Callable[[RequestParams], bytes | None]):
        """Context manager to hook request parameters.
        Hook callback returns bytes to mock the request, or None to pass the request through"""
        assert self._hook_callback is None, "At most one hook callback can be set"
        self._hook_callback = callback
        try:
            yield
        finally:
            self._hook_callback = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        await self.close()


class TestAPIHelpers(unittest.TestCase):
    """Test cases for API helper methods."""
    def _create_api(self, cookies=http.cookies.SimpleCookie()) -> API:
        class DummyAPI(API):
            async def search(self):
                pass

            async def songinfo(self):
                pass

            async def playlist_from_url(self):
                pass

            async def user_playlists(self):
                pass

            def match_song_id(self):
                pass

            def _parse_playlist_url(self, url):
                return None

            def _to_playlist_url(self, parsed):
                return ''

        return DummyAPI(lambda *args, **kwargs: None, lambda: cookies)  # type: ignore

    def test_check_full_match(self):
        api = self._create_api()

        def _test_expect_true(keyword: str, title: str, columns: list[str] = []):
            # Skip empty/whitespace-only queries as they are invalid
            if not keyword.strip():
                return
            self.assertTrue(api._check_full_match(keyword, title, columns))

        def _test_expect_false(keyword: str, title: str, columns: list[str] = []):
            # Skip empty/whitespace-only queries as they are invalid
            if not keyword.strip():
                return
            self.assertFalse(api._check_full_match(keyword, title, columns))

        # Single keyword matches
        _test_expect_true('hello', 'hello world')
        _test_expect_true('HELLO', 'hello world')
        _test_expect_true('world', 'hello world')

        # Multiple columns - at least one keyword must match title
        _test_expect_true('hello', 'hello there', ['world'])
        _test_expect_false('hello', 'hi there', ['hello world'])
        _test_expect_true('world hello', 'hello there', ['world'])

        # Multiple keywords - each keyword can match different columns
        _test_expect_true('hello world', 'hello world')
        _test_expect_true('HELLO WORLD', 'hello world')
        _test_expect_true('hello world', 'hello', ['world'])
        _test_expect_false('hello world', 'other', ['hello', 'world'])

        # No matches
        _test_expect_false('missing', 'hello world')
        _test_expect_false('hello missing', 'hello world')

        # Multiple spaces between words (valid)
        _test_expect_true('hello  world', 'hello world')

        # English word matches (requires word boundaries)
        _test_expect_false('app', 'apple')
        _test_expect_false('le', 'apple')
        _test_expect_true('apple', 'apple')
        _test_expect_true('apple', 'an apple')
        _test_expect_true('apple', 'apple!')
        _test_expect_false('apple', 'pineapple')
        _test_expect_false('pine', 'pineapple')
        _test_expect_false('app', 'happen')
        _test_expect_false('app', 'other', ['nope'])
        _test_expect_false('hello world', 'hello worlds')
        _test_expect_true('world', '你好world')

        # Partial CJK word matches (should succeed)
        _test_expect_true('你', '你好')
        _test_expect_true('好', '你好')
        _test_expect_true('你好 世界', '你好', ['世界'])
        _test_expect_false('世', '其他', ['世界'])
        _test_expect_false('你好世', '你好', ['世界'])

        # Only match in non-title columns (should fail)
        _test_expect_false('test', 'other', ['testing'])
        _test_expect_false('world', 'hello', ['new world'])
        _test_expect_true('hello world', 'hello', ['earth world'])

        # Matching Japanese text with Chinese characters
        _test_expect_true('东方', '東方project')
        _test_expect_true('遊戯', '游戏王')
        _test_expect_true('音乐 游戏', '音楽の世界', ['遊戯'])

    def test_strip_cover_text(self):
        api = self._create_api()

        def _test_expect(input: str, expected: str | None = None):
            self.assertEqual(api._strip_cover_text(input), expected or input)

        # Basic cases
        _test_expect("Song Title (Cover)")
        _test_expect("Song Title （Cover）")
        _test_expect("Song Title （Cover by Artist）", "Song Title")
        _test_expect("Song Title (cover by Multiple Artists)", "Song Title")
        _test_expect("Song Title （翻唱 by Artist）")

        # Cover in middle of title
        _test_expect("Song (Cover) Title", "Song (Cover) Title")
        _test_expect("Song （Cover by Artist） Title", "Song （Cover by Artist） Title")
        _test_expect("(Cover) Song Title", "(Cover) Song Title")

    def test_cookie_helper(self):
        # Test with empty cookie getter
        api = self._create_api()
        self.assertEqual(len(api.cookies), 0)

        test_cookies = http.cookies.SimpleCookie()
        test_cookies['key1'] = 'value1'
        test_cookies['key1']['domain'] = '.test.com'
        test_cookies['key2'] = 'value2'
        test_cookies['key2']['domain'] = 'sub.test.com'
        test_cookies['key3'] = 'value3'
        test_cookies['key3']['domain'] = '.other.com'
        test_cookies['key4'] = 'value4'
        test_cookies['key4']['domain'] = 'plain.com'
        api = self._create_api(cookies=test_cookies)

        self.assertEqual(api.cookies['key1'].value, 'value1')
        self.assertEqual(api.cookies['key2'].value, 'value2')
        self.assertEqual(api.cookies['key3'].value, 'value3')
        self.assertEqual(api.cookies['key4'].value, 'value4')

        with disable_logger('api.common'):
            self.assertEqual(api._get_cookie('key1', '.test.com'), 'value1')
            self.assertIsNone(api._get_cookie('key1', 'sub.test.com'))
            self.assertEqual(api._get_cookie('key2', 'sub.test.com'), 'value2')
            self.assertEqual(api._get_cookie('key2', '.test.com'), 'value2')
            self.assertIsNone(api._get_cookie('key3', '.test.com'))
            self.assertEqual(api._get_cookie('key3', '.other.com'), 'value3')

            self.assertEqual(api._get_cookie('key1', 'test.com'), 'value1')
            self.assertEqual(api._get_cookie('key4', 'plain.com'), 'value4')
            self.assertEqual(api._get_cookie('key4', '.plain.com'), 'value4')

            self.assertEqual(api._get_cookie('missing', '.test.com', 'default'), 'default')
            self.assertIsNone(api._get_cookie('missing', '.test.com'))

    def test_api_keys(self):
        self.assertEqual(BilibiliAPI(None, None).key, 'Bilibili')  # type: ignore
        self.assertEqual(NeteaseMusicAPI(None, None).key, 'NeteaseMusic')  # type: ignore
        self.assertEqual(QQMusicAPI(None, None).key, 'QQMusic')  # type: ignore


class TestMatchSongID(unittest.TestCase):
    """Test cases for API.match_song_id method."""

    def test_bilibili(self):
        api = BilibiliAPI(None, None)  # type: ignore

        def _assert_match(query: str, expected: str):
            self.assertEqual(api.match_song_id(query), expected)

        _assert_match('BV1Ln4y1R7HU', 'BV1Ln4y1R7HU')
        _assert_match('av1055633454', 'av1055633454')
        _assert_match('BV1Ln4y1R7HU_p2', 'BV1Ln4y1R7HU_p2')

        _assert_match('https://www.bilibili.com/video/BV1Ln4y1R7HU', 'BV1Ln4y1R7HU')
        _assert_match('https://www.bilibili.com/video/av1055633454', 'av1055633454')

        _assert_match('https://www.bilibili.com/video/BV1Ln4y1R7HU?p=2', 'BV1Ln4y1R7HU_p2')
        _assert_match('https://www.bilibili.com/video/BV1Ln4y1R7HU?p=2&t=30', 'BV1Ln4y1R7HU_p2')
        _assert_match('https://www.bilibili.com/video/BV1Ln4y1R7HU/?spm=123&p=3', 'BV1Ln4y1R7HU_p3')

        self.assertIsNone(api.match_song_id('invalid'))
        self.assertIsNone(api.match_song_id('https://www.bilibili.com/other/BV1Ln4y1R7HU'))

    def test_netease(self):
        api = NeteaseMusicAPI(None, None)  # type: ignore

        def _assert_match(query: str, expected: str):
            self.assertEqual(api.match_song_id(query), expected)

        _assert_match('460528', '460528')
        _assert_match('399367220', '399367220')
        _assert_match('网易云460528', '460528')
        _assert_match('网易云音乐460528', '460528')
        _assert_match('网易云 460528', '460528')
        _assert_match('网易云音乐 460528', '460528')

        _assert_match('https://music.163.com/song?id=460528', '460528')
        _assert_match('https://music.163.com/#/song?id=460528', '460528')
        _assert_match('https://music.163.com/song/?id=460528', '460528')
        _assert_match('https://music.163.com/#/song/?id=460528', '460528')

        _assert_match('https://music.163.com/#/song?id=460528&auto=1', '460528')
        _assert_match('https://music.163.com/song?uid=12345&id=460528', '460528')
        _assert_match('https://music.163.com/song/?market=from_qq&id=460528&', '460528')

        self.assertIsNone(api.match_song_id('invalid'))
        self.assertIsNone(api.match_song_id('https://music.163.com/playlist?id=460528'))
        self.assertIsNone(api.match_song_id('0123456'))  # Leading zero
        self.assertIsNone(api.match_song_id('12345'))    # Too short
        self.assertIsNone(api.match_song_id('https://music.163.com/song/460528'))  # Missing id parameter

    def test_qqmusic(self):
        api = QQMusicAPI(None, None)  # type: ignore

        def _assert_match(query: str, expected: str):
            self.assertEqual(api.match_song_id(query), expected)

        _assert_match('002HLH8k10De6r', '002HLH8k10De6r')
        _assert_match('003wQdka0xw2I7', '003wQdka0xw2I7')

        _assert_match('https://y.qq.com/n/ryqq/songDetail/002HLH8k10De6r', '002HLH8k10De6r')

        self.assertIsNone(api.match_song_id('invalid'))
        self.assertIsNone(api.match_song_id('https://y.qq.com/n/ryqq/playlist/002HLH8k10De6r'))
        self.assertIsNone(api.match_song_id('002HLH8k'))  # Too short


class TestMatchPlaylistUrl(unittest.TestCase):
    def create_assert(self, api: API, list_type: str | None):
        def _assert(url: str, id: str, extra: dict = {}):
            result = api._parse_playlist_url(url)
            if list_type is None:
                self.assertIsNone(result)
            else:
                self.assertIsNotNone(result)
                assert result is not None  # for linter
                self.assertEqual(result.type, list_type)
                self.assertEqual(result.cache_id, id)
                self.assertEqual(result.extra, extra)

                # Test bidirectional conversion
                converted_url = api._to_playlist_url(result)
                converted_result = api._parse_playlist_url(converted_url)
                self.assertIsNotNone(converted_result)
                assert converted_result is not None  # for linter
                self.assertEqual(converted_result.type, result.type)
                self.assertEqual(converted_result.cache_id, result.cache_id)
                self.assertEqual(converted_result.extra, result.extra)
        return _assert

    def test_bilibili(self):
        api = BilibiliAPI(None, None)  # type: ignore
        assert_multipart = self.create_assert(api, 'multipart')
        assert_collection = self.create_assert(api, 'collection')
        assert_series = self.create_assert(api, 'series')
        assert_favorite = self.create_assert(api, 'favorite')
        assert_invalid = self.create_assert(api, None)

        bili_main = 'https://www.bilibili.com'
        bili_space = 'https://space.bilibili.com'

        # Test BV/av video URLs (multipart)
        assert_multipart(f'{bili_main}/video/BV1Ln4y1R7HU', 'BV1Ln4y1R7HU')
        assert_multipart(f'{bili_main}/video/BV1Ln4y1R7HU?p=2&t=30', 'BV1Ln4y1R7HU')
        assert_multipart(f'{bili_main}/video/av1055633454', 'av1055633454')
        assert_multipart(f'{bili_main}/video/av1055633454?spm=123', 'av1055633454')

        # Test collection URLs
        assert_collection(f'{bili_space}/123456/channel/collectiondetail?sid=789', '789', {'uid': '123456'})
        assert_collection(f'{bili_space}/123456/channel/collectiondetail?spm=123&sid=789', '789', {'uid': '123456'})
        assert_collection(f'{bili_space}/123456/lists/789?type=season', '789', {'uid': '123456'})
        assert_collection(f'{bili_space}/123456/lists/789?other=param&type=season', '789', {'uid': '123456'})
        assert_invalid(f'{bili_space}/123456/lists/789?type=season2', '')  # Should not match with word boundary

        # Test series URLs
        assert_series(f'{bili_space}/123456/channel/seriesdetail?sid=789', '789', {'uid': '123456'})
        assert_series(f'{bili_space}/123456/channel/seriesdetail?spm=123&sid=789', '789', {'uid': '123456'})
        assert_series(f'{bili_space}/123456/lists/789?type=series', '789', {'uid': '123456'})
        assert_series(f'{bili_space}/123456/lists/789?other=param&type=series', '789', {'uid': '123456'})
        assert_invalid(f'{bili_space}/123456/lists/789?type=series2', '')  # Should not match with word boundary
        assert_series(f'{bili_main}/medialist/play/123456?business_id=789', '789', {'uid': '123456'})
        assert_series(f'{bili_main}/medialist/play/123456?other=param&business_id=789', '789', {'uid': '123456'})
        assert_series(f'{bili_main}/list/123456?sid=789', '789', {'uid': '123456'})
        assert_series(f'{bili_main}/list/123456?other=param&sid=789', '789', {'uid': '123456'})

        # Test favorite list URLs
        assert_favorite(f'{bili_space}/123456/favlist?fid=789', '789')
        assert_favorite(f'{bili_space}/123456/favlist?other=param&fid=789', '789')
        assert_favorite(f'{bili_main}/medialist/play/ml789', '789')
        assert_favorite(f'{bili_main}/medialist/play/ml789?param=value', '789')
        assert_favorite(f'{bili_main}/list/ml789', '789')
        assert_favorite(f'{bili_main}/list/ml789?param=value', '789')

        # Test invalid URLs
        assert_invalid('invalid_url', '')
        assert_invalid(f'{bili_main}/other/BV1Ln4y1R7HU', '')
        assert_invalid('BV1Ln4y1R7HU', '')
        assert_invalid('av1055633454', '')

    def test_netease(self):
        api = NeteaseMusicAPI(None, None)  # type: ignore
        assert_playlist = self.create_assert(api, 'playlist')
        assert_invalid = self.create_assert(api, None)

        main = 'https://music.163.com'

        # Test playlist URLs
        assert_playlist(f'{main}/playlist?id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/playlist?other=param&id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/#/playlist?id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/#/my/m/music/playlist?id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/#/playlist?auto=1&id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/m/playlist?id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/m/playlist?market=from_qq&id=123456', '123456', {'type': 'playlist'})
        assert_playlist(f'{main}/m/playlist?market=from_qq&id=123456&other=param', '123456', {'type': 'playlist'})

        # Test toplist URLs
        assert_playlist(f'{main}/discover/toplist?id=123456', '123456', {'type': 'discover/toplist'})
        assert_playlist(f'{main}/discover/toplist?other=param&id=123456', '123456', {'type': 'discover/toplist'})
        assert_playlist(f'{main}/#/discover/toplist?id=123456', '123456', {'type': 'discover/toplist'})
        assert_playlist(f'{main}/#/discover/toplist?auto=1&id=123456', '123456', {'type': 'discover/toplist'})

        # Test invalid URLs
        assert_invalid('invalid_url', '')
        assert_invalid(f'{main}/song?id=123456', '')
        assert_invalid(f'{main}/playlist', '')
        assert_invalid('123456', '')

    def test_qqmusic(self):
        api = QQMusicAPI(None, None)  # type: ignore
        assert_playlist = self.create_assert(api, 'playlist')
        assert_invalid = self.create_assert(api, None)

        # Test playlist URLs
        assert_playlist('https://y.qq.com/n/ryqq/playlist/123456', '123456')
        assert_playlist('https://y.qq.com/n/ryqq/playlist/123456?auto=1', '123456')
        assert_playlist('https://i.y.qq.com/n2/m/share/details/taoge.html?id=123456', '123456')
        assert_playlist('https://i.y.qq.com/n2/m/share/details/taoge.html?other=param&id=123456', '123456')

        # Test invalid URLs
        assert_invalid('invalid_url', '')
        assert_invalid('https://y.qq.com/n/ryqq/songDetail/123456', '')
        assert_invalid('https://y.qq.com/n/ryqq/playlist', '')
        assert_invalid('123456', '')


class TestAPIMixin(typing.Generic[API_TYPE]):
    _API_CLASS: type[API_TYPE]
    _TEST_SONGINFO: dict
    _TEST_SEARCH: dict
    _TEST_PLAYLIST_URL: list[dict]

    async def asyncSetUp(self):
        self.provider = RequestProvider(self._API_CLASS)
        self.api = self.provider.api

    async def asyncTearDown(self):
        await self.provider.close()
        await asyncio.sleep(1)

    def assertFieldEqual(self, value, expected):
        assert isinstance(self, unittest.TestCase)
        if isinstance(expected, type):
            self.assertIsInstance(value, expected)
        elif isinstance(expected, dict):
            self.assertEqual(set(value.keys()), set(expected.keys()))
            for k, v in value.items():
                self.assertFieldEqual(v, expected[k])
        else:
            self.assertEqual(value, expected)

    async def test_songinfo(self):
        assert isinstance(self, unittest.TestCase)
        if not getattr(self, '_TEST_SONGINFO', None):
            raise unittest.SkipTest('No test data for songinfo')

        song_info = await self.api.songinfo(self._TEST_SONGINFO['id'])
        self.assertEqual(song_info.id, self._TEST_SONGINFO['id'])
        self.assertEqual(song_info.title, self._TEST_SONGINFO['response']['title'])
        self.assertEqual(song_info.singer, self._TEST_SONGINFO['response']['singer'])
        self.assertFieldEqual(song_info.headers, self._TEST_SONGINFO['response']['headers'])
        self.assertFieldEqual(song_info.meta, self._TEST_SONGINFO['response']['meta'])
        self.assertEqual(os.path.basename(urllib.parse.urlparse(song_info.url).path),
                         self._TEST_SONGINFO['response']['filename'])

        async with self.provider.session.get(song_info.url, headers=song_info.headers) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(int(resp.headers['Content-Length']), self._TEST_SONGINFO['response']['size'])

    async def test_search(self):
        assert isinstance(self, unittest.TestCase)
        if not getattr(self, '_TEST_SEARCH', None):
            raise unittest.SkipTest('No test data for search')

        results = await self.api.search(self._TEST_SEARCH['query'])
        self.assertEqual(set(r.id for r in results), set(self._TEST_SEARCH['song_ids']))

    async def _test_playlist_url(self, method_name: str):
        assert isinstance(self, unittest.TestCase)
        for playlist_info in self._TEST_PLAYLIST_URL:
            if playlist_info['handler_method'] != method_name:
                continue
            handler = getattr(self.api, playlist_info['handler_method'])

            playlist: PlaylistResult = await handler(
                ParsedPlaylistUrl('', *playlist_info['input']))

            self.assertEqual(playlist.type, playlist_info['type'])
            self.assertEqual(playlist.cache_id, playlist_info['cache_id'])
            self.assertEqual(playlist.extra, playlist_info.get('extra', {}))
            self.assertEqual(playlist.title, playlist_info['title'])
            for key, meta in playlist_info['songs_meta'].items():
                self.assertDictEqual(playlist.songs_meta[key], meta)
            self.assertFalse(set(playlist_info['song_ids']) - set(playlist.song_ids))
            self.assertEqual(self.api._to_playlist_url(playlist), playlist_info['normalized_url'])


class TestNeteaseMusicAPI(TestAPIMixin[NeteaseMusicAPI], unittest.IsolatedAsyncioTestCase):
    _API_CLASS = NeteaseMusicAPI
    _TEST_SONGINFO = {
        'id': '460528',
        'response': {
            'title': '白金ディスコ',
            'singer': '井口裕香',
            'headers': {},
            'filename': '410390284f16e963b8cfba73a65ea58a.mp3',
            'size': 10225415,
            'meta': {
                'duration': 256,
                'decibel': -11.1449,
            },
        },
    }
    _TEST_SEARCH = {
        'query': '白金ディスコ 井口裕香',
        'song_ids': ['460528', '399367220'],
    }
    _TEST_PLAYLIST_URL = [{
        'handler_method': '_fetch_playlist',
        'input': ('9345473', {'type': 'playlist'}),
        'normalized_url': 'https://music.163.com/playlist?id=9345473',
        'type': 'playlist',
        'cache_id': '9345473',
        'extra': {'type': 'playlist'},
        'title': '春☆稍纵即逝的樱花季(ゲーム插曲)',
        'song_ids': ['478393', '641644'],
        'songs_meta': {
            '692560': {'title': '親愛なる世界へ', 'duration': 318, 'singer': 'Ceui'},
        },
    }]

    async def test_playlist(self):
        await self._test_playlist_url('_fetch_playlist')


class TestQQMusicAPI(TestAPIMixin[QQMusicAPI], unittest.IsolatedAsyncioTestCase):
    _API_CLASS = QQMusicAPI
    _TEST_SONGINFO = {
        'id': '002HLH8k10De6r',
        'response': {
            'title': '星间飞行',
            'singer': '中島愛',
            'headers': {},
            'filename': 'M500003AN8qy3igKYS.mp3',
            'size': 3745158,
            'meta': {
                'duration': 234,
                'decibel': -11.012,
            },
        },
    }
    _TEST_SEARCH = {
        'query': '星间飞行',
        'song_ids': ['002HLH8k10De6r', '002rbyGQ2enDEn', '001oBpTk2HjgoR', '003wQdka0xw2I7'],
    }
    _TEST_PLAYLIST_URL = [{
        'handler_method': '_fetch_playlist',
        'input': ('9209322004', {}),
        'normalized_url': 'https://y.qq.com/n/ryqq/playlist/9209322004',
        'type': 'playlist',
        'cache_id': '9209322004',
        'title': '哔哩哔哩官方ACG精选',
        'song_ids': ['00221jjt01LOTE', '002sh9nq3rZBWp'],
        'songs_meta': {
            '002w57E00BGzXn': {'title': '起风了', 'duration': 311, 'singer': '周深'},
        },
    }]

    async def test_playlist(self):
        await self._test_playlist_url('_fetch_playlist')


class TestBilibiliAPI(TestAPIMixin[BilibiliAPI], unittest.IsolatedAsyncioTestCase):
    _API_CLASS = BilibiliAPI
    _TEST_SONGINFO = {
        'id': 'BV1Ln4y1R7HU',
        'response': {
            'title': '【冰糖IO未披露新皮免费领取！】免费live2d模型',
            'singer': '神宫凉子',
            'headers': {
                'user-agent': str,
                'referer': 'https://www.bilibili.com/video/BV1Ln4y1R7HU',
            },
            'meta': {
                'avid': 'av1055633454',
                'type': '日常',
                'duration': 79,
                'decibel': -7.7,
                'play_count': int,
                'pages': list,
            },
            'filename': '1577576366-1-30280.m4s',
            'size': 1913319,
        },
    }
    _TEST_SEARCH = {
        'query': '真夜白音 模型公开',
        'song_ids': ['BV1i94y1W77Y'],
    }
    _TEST_PLAYLIST_URL = [{
        'handler_method': '_fetch_playlist_from_bvid',
        'input': ('BV1Xx41117tr', {}),
        'normalized_url': 'https://www.bilibili.com/video/BV1Xx41117tr',
        'type': 'multipart',
        'cache_id': 'BV1Xx41117tr',
        'title': '【CS公开课】计算机程序的构造和解释（SICP）【中英字幕】【FoOTOo&HITPT&Learning-SICP】',
        'song_ids': ['BV1Xx41117tr_p20'],
        'songs_meta': {
            'BV1Xx41117tr_p1': {
                'title': 'Lec1a：Lisp概览',
                'duration': 4375,
            },
        },
    }, {
        'handler_method': '_fetch_fav_playlist',
        'input': ('770262946', {}),
        'normalized_url': 'https://www.bilibili.com/list/ml770262946',
        'type': 'favorite',
        'cache_id': '770262946',
        'title': '小毛线收藏',
        'song_ids': ['BV1zGe6edE2J', 'BV1H24y1T7ZY', 'BV1ev4y1E7xP', 'BV1qv4y1c7mK', 'BV1vb4y1B7DC',
                     'BV17K4y1j7rV', 'BV17y4y167Uc', 'BV1Ba4y177Zg', 'BV1fJ411Q7Qw', 'BV1tJ411Q751',
                     'BV11J411Q7UQ', 'BV1VJ411F7cU', 'BV1VJ411R7ou'],
        'songs_meta': {
            'BV1VJ411R7ou': {
                'title': '【阿萨aza】5000粉庆祝初手书！当酒后你和可爱阿萨去跳舞时...',
                'duration': 64,
                'singer': 'はナビ',
            },
        },
    }, {
        'handler_method': '_fetch_series_playlist',
        'input': ('1871798', {'uid': '434334701'}),
        'normalized_url': 'https://space.bilibili.com/434334701/lists/1871798?type=series',
        'type': 'series',
        'cache_id': '1871798',
        'extra': {'uid': '434334701'},
        'title': '鲨歌',
        'song_ids': ['BV1APtdedEgS', 'BV1gp4y1e71f'],
        'songs_meta': {
            'BV1APtdedEgS': {
                'title': '翻唱了老八翻唱的「LOVE 2000」',
                'duration': 111,
            },
        },
    }, {
        'handler_method': '_fetch_collection_playlist',
        'input': ('558180', {'uid': '434334701'}),
        'normalized_url': 'https://space.bilibili.com/434334701/lists/558180?type=season',
        'type': 'collection',
        'cache_id': '558180',
        'extra': {'uid': '434334701'},
        'title': '鲨鱼舞蹈系列',
        'song_ids': ['BV1CT41147Uz', 'BV1ti4y1k7ez'],
        'songs_meta': {
            'BV1CT41147Uz': {
                'title': '越南神曲叮叮当当舞！',
                'duration': 27,
            },
        },
    }, {
        'handler_method': '_fetch_playlist_from_bvid',
        'input': ('BV1rs4y1S7uB', {}),
        'normalized_url': 'https://space.bilibili.com/434334701/lists/558180?type=season',
        'type': 'collection',
        'cache_id': '558180',
        'extra': {'uid': '434334701'},
        'title': '鲨鱼舞蹈系列',
        'song_ids': ['BV1CT41147Uz', 'BV1ti4y1k7ez'],
        'songs_meta': {
            'BV1CT41147Uz': {
                'title': '越南神曲叮叮当当舞！',
                'duration': 27,
            },
        },
    }]

    async def test_playurl_api(self):
        playurl = await self.api._get_playinfo('BV1Ln4y1R7HU', 1577576366)
        self.assertEqual(playurl['code'], 0)
        self.assertTrue('1577576366-1-30280.m4s' in str(playurl))

    async def test_favorite_playlist(self):
        await self._test_playlist_url('_fetch_fav_playlist')

    async def test_series_playlist(self):
        await self._test_playlist_url('_fetch_series_playlist')

    async def test_collection_playlist(self):
        await self._test_playlist_url('_fetch_collection_playlist')

    async def test_bvid_playlist(self):
        await self._test_playlist_url('_fetch_playlist_from_bvid')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run API tests')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--skip-api', action='store_true')
    args = parser.parse_args()

    async def run():
        async with RequestProvider(QQMusicAPI) as provider:
            _ = provider.api

    if args.run:
        asyncio.run(run())
    else:
        if args.skip_api:
            del TestBilibiliAPI
            del TestNeteaseMusicAPI
            del TestQQMusicAPI
        asyncio.get_event_loop().set_debug(False)
        unittest.main(verbosity=2, argv=[arg for arg in sys.argv if not '--skip-api'.startswith(arg)])
