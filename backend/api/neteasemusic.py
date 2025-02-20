from __future__ import annotations
import json
import hashlib
import random
import time
import re
import asyncio
import logging

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from .common import API, SearchResult, UserPlaylistResult, InfoResult, NoPlayurlError, ParsedPlaylistUrl, PlaylistResult
from ..db import PlaylistInfo


logger = logging.getLogger('api.neteasemusic')


class NeteaseMusicAPI(API):
    _NAME = '网易云'

    async def _request_eapi(self, path: str, body: dict):
        body['header'] = {
            'osver': 'undefined',
            'deviceId': 'undefined',
            'appver': '8.0.0',
            'versioncode': '140',
            'mobilename': 'undefined',
            'buildver': '1623435496',
            'resolution': '1920x1080',
            '__csrf': '',
            'os': 'pc',
            'channel': 'undefined',
            'requestId': f'{time.time() * 1e3:.0f}_{random.randint(0, 1000):04}',
            **self._get_cookie_dict(['MUSIC_U', 'MUSIC_A'], '.163.com'),
        }

        request_text = json.dumps(body, separators=(',', ':'))

        msg_digest = hashlib.md5(f'nobody/api{path}use{request_text}md5forencrypt'.encode()).hexdigest()
        payload = f'/api{path}-36cd479b6b5-{request_text}-36cd479b6b5-{msg_digest}'
        encrypted = AES.new(b"e82ckenh8dichen8", AES.MODE_ECB).encrypt(pad(payload.encode(), 16))

        data = f'params={encrypted.hex().upper()}'.encode()
        headers = {
            'Referer': 'https://music.163.com',
            'Cookie': '; '.join([f'{k}={v}' for k, v in body['header'].items()]),
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Real-IP': '118.88.88.88',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
        }

        return json.loads(await self._request(
            'POST', f'https://interface.music.163.com/eapi{path}', data=data, headers=headers))

    @classmethod
    def _extract_search_result(cls, query: str, rsp: dict) -> list[SearchResult]:
        def _is_match(song: dict):
            title = ' / '.join([cls._strip_cover_text(song['name']), *song.get('transNames', [])])
            artists = [a['name'] for a in song['artists']]
            return cls._check_full_match(query, title, artists)

        def _filter_songs(songs: list[dict] | None):
            return [song for song in songs or [] if _is_match(song)]

        return [SearchResult(
            id=str(song['id']),
            title=song['name'],
            singer='/'.join(a['name'] for a in song['artists']),
            meta={
                'duration': round(song['duration'] / 1000),
            }
        ) for song in _filter_songs(rsp['result'].get('songs') or [])]

    async def _quick_search(self, query: str) -> list[SearchResult]:
        rsp = await self._request_eapi('/search/suggest/web', {'s': query})
        return self._extract_search_result(query, rsp)

    async def _full_search(self, query: str) -> list[SearchResult]:
        rsp = await self._request_eapi('/search/get', {'s': query, 'type': 1, 'limit': 30, 'offset': 0})
        return self._extract_search_result(query, rsp)

    async def search(self, query: str, limit=5) -> list[SearchResult]:
        if matches := await self._quick_search(query):
            return matches[:limit]
        return (await self._full_search(query))[:limit]

    async def _get_meta(self, song_id: str):
        try:
            rsp = await self._request_json(
                'GET', f'http://music.163.com/api/song/detail?id={song_id}&ids=%5B{song_id}%5D')
            info = rsp['songs'][0]
            return info['name'], '/'.join(a['name'] for a in info['artists'])
        except Exception:
            return None, None

    @staticmethod
    def _parse_meta(song: dict):
        try:
            return {
                'duration': round(song['time'] / 1000),
                'decibel': float(song['gain']),
            }
        except Exception:
            logger.warning(f'元数据解析失败: {song.get("id")}')
            return {}

    async def _get_quality_url(self, song_id: str, quality: str):
        rsp = await self._request_eapi(
            '/song/enhance/player/url/v1', {'ids': f'[{song_id}]', 'level': quality, 'encodeType': 'flac'})
        song = rsp['data'][0]
        if song.get('freeTrialInfo'):
            raise NoPlayurlError(self.key)
        url: str | None = song.get('url')
        if url and re.search(r'^https?://', url or ''):
            return url, self._parse_meta(song)
        raise NoPlayurlError(self.key)

    async def songinfo(self, song_id: str | SearchResult, proxy: str | None = None) -> InfoResult:
        song_id = song_id.id if isinstance(song_id, SearchResult) else song_id
        (title, singer), (url, meta) = await asyncio.gather(
            self._get_meta(song_id), self._get_quality_url(song_id, 'exhigh'))
        return InfoResult(
            id=song_id,
            url=url,
            title=title or song_id,
            singer=singer,
            meta=meta,
        )

    async def _fetch_playlist(self, parsed: ParsedPlaylistUrl) -> PlaylistResult:
        def _parse_meta(song: dict):
            try:
                return {
                    'title': song['name'],
                    'duration': round(song['dt'] / 1000),
                    'singer': '/'.join(a['name'] for a in song['ar']),
                }
            except Exception:
                logger.warning(f'元数据解析失败: {song.get("id")}')
                return {}

        playlist_id = parsed.cache_id

        rsp = await self._request_eapi(
            '/v3/playlist/detail', {'id': playlist_id, 't': '-1', 'n': '10000', 's': '0'})
        if rsp.get('code') != 200:
            raise ValueError(f'Failed to get playlist code={rsp.get("code")}')

        return PlaylistResult(
            type='playlist',
            cache_id=playlist_id,
            extra=parsed.extra,
            title=str(rsp['playlist']['name']),
            song_ids=[str(i['id']) for i in rsp['playlist']['tracks']],
            songs_meta={str(i['id']): _parse_meta(i) for i in rsp['playlist']['tracks']},
        )

    def _parse_playlist_url(self, url: str) -> ParsedPlaylistUrl | None:
        if match := re.search(
            r'^(?:https?://)?(?:y\.)?music\.163\.com/(?:#/(?:my/m/music/)?|m/)?(?P<type>playlist|discover/toplist)/?\?(?:.*&)?id=(?P<id>[0-9]+)', url
        ):
            return ParsedPlaylistUrl('playlist', match.group('id'), {'type': match.group('type')})
        return None

    def _to_playlist_url(self, parsed: ParsedPlaylistUrl | PlaylistResult) -> str:
        if parsed.type == 'playlist':
            return f'https://music.163.com/{parsed.extra["type"]}?id={parsed.cache_id}'
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
        return None

    async def user_playlists(self) -> list[UserPlaylistResult]:
        if not self._get_cookie('MUSIC_U', '.163.com'):
            return []

        page = await self._request('GET', 'https://music.163.com/', cookies=self.cookies)
        if not (match := re.search(r'GUser={userId:(\d+)', page.decode())):
            return []

        rsp = await self._request_eapi('/user/playlist', {
            'uid': int(match.group(1)),
            'limit': 1000,
            'offset': 0,
            'includeVideo': True,
        })

        return [UserPlaylistResult(
            url=f'https://music.163.com/playlist?id={i["id"]}',
            title=i['name'],
            count=i['trackCount'],
        ) for i in rsp.get('playlist', [])]

    def match_song_id(self, query: str) -> str | None:
        query = query.strip()
        if re.match(r'[1-9]\d{5,}', query):
            return query
        if match := re.search(r'网易云(?:音乐)?\s*(?P<id>[1-9]\d+)', query):
            return match.group('id')
        if match := re.search(r'music\.163\.com/(?:#/)?song/?\?(?:.*&)?id=(?P<id>[1-9]\d+)', query):
            return match.group('id')
        return None
