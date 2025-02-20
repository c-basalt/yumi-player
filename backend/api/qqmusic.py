from __future__ import annotations
import time
import re
import json
import random
import urllib.parse
import logging
import contextlib

from .common import API, SearchResult, UserPlaylistResult, InfoResult, NoPlayurlError, ParsedPlaylistUrl, PlaylistResult
from ..db import PlaylistInfo

logger = logging.getLogger('api.qqmusic')


class QQMusicAPI(API):
    _NAME = 'QQ音乐'

    _FORMATS = {
        'M800': {'name': '320mp3', 'ext': 'mp3', 'preference': 4},
        'M500': {'name': '128mp3', 'ext': 'mp3', 'preference': 3},
        'C400': {'name': '96aac', 'ext': 'm4a', 'preference': 2},
        'C200': {'name': '48aac', 'ext': 'm4a', 'preference': 1},
    }

    def _get_g_tk(self):
        n = 5381
        for c in self._get_cookie('qqmusic_key', '.qq.com', ''):
            n += (n << 5) + ord(c)
        return n & 2147483647

    def _get_uin(self):
        try:
            return int(self._get_cookie('uin', '.qq.com', 0))
        except ValueError:
            return 0

    async def _request_fcu(self, data: dict, **kwargs):
        return await self._request_json('POST', 'https://u.y.qq.com/cgi-bin/musicu.fcg', data=json.dumps({
            'comm': {
                'cv': 0,
                'ct': 24,
                'format': 'json',
                'uin': self._get_uin(),
            },
            **data,
        }, separators=(',', ':')).encode(), **kwargs)

    @staticmethod
    def _make_random_id(base: int):
        return str(round((base + random.random()) * 18014398509481984))

    async def _cfu_search(self, query) -> list[dict]:
        if not self._get_uin():
            return []
        rsp = await self._request_fcu({
            "comm": {
                "cv": 4747474,
                "ct": 24,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq.json",
                "needNewCode": 1,
                "uin": self._get_uin(),
                "g_tk_new_20200303": self._get_g_tk(),
                "g_tk": self._get_g_tk(),
            },
            "req_1": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "remoteplace": "txt.yqq.top",
                    "searchid": self._make_random_id(3),
                    "search_type": 0,
                    "query": query,
                    "page_num": 1,
                    "num_per_page": 10,
                },
            },
        })
        if rsp['req_1'].get('code'):
            logger.warning(f'QQMusic cfu搜索响应错误: {rsp}')
            return []
        return [{
            'id': str(song['mid']),
            'title': str(song['title']),
            'singers': [s['name'] for s in song['singer']],
            'duration': song['interval'],
        } for song in rsp['req_1']['data']['body']['song']['list']]

    async def _soso_search(self, query) -> list[dict]:
        rsp = await self._request_json('GET', 'http://c.y.qq.com/soso/fcgi-bin/client_search_cp', params={
            'format': 'json',
            'n': 10,
            'p': 1,
            'w': query,
            'cr': 1,
            'g_tk': self._get_g_tk(),
            't': 0,
        })
        if rsp.get('code'):
            logger.warning(f'QQMusic soso搜索响应错误: {rsp}')
            return []
        return [{
            'id': str(song['songmid']),
            'title': str(song['songname']),
            'singers': [s['name'] for s in song['singer']],
            'duration': song['interval'],
        } for song in rsp['data']['song']['list']]

    async def _smartbox_search(self, query) -> list[dict]:
        result = await self._request_json('GET', 'https://c6.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg', params={
            '_': int(time.time() * 1e3),
            'cv': 4747474,
            'ct': 24,
            'format': 'json',
            'platform': 'yqq.json',
            'key': query,
        })
        if result.get('code'):
            logger.warning(f'QQMusic smartbox搜索响应错误: {result}')
            return []
        return [{
            'id': str(song['mid']),
            'title': str(song['name']),
            'singers': [song['singer']],
        } for song in result['data']['song']['itemlist']]

    async def search(self, query: str, limit=5) -> list[SearchResult]:
        def _is_match(song: dict):
            title = self._strip_cover_text(song['title'])
            return self._check_full_match(query, title, song['singers'])

        def _extract_result(songs: list[dict]) -> list[SearchResult]:
            return [SearchResult(
                id=str(song['id']),
                title=str(song['title']),
                singer='/'.join(song['singers']),
                meta={'duration': song['duration']} if 'duration' in song else {},
            ) for song in songs if _is_match(song)][:limit]

        if not (result := await self._smartbox_search(query)):
            result = await self._soso_search(query)
        return _extract_result(result)

    async def _get_media_url(self, song_id: str, media_mid: str | None, proxy: str | None = None) -> str:
        url_rsp = await self._request_fcu({'req_1': {
            'module': 'vkey.GetVkeyServer',
            'method': 'CgiGetVkey',
            'param': {
                'guid': str(random.randrange(10**10, 10**11)),
                'songmid': [song_id],
                'songtype': [0],
                'uin': str(self._get_uin()),
                'loginflag': 1,
                'platform': '20',
            } if not media_mid else {
                'guid': str(random.randrange(10**10, 10**11)),
                'songmid': [song_id] * len(self._FORMATS),
                'songtype': [0] * len(self._FORMATS),
                'uin': str(self._get_uin()),
                'loginflag': 1,
                'platform': '20',
                'filename': [f'{code}{media_mid}.{f["ext"]}' for code, f in self._FORMATS.items()],
            }}}, proxy=proxy)

        result = url_rsp['req_1']
        if result.get('code'):
            raise ValueError(f'response error: {result}')

        formats = [(fmt.get('filename', '')[:4], fmt.get('purl')) for fmt in result['data']['midurlinfo']
                   if fmt.get('purl')]
        if not formats:
            raise NoPlayurlError(self.key)
        purl = max(formats, key=lambda x: self._FORMATS.get(x[0], {}).get('preference', 0))[1]
        return urllib.parse.urljoin('https://dl.stream.qqmusic.qq.com', purl)

    @staticmethod
    def _parse_meta(info_data: dict) -> dict:
        try:
            return {
                'duration': int(info_data['interval']),
                'decibel': float(info_data['volume']['gain']),
            }
        except Exception:
            logger.warning(f'元数据解析失败: {info_data.get("mid")}')
            return {}

    async def songinfo(self, song_id: str | SearchResult, proxy: str | None = None) -> InfoResult:
        song_id = song_id.id if isinstance(song_id, SearchResult) else song_id
        try:
            info_rsp = await self._request_fcu({'info': {
                'module': 'music.pf_song_detail_svr',
                'method': 'get_song_detail_yqq',
                'param': {
                    'song_mid': song_id,
                    'song_type': 0,
                },
            }})
            info_data = info_rsp['info']['data']['track_info']
            title = info_data['title']
            singer = '/'.join([s['name'] for s in info_data['singer']])
            media_mid = info_data['file']['media_mid']
        except Exception:
            logging.warning(f'media_id获取失败: {song_id}')
            info_data = {}
            media_mid = None

        if proxy:
            with contextlib.suppress(Exception):
                return InfoResult(
                    id=song_id,
                    url=await self._get_media_url(song_id, media_mid, proxy=None),
                    title=title or song_id,
                    singer=singer,
                )
            logger.debug(f'Retry getting songinfo using proxy for {song_id}')

        return InfoResult(
            id=song_id,
            url=await self._get_media_url(song_id, media_mid, proxy),
            title=title or song_id,
            singer=singer,
            meta=self._parse_meta(info_data),
        )

    async def _fetch_playlist(self, parsed_url: ParsedPlaylistUrl) -> PlaylistResult:
        def _parse_meta(song: dict):
            try:
                return {
                    'title': song['songname'],
                    'duration': song['interval'],
                    'singer': '/'.join([s['name'] for s in song['singer']]),
                }
            except Exception:
                logger.warning(f'Failed to parse meta for {song.get("id")}')
                return {}

        playlist_id = parsed_url.cache_id

        rsp_bytes = await self._request(
            'GET', 'http://i.y.qq.com/qzone-music/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg',
            params={'type': 1, 'json': 1, 'utf8': 1, 'onlysong': 0, 'disstid': playlist_id},
            headers={'Referer': f'https://y.qq.com/n/ryqq/playlist/{playlist_id}'}
        )
        rsp = json.loads(re.sub(r'^jsonCallback\((.*)\)$', r'\1', rsp_bytes.decode('utf-8')))

        if rsp.get('code') != 0 or len(rsp.get('cdlist', [])) == 0:
            raise ValueError(f'Failed to get playlist code={rsp.get("code")}')

        [data] = rsp['cdlist']
        songs_meta = {str(song['songmid']): _parse_meta(song) for song in data['songlist']}

        return PlaylistResult(
            type='playlist',
            cache_id=playlist_id,
            extra={},
            title=str(data['dissname']),
            song_ids=[str(song['songmid']) for song in data['songlist']],
            songs_meta=songs_meta,
        )

    def _parse_playlist_url(self, url: str) -> ParsedPlaylistUrl | None:
        if match := re.search(
            r'^(?:https?://)?y\.qq\.com/n/ryqq/playlist/(?P<id>[0-9]+)', url
        ) or re.search(
            r'^(?:https?://)?i\.y\.qq\.com/n2/m/share/details/taoge\.html\?(?:.*&)?id=(?P<id>[0-9]+)', url
        ):
            return ParsedPlaylistUrl('playlist', match.group('id'), {})

    def _to_playlist_url(self, parsed: ParsedPlaylistUrl | PlaylistResult) -> str:
        if parsed.type == 'playlist':
            return f'https://y.qq.com/n/ryqq/playlist/{parsed.cache_id}'
        raise ValueError(f'Unknown playlist type for {parsed}')

    async def playlist_from_url(self, url: str, refresh: bool = False) -> PlaylistInfo | None:
        if match := self._parse_playlist_url(url):
            assert match.type == 'playlist'
            url = self._to_playlist_url(match)
            if not refresh:
                if cached := await self._load_playlist_cache(match):
                    return cached
            result = await self._fetch_playlist(match)
            return await self._save_playlist_cache(result)

    async def user_playlists(self) -> list[UserPlaylistResult]:
        if not self._get_uin():
            return []
        rsp = await self._request_json(
            'GET', 'https://c6.y.qq.com/rsc/fcgi-bin/fcg_user_created_diss', headers={
                'origin': 'https://y.qq.com',
                'referer': 'https://y.qq.com/',
            }, params={
                'r': int(time.time() * 1e3),
                '_': int(time.time() * 1e3 + random.random() * 5),
                'cv': 4747474,
                'ct': 24,
                'format': 'json',
                'notice': 0,
                'platform': 'yqq.json',
                'needNewCode': 1,
                'uin': self._get_uin(),
                'g_tk_new_20200303': self._get_g_tk(),
                'g_tk': self._get_g_tk(),
                'hostuin': self._get_uin(),
                'sin': 0,
                'size': 1000,
            })

        return [UserPlaylistResult(
            url=f'https://y.qq.com/n/ryqq/playlist/{diss["tid"]}',
            title=str(diss['diss_name']),
            count=diss['song_cnt'],
        ) for diss in rsp.get('data', {}).get('disslist', []) if diss['tid']]

    def match_song_id(self, query: str) -> str | None:
        query = query.strip()
        id_pattern = r'(?P<id>\d{3}[A-Za-z0-9]{11})'
        if re.match(id_pattern, query):
            return query
        if match := re.search(rf'y\.qq\.com/n/ryqq/songDetail/{id_pattern}', query):
            return match.group('id')
        return None
