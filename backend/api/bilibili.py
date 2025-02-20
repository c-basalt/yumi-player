from __future__ import annotations
import uuid
import re
import json
import contextlib
import logging
import itertools
import asyncio
import typing
import html

from .common import API, SearchResult, InfoResult, ParsedPlaylistUrl, PlaylistResult
from ..db import PlaylistInfo, PlaylistCacheEntry

logger = logging.getLogger('api.bilibili')


class BilibiliAPI(API):
    BVID_PATTERN = r'(?P<bvid>av\d+|(?:BV|bv)[A-Za-z0-9]{10})'
    _NAME = 'B站'

    @staticmethod
    def _clean_html(s: str):
        return re.sub(r'<[^>]*?>', '', s)

    @staticmethod
    def _parse_duration(s: str):
        duration = 0
        for component in s.split(':'):
            duration *= 60
            duration += float(component)
        return int(duration)

    async def search(self, query: str, limit=5) -> list[SearchResult]:
        cookies = self.cookies
        if 'buvid3' not in cookies:
            cookies['buvid3'] = f'{uuid.uuid4()}infoc'
            cookies['buvid3']['domain'] = '.bilibili.com'
        rsp = await self._request_json('GET', 'https://api.bilibili.com/x/web-interface/search/type', params={
            'Search_key': query,
            'keyword': query,
            'page': 1,
            'context': '',
            'duration': 0,
            'tids_2': '',
            '__refresh__': 'true',
            'search_type': 'video',
            'tids': 0,
            'highlight': 0,
        }, cookies=cookies)

        def filter_search(video):
            try:
                hit_columns = video.get('hit_columns') or []
                if 'title' not in hit_columns:
                    return False

                title = html.unescape(re.sub(r'</?em\b[^>]*>', '', video['title']))
                columns = [video.get(key, '') for key in hit_columns if key != 'title']

                return self._check_full_match(query, title, columns)
            except Exception:
                logger.exception(f'过滤搜索结果时出错: {video}')
                return False

        videos = [video for video in rsp['data']['result'] if filter_search(video)][:limit]

        return [
            SearchResult(
                id=video['bvid'],
                title=self._clean_html(video['title']),
                singer=video['author'],
                meta={
                    'tag': video['tag'].split(','),
                    'play_count': video['play'],
                    'duration': self._parse_duration(video['duration']),
                    'type': video['typename'],
                }) for video in videos
        ]

    @staticmethod
    def _search_json(key: str, s: str):
        if match := re.search(rf'{key}\s*=\s*({{.*?}})\s*[<;]', s):
            return json.loads(match[1])
        raise ValueError(f'No JSON found for key {key}')

    @staticmethod
    def _parse_playinfo(playinfo):
        audio = max(playinfo['data']['dash']['audio'], key=lambda x: x.get('bandwidth', x['id']))
        return audio['baseUrl']

    @classmethod
    def _parse_meta(cls, webpage: str, page: int | None = None):
        video_meta = cls._search_json('__INITIAL_STATE__', webpage)['videoData']
        if page is not None:
            page_meta = video_meta['pages'][page - 1]
            cid, title = page_meta['cid'], page_meta['part']
            meta_extra = {'title': video_meta['title']}
        else:
            cid, title = video_meta['cid'], video_meta['title']
            meta_extra = {}
        return video_meta['bvid'], cid, title, video_meta['owner']['name'], {
            'avid': f"av{video_meta['aid']}",
            'type': video_meta['tname'],
            'play_count': video_meta['stat']['view'],
            'pages': video_meta['pages'],
            **meta_extra,
        }

    async def _get_playinfo(self, bvid: str, cid: int):
        return await self._request_json('GET', 'https://api.bilibili.com/x/player/playurl', params={
            'bvid': bvid, 'cid': cid, 'fnval': 4048})

    @staticmethod
    def _parse_audio_meta(playinfo: dict, bvid: str):
        try:
            return {
                'duration': round(playinfo['data']['timelength'] / 1000),
                'decibel': float(playinfo['data']['volume']['measured_i']),
            }
        except Exception:
            logger.warning(f'元数据解析失败: {bvid}')
            return {}

    async def _get_part_info(self, bvid: str, part: int | None = None, proxy: str | None = None):
        page_url = f'https://www.bilibili.com/video/{bvid}' + (f'?p={part}' if part else '')
        webpage = (await self._request('GET', page_url, cookies=self.cookies, proxy=proxy)).decode('utf-8')

        bvid, cid, title, uploader, meta = self._parse_meta(webpage, part)
        try:
            playinfo = self._search_json('__playinfo__', webpage)
        except ValueError:
            logger.debug(f'No playinfo found for {bvid}, using playurl API instead')
            playinfo = await self._get_playinfo(bvid, cid)
        audio_url = self._parse_playinfo(playinfo)
        return InfoResult(
            id=f'{bvid}_p{part}' if part else bvid,
            url=audio_url,
            title=title,
            singer=uploader,
            headers={
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
                'referer': page_url,
            },
            meta={**meta, **self._parse_audio_meta(playinfo, bvid)},
        )

    async def songinfo(self, song_id: str | SearchResult, proxy: str | None = None) -> InfoResult:
        if proxy:
            with contextlib.suppress(Exception):
                return await self.songinfo(song_id, proxy=None)
            logger.debug(f'Retry getting songinfo using proxy for {song_id}')

        song_id = song_id.id if isinstance(song_id, SearchResult) else song_id
        if match := re.match(r'(?P<bvid>[^_]*)_p(?P<part>\d+)', song_id):
            bvid, part = match.group('bvid'), match.group('part')
            return await self._get_part_info(bvid, int(part), proxy)
        else:
            return await self._get_part_info(song_id, None, proxy)

    async def _fetch_playlist_from_bvid(self, parsed_url: ParsedPlaylistUrl) -> PlaylistResult:
        bvid = parsed_url.cache_id

        page_url = f'https://www.bilibili.com/video/{bvid}'
        webpage = (await self._request('GET', page_url, cookies=self.cookies)).decode('utf-8')
        video_data = self._search_json('__INITIAL_STATE__', webpage)['videoData']

        # in case that avid is provided instead
        bvid = video_data['bvid']
        page_url = f'https://www.bilibili.com/video/{bvid}'

        # 视频合集
        if collection_info := video_data.get('ugc_season'):
            if collection_info.get('id') and collection_info.get('season_type') == 1:
                logger.debug(f'从 {bvid} 找到合集={collection_info.get("id")}')
                song_ids, songs_meta = [], {}
                playlist_id, list_title, uploader_uid = (collection_info.get(key) for key in ('id', 'title', 'mid'))
                for sub_section in collection_info['sections']:
                    for entry in sub_section['episodes']:
                        song_ids.append(entry['bvid'])
                        songs_meta[entry['bvid']] = {
                            'title': entry['arc']['title'],
                            'duration': entry['arc']['duration'],
                        }
                songs_meta['uid'] = uploader_uid

                return PlaylistResult(
                    type='collection',
                    cache_id=str(playlist_id),
                    extra={'uid': str(uploader_uid)},
                    title=str(list_title),
                    song_ids=song_ids,
                    songs_meta=songs_meta)
            else:
                logger.warning(f'未知合集类型: {collection_info.get("id")} type={collection_info.get("season_type")} from {bvid}')

        # 分P视频
        if len(video_data['pages']) > 1:
            logger.debug(f'找到分P视频 {bvid}')
            song_ids, songs_meta = [], {}
            for p, page in enumerate(video_data['pages'], start=1):
                song_ids.append(f'{bvid}_p{p}')
                songs_meta[f'{bvid}_p{p}'] = {
                    'title': page['part'],
                    'duration': page['duration'],
                }

            return PlaylistResult(
                type='multipart',
                cache_id=str(bvid),
                extra={},
                title=str(video_data['title']),
                song_ids=song_ids,
                songs_meta=songs_meta)

        raise ValueError(f'bvid={bvid} is neither a collection nor a multi-page video')

    async def _fetch_collection_playlist(self, parsed_url: ParsedPlaylistUrl) -> PlaylistResult:
        list_id = parsed_url.cache_id
        uid = parsed_url.extra['uid']
        logger.debug(f'获取合集列表 {list_id}')
        rsp = await self._request_json(
            'GET', 'https://api.bilibili.com/x/polymer/web-space/seasons_archives_list',
            params={'mid': uid, 'season_id': list_id, 'page_num': 1, 'page_size': 30},
            headers={'Referer': f'https://space.bilibili.com/{uid}/lists/{list_id}?type=season'})

        if rsp['code'] != 0:
            raise ValueError(f'Failed to get collection list for {list_id} ({rsp.get("code")}): {rsp.get("message")}')

        return await self._fetch_playlist_from_bvid(ParsedPlaylistUrl('', rsp['data']['archives'][0]['bvid'], {}))

    async def _fetch_series_playlist(self, parsed_url: ParsedPlaylistUrl) -> PlaylistResult:
        list_id = parsed_url.cache_id
        uid = parsed_url.extra['uid']
        song_ids, songs_meta = [], {}

        for pn in itertools.count(1):
            logger.debug(f'获取系列列表 {list_id}, pn={pn}')
            rsp = await self._request_json('GET', 'https://api.bilibili.com/x/series/archives', params={
                'mid': uid, 'series_id': list_id, 'only_normal': 'true', 'sort': 'desc', 'pn': pn, 'ps': 30},
                headers={'Referer': f'https://space.bilibili.com/{uid}/lists/{list_id}?type=series'})
            if rsp['code'] != 0:
                raise ValueError(f'Failed to get series list for {list_id} ({rsp.get("code")}): {rsp.get("message")}')

            for entry in rsp['data']['archives']:
                song_ids.append(entry['bvid'])
                songs_meta[entry['bvid']] = {
                    'title': entry['title'],
                    'duration': entry['duration'],
                }

            if rsp['data']['page']['num'] * rsp['data']['page']['size'] >= rsp['data']['page']['total']:
                break
            await asyncio.sleep(3)

        meta_rsp = await self._request_json(
            'GET', f'https://api.bilibili.com/x/series/series?series_id={list_id}',
            headers={'Referer': f'https://space.bilibili.com/{uid}/lists/{list_id}?type=series'})

        return PlaylistResult(
            type='series',
            cache_id=str(list_id),
            extra={'uid': uid},
            title=str(meta_rsp.get('data', {}).get('meta', {}).get('name')),
            song_ids=song_ids,
            songs_meta=songs_meta)

    async def _fetch_fav_playlist(self, parsed_url: ParsedPlaylistUrl) -> PlaylistResult:
        list_id = parsed_url.cache_id
        song_ids, songs_meta = [], {}
        last_avid = ''

        page_meta = await self._request_json('GET', 'https://api.bilibili.com/x/v1/medialist/info',
                                             params={'type': 3, 'biz_id': list_id, 'tid': 0},
                                             headers={'Referer': f'https://www.bilibili.com/list/ml{list_id}'})
        title = page_meta['data']['title']
        total = page_meta['data']['media_count']

        ps = 20
        for _ in range(100):
            rsp = await self._request_json(
                'GET', 'https://api.bilibili.com/x/v2/medialist/resource/list', params={
                    'mobi_app': 'web',
                    'type': 3,
                    'biz_id': list_id,
                    'oid': last_avid,
                    'otype': 2,
                    'ps': ps,
                    'direction': 'false',
                    'desc': 'true',
                    'sort_field': 1,
                    'tid': 0,
                    'with_current': 'false'},
                headers={'Referer': f'https://www.bilibili.com/list/ml{list_id}'})

            if rsp['code'] != 0:
                raise ValueError(f'Failed to get favorite list for {list_id} ({rsp.get("code")}): {rsp.get("message")}')

            for entry in rsp['data'].get('media_list') or []:
                if len(entry['pages']) > 1:
                    for p, page in enumerate(entry['pages'], start=1):
                        song_ids.append(f'{entry["bv_id"]}_p{p}')
                        songs_meta[f'{entry["bv_id"]}_p{p}'] = {
                            'title': f'{page["title"]} - {entry["title"]}',
                            'duration': page['duration'],
                            'singer': entry['upper']['name'],
                        }
                else:
                    song_ids.append(entry['bv_id'])
                    songs_meta[entry['bv_id']] = {
                        'title': entry['title'],
                        'duration': entry['duration'],
                        'singer': entry['upper']['name'],
                    }
                last_avid = entry['id']

            if not rsp['data'].get('has_more') or not rsp['data'].get('media_list'):
                break
            if isinstance(total, int) and len(song_ids) >= total:
                break
            await asyncio.sleep(3)

        return PlaylistResult(
            type='favorite',
            cache_id=str(list_id),
            extra={},
            title=title,
            song_ids=song_ids,
            songs_meta=songs_meta,
        )

    async def save_updated_playlist(self, playlist: PlaylistInfo):
        if match := re.search(r'/(?P<uid>\d+)/channel/seriesdetail?sid=(?P<list_id>\d+)', playlist.url):
            entry = await PlaylistCacheEntry.save_playlist(
                self.key, 'series', match.group('list_id'),
                title=str(playlist.title),
                song_ids=playlist.song_ids,
                songs_meta=playlist.songs_meta)
            return entry.as_playlist_info(playlist.url, self.key)
        elif match := re.search(r'/(?P<uid>\d+)/favlist\?(?:.*&)?fid=(?P<list_id>\d+)', playlist.url):
            entry = await PlaylistCacheEntry.save_playlist(
                self.key, 'favorite', match.group('list_id'),
                title=str(playlist.title),
                song_ids=playlist.song_ids,
                songs_meta=playlist.songs_meta)
            return entry.as_playlist_info(playlist.url, self.key)
        else:
            logger.warning(f'Expected series or favorite playlist, got playlist with url: {playlist.url}')

    def _parse_playlist_url(self, url: str) -> ParsedPlaylistUrl | None:
        if match := re.search(rf'^(?:https?://)?www\.bilibili\.com/video/{self.BVID_PATTERN}', url):
            return ParsedPlaylistUrl('multipart', match.group('bvid'), {})

        for pattern in [
            r'^(?:https?://)?space\.bilibili\.com/(?P<uid>\d+)/channel/collectiondetail\?(?:.*&)?sid=(?P<list_id>\d+)',
            r'^(?:https?://)?space\.bilibili\.com/(?P<uid>\d+)/lists/(?P<list_id>\d+)\?(?:.*&)?type=season\b',
        ]:
            if match := re.search(pattern, url):
                return ParsedPlaylistUrl('collection', match.group('list_id'), {'uid': match.group('uid')})

        for pattern in [
            r'^(?:https?://)?space\.bilibili\.com/(?P<uid>\d+)/channel/seriesdetail\?(?:.*&)?sid=(?P<list_id>\d+)',
            r'^(?:https?://)?www\.bilibili\.com/medialist/play/(?P<uid>\d+)\?(?:.*&)?business_id=(?P<list_id>\d+)',
            r'^(?:https?://)?www\.bilibili\.com/list/(?P<uid>\d+)\?(?:.*&)?sid=(?P<list_id>\d+)',
            r'^(?:https?://)?space\.bilibili\.com/(?P<uid>\d+)/lists/(?P<list_id>\d+)\?(?:.*&)?type=series\b',
        ]:
            if match := re.search(pattern, url):
                return ParsedPlaylistUrl('series', match.group('list_id'), {'uid': match.group('uid')})

        for pattern in [
            r'^(?:https?://)?space\.bilibili\.com/(?P<uid>\d+)/favlist\?(?:.*&)?fid=(?P<list_id>\d+)',
            r'^(?:https?://)?www\.bilibili\.com/medialist/play/ml(?P<list_id>\d+)',
            r'^(?:https?://)?www\.bilibili\.com/list/ml(?P<list_id>\d+)',
        ]:
            if match := re.search(pattern, url):
                return ParsedPlaylistUrl('favorite', match.group('list_id'), {})

    def _to_playlist_url(self, parsed: ParsedPlaylistUrl | PlaylistResult) -> str:
        if parsed.type == 'multipart':
            return f'https://www.bilibili.com/video/{parsed.cache_id}'
        elif parsed.type == 'series':
            return f'https://space.bilibili.com/{parsed.extra["uid"]}/lists/{parsed.cache_id}?type=series'
        elif parsed.type == 'collection':
            return f'https://space.bilibili.com/{parsed.extra["uid"]}/lists/{parsed.cache_id}?type=season'
        elif parsed.type == 'favorite':
            return f'https://www.bilibili.com/list/ml{parsed.cache_id}'
        else:
            raise ValueError(f'Unknown playlist type for {parsed}')

    async def playlist_from_url(self, url: str, refresh: bool = False) -> PlaylistInfo | None:
        if match := self._parse_playlist_url(url):
            if not refresh:
                if cached := await self._load_playlist_cache(match):
                    return cached
            handlers: dict[str, typing.Callable[[ParsedPlaylistUrl], typing.Coroutine[typing.Any, typing.Any, PlaylistResult]]] = {
                'multipart': self._fetch_playlist_from_bvid,
                'series': self._fetch_series_playlist,
                'collection': self._fetch_collection_playlist,
                'favorite': self._fetch_fav_playlist,
            }
            result = await handlers[match.type](match)
            return await self._save_playlist_cache(result)

    async def user_playlists(self) -> list[tuple[str, str]]:
        return []

    def match_song_id(self, query: str) -> str | None:
        query = query.strip()
        if re.match(rf'{self.BVID_PATTERN}(?:_p\d+)?', query):
            return query
        if match := re.search(rf'www\.bilibili\.com/video/{self.BVID_PATTERN}', query):
            if part := re.search(r'(?:^|&)p=(?P<part>\d+)', query.split('?')[-1]):
                return f'{match.group("bvid")}_p{part.group("part")}'
            return match.group('bvid')
        return None
