from __future__ import annotations
import typing
import re
import os
import json
import asyncio
import urllib.parse
import dataclasses
import time
import logging
import hashlib
import random
import collections
import functools

import aiohttp
import aiohttp.web
import aiofiles.os
import aiohttp_socks


from ..api import BilibiliAPI, NeteaseMusicAPI, QQMusicAPI
from ..api.common import SearchResult
from ..db import PlaylistEntry, SongInfo, UserInfo, CacheEntry, BannedUserCache, QueryEntry
from ..cookies import BilibiliCookieLoader, NeteaseMusicCookieLoader, QQMusicCookieLoader
from ..config import DataConfig, create_aiohttp_session

from .events import RequestFailEvent, CancelFailEvent, CancelSuccessEvent, SkipFailEvent, SkipSuccessEvent
from .commands import PausedCmd, SeekCmd, ProgressCmd, CancelCmd, StatusCmd, ShowEventCmd, NextCmd, MoveToEndCmd, MoveToTopCmd, MoveDownCmd, SetIsFallbackCmd, UnsetIsFallbackCmd, VolumeReportCmd, player_commands
from .bilibili_api import fetch_bili_uname, fetch_recent_users
from .decibel import get_decibel
from .exceptions import KeywordBannedError, NoQueryMatchError, NoPlayurlError
from .query import PlayerQuery
from .records import RecentBvid, PlayerPlaylist, handle_get_playlist_history, handle_get_query_history
from .status import PlayerStatusWrapper
from .unshield import unshield, UnsheildRuleConfig


def handle_option(func):
    @functools.wraps(func)
    async def wrapper(self, request: aiohttp.web.Request):
        if request.method == 'OPTIONS':
            return aiohttp.web.Response(status=200)
        return await func(self, request)
    return wrapper


@dataclasses.dataclass
class PlayerBannedConfig(DataConfig):
    banned_uids: tuple[int | str, ...] = ()
    banned_keywords: tuple[str, ...] = ()

    def validate(self, key: str, value: typing.Any):
        if key == 'banned_uids':
            return tuple(int(uid) for uid in collections.OrderedDict.fromkeys(str(uid) for uid in value) if uid.isdigit())
        if key == 'banned_keywords':
            return tuple(collections.OrderedDict.fromkeys(str(w).lower() for w in value))
        return value

    @property
    def banned_users(self) -> list[UserInfo]:
        return [UserInfo(int(uid), '', '', 'user') for uid in self.banned_uids if isinstance(uid, int) or uid.isdigit()]

    @property
    def banned_keywords_lowercase(self) -> list[str]:
        return [str(w).lower() for w in self.banned_keywords]


@dataclasses.dataclass
class PlayerConfig(DataConfig):
    request_handler_off: bool = False
    clear_playing_fallback: bool = True
    request_cmd: str = '点歌'
    cancel_cmd: str = '取消点歌'
    skip_cmd: str = '切歌'
    skipend_cmd: str = '跳过当前'
    target_db: int = -40
    rate_limit_request: int = 2
    rate_limit_success_count: int = 10
    rate_limit_success_duration: int = 60
    query_history_count_limit: int = 100
    recent_bvid_limit: int = 10
    cache_limit_mb: int = 5000
    cache_basedir: str = 'music_cache'
    cache_proxy: str | None = None

    def validate(self, key: str, value: typing.Any):
        if key == 'cache_basedir':
            value = os.path.basename(str(value))
            if value in ['', '.', '..', 'db.sqlite3', 'config.json', 'logs', 'yumi_player.exe']:
                return None
        if key == 'cache_proxy':
            parsed = urllib.parse.urlparse(str(value))
            if not re.match(r'^(https?|socks[45]?)$', parsed.scheme) or not parsed.hostname:
                return None
        if key == 'cache_limit_mb':
            return max(500, int(value))
        return value


class Player:
    def __init__(self, server: Server):
        self._server = server
        self._logger = logging.getLogger('player')
        self._app = aiohttp.web.Application()

        self._config = PlayerConfig.create_sub(server.config, 'player')
        self._banned_config = PlayerBannedConfig.create_sub(server.config, 'player_banned')
        self._unshield_config = UnsheildRuleConfig.create_sub(server.config, 'player_unshield')

        self._playlist = PlayerPlaylist(self)
        self._player_status = PlayerStatusWrapper(self)
        self._recent_bvid = RecentBvid(self)
        self._downloader = MusicDownloader(self)
        self._fallback = FallbackLists(self)

        self._ws_clients: set[aiohttp.web.WebSocketResponse] = set()
        self._last_ws_sent = 0
        self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
        self._last_requested: dict[int | str, float] = {}

        self._app.router.add_route('GET', '/ws', self.ws_handler)
        self._app.router.add_route('GET', '/file', self._downloader.serve_file_handler)
        self._app.router.add_route('GET', '/fallback/ws_info', self._fallback.ws_info_handler)
        self._app.router.add_route('*', '/fallback/lists', self._fallback.handle_playlist_url_change)
        self._app.router.add_route('*', '/fallback/refresh', self._fallback.handle_playlist_refresh)
        self._app.router.add_route('GET', '/recent_users', self.handle_recent_users)
        self._app.router.add_route('GET', '/play_history', handle_get_playlist_history)
        self._app.router.add_route('GET', '/query_history', handle_get_query_history)
        self._app.router.add_route('*', '/banned_user', self.handle_add_banned_user)
        self._app.router.add_route('*', '/add_bvid', self.handle_add_bvid)
        self._app.router.add_route('*', '/manual_search', self.handle_manual_search)
        self._app.router.add_route('*', '/manual_add', self.handle_manual_add)
        self._app.router.add_route('GET', '/user_playlists', self._downloader.user_playlists_handler)
        self._app.router.add_route('GET', '/test_proxy', self._downloader.handle_test_proxy)
        self._app.router.add_route('*', '/sort_playlist', self.handle_sort_playlist)
        self._app.router.add_route('*', '/unsheild', self.handle_unsheild_test)
        server.add_subapp('/player', self._app)

    async def init(self):
        await self._playlist.init()
        await self._player_status.init()
        await self._recent_bvid.init()
        await self._downloader.init()
        await self._fallback.init()
        await QueryEntry.discard_old_queries(self._config.query_history_count_limit)

    async def _heartbeat_worker(self):
        while True:
            await asyncio.sleep(2)
            if time.time() - self._last_ws_sent > 1.5:
                self.dispatch_status()

    async def close(self):
        self._heartbeat_task.cancel()
        await asyncio.gather(
            self._downloader.close(),
            *[ws.close() for ws in self._ws_clients],
        )

    @property
    def owner_user(self):
        return UserInfo(self._server.room_uid or 0, '', '', 'owner')

    @property
    def status(self):
        return {
            'cached_songs': [dataclasses.asdict(song) for song in self._fallback.cached_song_list],
            'config': self._config.as_dict(recursive=False, exclude_keys=['cache_proxy', 'cache_basedir', 'cache_limit_mb']),
            'recent_bvid': self._recent_bvid.as_list(),
            **self._playlist.status,
            **self._player_status.as_dict(),
        }

    def _handle_player_command(self, command: BaseCmd):
        """Handle a player command"""
        try:
            if not isinstance(command, (StatusCmd, ProgressCmd)):
                self._logger.debug(f'处理播放器命令：{command}')

            if isinstance(command, PausedCmd):
                self._player_status.paused = bool(command.value)
            elif isinstance(command, NextCmd):
                if entry := self._playlist.current_entry:
                    if command.value == entry.id:
                        self._player_status.progress = 0
                        self._player_status.reported_volume = None
                        self._playlist.remove_played_entry(entry.id)
                    else:
                        self._logger.warning(f'id={command.value} 与当前播放歌曲不匹配，忽略next命令')
            elif isinstance(command, MoveToEndCmd):
                self._playlist.move_to_end(command.value)
            elif isinstance(command, MoveToTopCmd):
                self._playlist.move_to_top(command.value)
            elif isinstance(command, MoveDownCmd):
                self._playlist.move_down(int(command.value))
            elif isinstance(command, (SeekCmd, ProgressCmd)):
                self._player_status.progress = int(command.value)
            elif isinstance(command, CancelCmd):
                self._playlist.remove_canceled_entry(int(command.value))
            elif isinstance(command, SetIsFallbackCmd):
                self._playlist.update_is_fallback(command.value, True)
            elif isinstance(command, UnsetIsFallbackCmd):
                self._playlist.update_is_fallback(command.value, False)
            elif isinstance(command, VolumeReportCmd):
                self._player_status.reported_volume = float(command.value)
            elif isinstance(command, (ShowEventCmd, StatusCmd)):
                pass
            else:
                self._logger.warning(f'未知命令：{command}')
        except Exception:
            self._logger.exception(f'处理命令时出错：{command}')

        self.check_playlist_empty()

        data = {'command': command.asdict(), 'status': self.status}

        if not isinstance(command, (StatusCmd, ProgressCmd)):
            self._logger.debug(f'发送命令{command.type}处理后状态: {data["status"]}')
        self._last_ws_sent = time.time()
        asyncio.ensure_future(asyncio.gather(*[ws.send_json(data) for ws in self._ws_clients]))

    async def ws_handler(self, request: aiohttp.web.Request):
        ws = aiohttp.web.WebSocketResponse(heartbeat=10, receive_timeout=15)
        await ws.prepare(request)
        try:
            self._ws_clients.add(ws)
            await ws.send_json({'status': self.status})
            async for msg in ws:
                if not msg.type == aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    cmd_dict = json.loads(msg.data)
                    self._handle_player_command(
                        player_commands[cmd_dict['cmd']](cmd_dict.get('value', None)))
                except KeyError:
                    self._logger.error(f'未知命令{cmd_dict}，可用命令: {player_commands.keys()}')
                except Exception:
                    self._logger.exception('客户端ws消息解析错误')
        finally:
            self._ws_clients.discard(ws)
        return ws

    def dispatch(self, event: BaseEvent):
        """Dispatch a player event"""
        self._handle_player_command(ShowEventCmd(event))

    def dispatch_status(self):
        self._handle_player_command(StatusCmd())

    def handle(self, msg):
        """handler of danmaku server messages"""
        try:
            if msg.get('cmd') == 'DANMU_MSG':
                self._handle_danmu_msg(msg['info'])
            elif msg.get('cmd') == 'SUPER_CHAT_MESSAGE':
                self._handle_superchat(msg['data'])
        except Exception:
            self._logger.exception(f'弹幕服务器消息处理失败: {msg}')

    def _handle_danmu_msg(self, info):
        msg = info[1].strip()
        user = self._make_userinfo(info[2][0], info[0][7], info[2][1], info[2][2])
        self._logger.debug(f'收到"{user.summary}"的弹幕: {msg}')
        self._handle_message_danmaku(user, str(msg))

    def _handle_superchat(self, data):
        msg = data['message'].strip()
        user = self._make_userinfo(data['uid'], '', data['user_info']['uname'], data['user_info']['manager'])
        self._logger.debug(f'收到"{user.summary}"的SC: {msg}')
        self._handle_message_danmaku(user, str(msg))

    def _make_userinfo(self, uid, uid_hash, username, is_admin):
        user = UserInfo(
            uid=int(uid or 0),
            uid_hash=str(uid_hash or ''),
            username=str(username),
            privilege='admin' if bool(is_admin) else 'user',
        )
        if user == self.owner_user:
            user.privilege = 'owner'
        return user

    def _handle_message_danmaku(self, user: UserInfo, msg: str):
        commands = {
            self._config.request_cmd: self._handle_query,
            self._config.cancel_cmd: self._handle_cancel,
            self._config.skip_cmd: self._handle_skip,
            self._config.skipend_cmd: self._handle_skip,
        }

        for match in re.findall(BilibiliAPI.BVID_PATTERN, msg):
            self._logger.info(f'从"{user.summary}"的弹幕匹配BV号 {match}')
            asyncio.create_task(self._recent_bvid.record_bvid(user, match))

        msg = msg.strip()
        msg_cmd = next(iter(msg.split()), None)
        if not (handler := next((h for cmd, h in commands.items() if cmd and cmd == msg_cmd), None)):
            return

        if self._config.request_handler_off:
            self._logger.debug(f'指令未启用，忽略"{user.summary}"的消息: "{msg}"')
            return

        if (banned := next((b for b in self._banned_config.banned_users if user == b), None)):
            self._logger.info(f'拒绝黑名单用户"{user.username}"(UID: {banned.uid})的指令')
            return
        self._logger.info(f'处理"{user.summary}"的弹幕指令: {msg}')

        asyncio.create_task(handler(user, msg))

    async def _check_rate_limit(self, user: UserInfo) -> typing.Literal['request-rate-limit', 'success-rate-limit'] | None:
        """Check if the user is rate limited, return the reason if limited, otherwise None"""
        if self._last_requested.get(user.uid or user.uid_hash, 0) + self._config.rate_limit_request > time.time():
            return 'request-rate-limit'

        history = await PlaylistEntry.get_user_history_entries(
            user.uid_hash,
            limit=self._config.rate_limit_success_count
        )
        if len(history) >= self._config.rate_limit_success_count:
            oldest_allowed_time = time.time() - self._config.rate_limit_success_duration
            oldest_entry = history[-1]  # Last entry is oldest due to -id ordering
            if oldest_entry.created_at.timestamp() > oldest_allowed_time:
                return 'success-rate-limit'

    def _check_keyword_banned(self, query_or_title: str) -> str | None:
        '''Check if the query or title contains any banned keywords, return the keyword if found otherwise None'''
        query_or_title = query_or_title.lower()
        for keyword in self._banned_config.banned_keywords_lowercase:
            if keyword in query_or_title:
                return keyword
        return None

    def unsheild(self, text: str) -> str:
        return unshield(text, self._unshield_config)

    async def _handle_query(self, user: UserInfo, msg: str):
        query_text = self.unsheild(msg[len(self._config.request_cmd):].strip())

        if limit_reason := await self._check_rate_limit(user):
            return self.dispatch(RequestFailEvent(user, query_text, limit_reason))
        self._last_requested[user.uid] = self._last_requested[user.uid_hash] = time.time()

        try:
            query = PlayerQuery(self, user, query_text)
            await self._downloader.handle_query(query)
        except KeywordBannedError as e:
            self._logger.info(f'含黑名单关键词，拒绝点歌"{query_text}": {e}')
            query.dispatch_failed('keyword-banned', str(e))
        except Exception:
            self._logger.exception(f'"{user.summary}"的点歌失败: {query_text}')
            query.dispatch_failed()

    async def _handle_cancel(self, user: UserInfo, msg: str):
        if msg != self._config.cancel_cmd:
            return
        for entry in reversed(self._playlist.pending_main_entries):
            if user == entry.to_user():
                self._handle_player_command(CancelCmd(entry.id))
                self.dispatch(CancelSuccessEvent(user, entry.id, entry.song_title))
                return
        self.dispatch(CancelFailEvent(user, None, 'no-match'))

    async def _handle_skip(self, user: UserInfo, msg: str):
        if msg != self._config.skip_cmd and msg != self._config.skipend_cmd:
            return
        if not (entry := self._playlist.current_entry):
            return self.dispatch(SkipFailEvent(user, None, 'no-playing'))

        if entry.to_user() != user and user.privilege != 'owner':
            return self.dispatch(SkipFailEvent(user, entry.id, 'not-user'))
        if self._player_status.progress < 30 and msg == self._config.skipend_cmd:
            return self.dispatch(SkipFailEvent(user, entry.id, 'use-startcmd'))
        self._handle_player_command(NextCmd(entry.id))
        self.dispatch(SkipSuccessEvent(user, entry.id, entry.song_title))

    async def add_song(self, user: UserInfo, song_info: SongInfo, query: PlayerQuery | None,
                       is_auto_entry: bool = False, is_from_control: bool = False, is_fallback: bool = False):
        if entry := self._playlist.get_queued_entry(song_info):
            if not is_fallback and entry.is_fallback and entry.id != getattr(self._playlist.current_entry, 'id', None):
                self._logger.info(f'将后备歌曲 "{song_info.title}" ({song_info.id}) 改为正常队列')
                await self._playlist.promote_from_fallback(entry.id, user)
                if query:
                    query.dispatch_success(song_info)
                return
            else:
                self._logger.info(f'歌曲 "{song_info.title}" ({song_info.id}) 已在队列中，拒绝添加请求 ')
                if query:
                    query.dispatch_failed('already-queued')
                return

        self._logger.info(f'添加 "{song_info.title} / {song_info.singer}" ({song_info.source}: {song_info.id}) 到播放列表' + ("（自动播放）" if is_auto_entry else f'，由"{user.summary}"添加'))
        await self._playlist.add_song(user, song_info, is_auto_entry, is_from_control, is_fallback)

        if query:
            query.dispatch_success(song_info)
        self._downloader.remove_oversized_cache()
        self._logger.debug(f'当前播放列表 ({len(self._playlist._playlist)}) {self._playlist._playlist}')

    def check_playlist_empty(self):
        if self._playlist.is_empty:
            asyncio.create_task(self._add_fallback_song())

    async def _add_fallback_song(self):
        """Add a random song from fallback playlists when main playlist is empty"""
        try:
            if not self._playlist.is_empty:
                return
            if song := self._fallback.get_random_song():
                self._logger.debug(f'空置时自动添加歌曲 {song.title} / {song.singer}')
                await self.add_song(self.owner_user, song, None, is_auto_entry=True, is_fallback=True)
        except Exception:
            self._logger.exception("后备歌曲添加失败")

    async def _fetch_recent_users(self) -> list[UserInfo]:
        recent_users: collections.OrderedDict[str, UserInfo] = collections.OrderedDict()

        for user_list in await asyncio.gather(
            PlaylistEntry.get_recent_users(),
            fetch_recent_users(self._server.roomid, self._server.room_uid or 0)
        ):
            for user in user_list:
                recent_users[str(user.uid)] = user
        recent_users.pop(str(self._server.room_uid), None)
        return list(recent_users.values())

    async def handle_recent_users(self, request: aiohttp.web.Request):
        recent_users = await self._fetch_recent_users()
        return aiohttp.web.json_response(status=200, data=[
            dataclasses.asdict(user) for user in recent_users])

    async def _get_banned_usernames(self) -> dict[int, str]:
        uids = [user.uid for user in self._banned_config.banned_users]
        if not uids:
            return {}
        users = await BannedUserCache.get_banned_users(uids)
        for uid in set(uids) - set(users):
            if username := await fetch_bili_uname(uid):
                users[uid] = await BannedUserCache.save_banned_user(uid, username)
            else:
                break
        return {user.uid: user.username for user in users.values()}

    async def handle_add_banned_user(self, request: aiohttp.web.Request):
        if request.method == 'POST':
            data = await request.json()
            uid, username = int(data['uid']), data.get('username')

            if username:
                await BannedUserCache.save_banned_user(uid, username)
            else:
                if cached := await BannedUserCache.get_banned_username(uid, expired_days=3):
                    username = cached
                else:
                    if username := await fetch_bili_uname(uid):
                        await BannedUserCache.save_banned_user(uid, username)
            self._banned_config.banned_uids = (*self._banned_config.banned_uids, uid)
        return aiohttp.web.json_response(status=200, data=(await self._get_banned_usernames()))

    @handle_option
    async def handle_add_bvid(self, request: aiohttp.web.Request):
        data = await request.json()
        user = UserInfo(**data['user'])
        song_info = await self._downloader.get_single(self._downloader._bilibili, data['bvid'])
        if self._playlist.is_queued(song_info):
            return aiohttp.web.json_response(status=200, data={'error': '已在播放队列中'})
        await self.add_song(user, song_info, None, is_auto_entry=False, is_from_control=True)
        return aiohttp.web.json_response(status=200, data={})

    @handle_option
    async def handle_manual_search(self, request: aiohttp.web.Request):
        query = (await request.json())['query']

        for api in self._downloader.apis:
            if match_id := api.match_song_id(query):
                song_meta = await self._downloader.get_single_meta(api, match_id)
                return aiohttp.web.json_response(status=200, data={
                    api.key: [dataclasses.asdict(SearchResult(
                        id=song_meta.id,
                        title=song_meta.title,
                        singer=song_meta.singer,
                        meta=song_meta.meta
                    ))]
                })

        async def _query(api: API):
            try:
                return api.key, await api.search(query)
            except Exception:
                self._logger.exception(f'从{api.key}搜索"{query}"失败')
                return api.key, []

        return aiohttp.web.json_response(status=200, data={
            api_key: [dataclasses.asdict(song) for song in result]
            for api_key, result in await asyncio.gather(*[_query(api) for api in self._downloader.apis])
        })

    @handle_option
    async def handle_manual_add(self, request: aiohttp.web.Request):
        data = await request.json()
        source, song_id = data['source'], data['song_id']
        if data.get('user'):
            user = UserInfo(**data['user'])
        else:
            user = self.owner_user
        is_fallback = bool(data.get('is_fallback'))
        if not (api := next((api for api in self._downloader.apis if api.key == source), None)):
            return aiohttp.web.json_response(data={
                'error': f'Unknown source: {source}, must be one of {[api.key for api in self._downloader.apis]}'})
        try:
            song_info = await self._downloader.get_single(api, song_id, check_keyword=False)
        except NoPlayurlError:
            self._logger.info(f'未找到{source}: {song_id}的播放地址')
            return aiohttp.web.json_response(data={'error': '无法获取歌曲下载链接'})
        except Exception:
            self._logger.exception(f'从{source}获取歌曲信息失败: {song_id}')
            return aiohttp.web.json_response(data={'error': '歌曲信息获取失败'})
        if self._playlist.is_queued(song_info):
            self._logger.info(f'歌曲"{song_info.title} / {song_info.singer}"已在播放列表中，拒绝添加')
            return aiohttp.web.json_response(data={
                'error': f'"{song_info.title} / {song_info.singer}"已在播放队列中'})
        await self.add_song(user, song_info, None, is_auto_entry=False, is_from_control=True, is_fallback=is_fallback)
        return aiohttp.web.json_response(status=200, data={})

    @handle_option
    async def handle_sort_playlist(self, request: aiohttp.web.Request):
        data = await request.json()
        await self._playlist.reorder_entries(data)
        return aiohttp.web.json_response(status=200, data={})

    @handle_option
    async def handle_unsheild_test(self, request: aiohttp.web.Request):
        text = (await request.json())['text']
        return aiohttp.web.json_response(status=200, data={'text': self.unsheild(text)})


class FallbackList:
    _RETRY_TIMEOUT = 3600
    _logger = logging.getLogger('player.fallback_list')

    def __init__(self, lists: FallbackLists, api: API, playlist_info: PlaylistInfo):
        self._lists = lists
        self._api = api
        self._playlist_info = playlist_info
        self._recent_chosen: set[str] = set()
        self._last_chosen: str | None = None
        self._cached_next: SongInfo | None = None
        self._failed_to_load: dict[str, float] = {}
        self._load_later_task: asyncio.Task | None = None

    async def close(self):
        if self._load_later_task:
            self._load_later_task.cancel()
            await self._load_later_task

    @classmethod
    async def from_url(cls, lists: FallbackLists, url: str, refresh: bool = False, try_redirect: bool = True) -> 'FallbackList':
        for api in lists._player._downloader.apis:
            if playlist_info := await api.playlist_from_url(url, refresh):
                cls._logger.info(f'从{api.key}加载播放列表: {playlist_info.title}')
                cls._logger.debug(f'播放列表项目: {playlist_info.song_ids}')
                playlist = cls(lists, api, playlist_info)
                asyncio.create_task(playlist.load_random_next())
                return playlist
        if try_redirect:
            async with lists._player._downloader._session.get(url) as resp:
                if url != str(resp.url):
                    cls._logger.info(f'尝试检查重定向的链接是否为播放列表: {str(resp.url)}')
                    return await cls.from_url(lists, str(resp.url), refresh, try_redirect=False)
        raise ValueError(f"No API found that can handle URL: {url}")

    @property
    def url(self) -> str:
        return self._playlist_info.url

    @property
    def cached_next(self) -> SongInfo | None:
        return self._cached_next

    @property
    def failed_count(self) -> int:
        return len(self._failed_to_load)

    @property
    def songs_count(self) -> int:
        assert self._playlist_info is not None, 'playlist info not loaded'
        return len(self._playlist_info.song_ids)

    @property
    def all_failed(self) -> bool:
        return len(self._failed_to_load) == len(self._playlist_info.song_ids)

    def _check_bilibili_multipart(self, bvid: str, song_info: SongInfo):
        """Check within the list for update for a validated song_info"""
        playlist = self._playlist_info
        if not isinstance(self._api, BilibiliAPI):
            return
        try:
            index = playlist.song_ids.index(bvid)
            playlist.song_ids.remove(bvid)
        except ValueError:
            return

        self._logger.info(f'更新从播放列表 {playlist.url} 中找到B站分P信息: {bvid}')
        for p, page in enumerate(song_info.meta['part'], start=1):
            playlist.song_ids.insert(index, f'{bvid}_p{p}')
            playlist.songs_meta[f'{bvid}_p{p}'] = {
                'title': page['part'],
                'duration': page['duration'],
            }
            index += 1

        asyncio.create_task(self._api.save_updated_playlist(playlist))

    def _shuffle_song_id(self) -> str | None:
        '''Return a random valid song id from the playlist and record the choice, return None if no valid song'''
        assert self._playlist_info is not None, 'playlist info not loaded'
        valid_ids = set(self._playlist_info.song_ids) - set(self._failed_to_load)
        if not valid_ids:
            return None
        unchosen = valid_ids - self._recent_chosen
        if not unchosen:
            self._recent_chosen.clear()
            unchosen = (valid_ids - {self._last_chosen}) or valid_ids

        song_id = random.choice(list(unchosen))
        self._last_chosen = song_id
        self._recent_chosen.add(song_id)
        return song_id

    def _purge_expired_failed(self):
        for song_id, value in list(self._failed_to_load.items()):
            if value + self._RETRY_TIMEOUT < time.time():
                self._failed_to_load.pop(song_id)

    def _load_next_later(self, sleep=600):
        async def __load_later():
            try:
                await asyncio.sleep(sleep)
                self._load_later_task = None
                asyncio.create_task(self.load_random_next())
            except asyncio.CancelledError:
                pass
        self._load_later_task = asyncio.create_task(__load_later())

    async def load_random_next(self):
        assert self._playlist_info is not None, 'playlist info must be loaded first'
        self._purge_expired_failed()
        self._cached_next = None
        for _ in range(len(self._playlist_info.song_ids) - len(self._failed_to_load)):
            if not (song_id := self._shuffle_song_id()):
                self._logger.warning(f'后备播放列表中没有有效歌曲: {self._playlist_info.title}')
                self._load_next_later()
                return
            try:
                self._logger.info(f'为播放列表预加载歌曲 {self._api.key}={song_id}: {self._playlist_info.title}')
                self._cached_next = await self._lists._player._downloader.get_single(self._api, song_id)
                asyncio.create_task(self._lists.broadcast_playlist_info())
                self._lists._player.check_playlist_empty()
                return
            except Exception as e:
                self._failed_to_load[song_id] = time.time()
                asyncio.create_task(self._lists.broadcast_playlist_info())
                self._logger.warning(
                    f'歌曲预加载失败{self._api.key}-{song_id}: {self._playlist_info.title}',
                    exc_info=(not isinstance(e, NoPlayurlError)))
        self._logger.warning(f'{self._api.key}的播放列表全部预加载失败: {self._playlist_info.title}')
        self._load_next_later()


@dataclasses.dataclass
class FallbackConfig(DataConfig):
    playlists: typing.Tuple[str, ...] = ()
    disabled_urls: typing.Tuple[str, ...] = ()

    def validate(self, key: str, value: typing.Any):
        if key in ['playlists', 'disabled_urls']:
            value = tuple(collections.OrderedDict.fromkeys(value))
        return value


class FallbackLists:
    def __init__(self, player: Player):
        self._player = player
        self._logger = logging.getLogger('player.fallbacks')
        self._config = FallbackConfig.create_sub(player._config, 'fallback')
        self._playlists: collections.OrderedDict[str, FallbackList] = collections.OrderedDict()
        self._recent_chosen: set[str] = set()
        self._last_chosen: str | None = None
        self._info_clients: set[aiohttp.web.WebSocketResponse] = set()

    async def init(self):
        for url in self._config.playlists:
            try:
                await self._load_list(str(url))
                asyncio.create_task(self.broadcast_playlist_info())
            except Exception:
                self._logger.exception(f'后备播放列表加载失败: {url}')

    async def close(self):
        asyncio.ensure_future(asyncio.gather(
            *[playlist.close() for playlist in self._playlists.values()],
            *[ws.close() for ws in self._info_clients]))

    async def ws_info_handler(self, request: aiohttp.web.Request):
        ws = aiohttp.web.WebSocketResponse(heartbeat=10, receive_timeout=15)
        await ws.prepare(request)
        try:
            self._info_clients.add(ws)
            await self.broadcast_playlist_info()
            async for msg in ws:
                pass
        finally:
            self._info_clients.discard(ws)
        return ws

    async def broadcast_playlist_info(self):
        """Send playlist info to all connected WebSocket clients"""
        if not self._info_clients:
            return

        await asyncio.gather(*[
            ws.send_json({
                url: {
                    'info': dataclasses.asdict(playlist._playlist_info),
                    'api': playlist._api.key,
                    'failed_count': playlist.failed_count
                }
                for url, playlist in self._playlists.items() if playlist._playlist_info is not None
            }) for ws in self._info_clients])

    async def _load_list(self, url: str, refresh: bool = False):
        playlist = await FallbackList.from_url(self, url, refresh=refresh)
        self._playlists[playlist.url] = playlist
        return playlist

    @property
    def cached_song_list(self) -> list[SongInfo]:
        return [playlist.cached_next for playlist in self._playlists.values() if playlist.cached_next]

    def check_bilibili_multipart(self, song_info: SongInfo):
        """Check for update for all fallback playlists"""
        if song_info.source != 'Bilibili':
            return
        if not song_info.meta.get('part') or len(song_info.meta['part']) <= 1:
            return
        bvid = song_info.id.split('_p')[0]
        for playlist in self._playlists.values():
            playlist._check_bilibili_multipart(bvid, song_info)

    def get_random_song(self) -> SongInfo | None:
        cached_songs = [(playlist, playlist.cached_next)
                        for playlist in self._playlists.values() if playlist.cached_next and playlist.url not in self._config.disabled_urls]
        if not cached_songs:
            if [playlist for playlist in self._playlists.values() if not playlist.all_failed]:
                self._logger.info('后备播放列表中没有加载好的歌曲')
            return None

        unplayed = [(playlist, song) for playlist, song in cached_songs
                    if song.composite_id not in self._recent_chosen]
        if not unplayed:
            self._recent_chosen.clear()
            unplayed = cached_songs

        weights = [playlist.songs_count - playlist.failed_count for playlist, _ in unplayed]
        playlist, song = random.choices(unplayed, weights=weights, k=1)[0]
        self._recent_chosen.add(song.composite_id)
        asyncio.create_task(playlist.load_random_next())

        return song

    async def add_playlist_url(self, url: str):
        url = url.replace('music.163.com/#/', 'music.163.com/')
        playlist = await self._load_list(url, refresh=True)
        self._playlists.move_to_end(playlist.url, last=False)  # move to top
        self._config.playlists = tuple(self._playlists)
        asyncio.create_task(self.broadcast_playlist_info())

    async def remove_playlist_url(self, url: str):
        if removed_list := self._playlists.pop(url, None):
            asyncio.create_task(removed_list.close())
        self._config.playlists = tuple(self._playlists)  # save changed playlists
        asyncio.create_task(self.broadcast_playlist_info())

    async def refresh_playlist_cache(self, url: str):
        try:
            await self._load_list(url, refresh=True)
            asyncio.create_task(self.broadcast_playlist_info())
        except Exception:
            self._logger.exception(f"播放列表缓存刷新失败: {url}")

    async def handle_playlist_url_change(self, request: aiohttp.web.Request):
        self._logger.debug(f'已缓存的列表: {self._playlists}')
        self._logger.debug(f'已缓存的歌曲: {self.cached_song_list}')
        if request.method == 'POST':
            data = await request.json()
            if data['cmd'] == 'add':
                try:
                    await self.add_playlist_url(data['url'])
                except Exception as e:
                    self._logger.exception(f'播放列表添加失败: {data["url"]}')
                    return aiohttp.web.json_response(status=500, data={'error': str(e)})
            elif data['cmd'] == 'remove':
                try:
                    await self.remove_playlist_url(data['url'])
                except ValueError as e:
                    self._logger.exception(f'播放列表移除失败: {data["url"]}')
                    return aiohttp.web.json_response(status=400, data={'error': str(e)})
            elif data['cmd'] == 'disable':
                if data['url'] in self._playlists:
                    self._config.disabled_urls = (*self._config.disabled_urls, data['url'])
                    asyncio.create_task(self.broadcast_playlist_info())
            elif data['cmd'] == 'enable':
                self._config.disabled_urls = tuple(
                    url for url in self._config.disabled_urls if url != data['url'])
                asyncio.create_task(self.broadcast_playlist_info())
        return aiohttp.web.json_response(status=200, data={
            'playlists': list(self._playlists),
            'disabled': self._config.disabled_urls,
        })

    @handle_option
    async def handle_playlist_refresh(self, request: aiohttp.web.Request):
        try:
            await self.refresh_playlist_cache((await request.json())['url'])
            return aiohttp.web.json_response(status=200, data={})
        except Exception as e:
            return aiohttp.web.json_response(status=500, data={'error': str(e)})


class MusicDownloader:
    def __init__(self, player: Player) -> None:
        self._player = player
        self._logger = logging.getLogger('player.downloader')
        self._session = create_aiohttp_session(headers={
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
        })
        self._bilibili = BilibiliAPI(self._request, self._cookies_getter(BilibiliCookieLoader))
        self._qqmusic = QQMusicAPI(self._request, self._cookies_getter(QQMusicCookieLoader))
        self._netease = NeteaseMusicAPI(self._request, self._cookies_getter(NeteaseMusicCookieLoader))
        self._cache_worker_task = asyncio.create_task(self._remove_oversized_cache())
        self._cache_worker_pending = asyncio.Event()

    def _cookies_getter(self, loader_class: type[CookieLoader]) -> CookiesGetter:
        def _getter():
            return self._player._server.cookies.get_cookies(loader_class._key())
        return _getter

    async def init(self):
        await self.check_invalid_records()
        self.remove_oversized_cache()

    async def close(self):
        self._cache_worker_task.cancel()
        await self._session.close()

    @property
    def apis(self) -> list[API]:
        return [self._bilibili, self._qqmusic, self._netease]

    @property
    def basedir(self):
        '''cache directory from config'''
        basedir = os.path.basename(self._player._config.cache_basedir)
        os.makedirs(basedir, exist_ok=True)
        return basedir

    async def _get_decibel(self, filename: str) -> float | None:
        return await get_decibel(self._to_cache_path(filename))

    def _to_cache_path(self, filename):
        return os.path.join(self.basedir, os.path.basename(filename))

    def _is_valid_entry(self, entry: CacheEntry):
        return os.path.isfile(self._to_cache_path(entry.song_file))

    async def _delete_entry_and_file(self, entry: CacheEntry):
        try:
            if self._is_valid_entry(entry):
                await aiofiles.os.remove(self._to_cache_path(entry.song_file))
                await entry.delete()
                self._logger.info(f'已删除缓存文件: {entry.song_file}')
            else:
                await entry.update_valid(False)
                self._logger.info(f'缓存文件不存在，标记为失效: {entry.song_file}')
        except Exception:
            self._logger.exception(f'缓存删除失败: {entry.song_file}')

    async def get_total_cache_size(self):
        return (await CacheEntry.get_total_size()) / (1024 ** 2)

    async def check_invalid_records(self):
        async for entry in CacheEntry.all():
            await entry.update_valid(self._is_valid_entry(entry))

    async def _remove_oversized_cache(self):
        while True:
            await self._cache_worker_pending.wait()
            try:
                for entry in await CacheEntry.get_entries_by_access():
                    _total_cache = await self.get_total_cache_size()
                    self._logger.debug(f'缓存大小: {_total_cache:.2f} MiB/{self._player._config.cache_limit_mb} MiB')
                    if _total_cache < self._player._config.cache_limit_mb:
                        break

                    for song in self._player._playlist.all_song_info:
                        if os.path.basename(song.filename) == os.path.basename(entry.song_file):
                            return

                    for song in self._player._fallback.cached_song_list:
                        if os.path.basename(song.filename) == os.path.basename(entry.song_file):
                            return

                    self._logger.info(f'缓存大小达到限制，删除缓存文件: {entry.song_file}')
                    await self._delete_entry_and_file(entry)

            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception:
                self._logger.exception('清除超出的缓存时出错')
            finally:
                self._cache_worker_pending.clear()

    def remove_oversized_cache(self):
        self._cache_worker_pending.set()

    async def handle_test_proxy(self, request: aiohttp.web.Request):
        if not self._player._config.cache_proxy:
            return aiohttp.web.json_response(data={'success': False, 'reason': 'no-proxy'})
        try:
            headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61'}
            async with aiohttp_socks.ProxyConnector.from_url(self._player._config.cache_proxy) as connector:
                async with aiohttp.request('GET', 'https://www.bilibili.com/video/BV1GJ411x7h7/', headers=headers,
                                           connector=connector, timeout=aiohttp.ClientTimeout(total=5)) as rsp:
                    if 'Never Gonna Give You Up' in await rsp.text():
                        return aiohttp.web.json_response(data={'success': True, 'reason': ''})
                    return aiohttp.web.json_response(data={'success': False, 'reason': 'geo-restricted'})
        except asyncio.TimeoutError:
            return aiohttp.web.json_response(data={'success': False, 'reason': 'connection-timeout'})
        except Exception:
            self._logger.exception('代理测试失败')
            return aiohttp.web.json_response(data={'success': False, 'reason': 'proxy-error'})

    async def _request(self, method: str, url: str, data: bytes | None = None, params: dict | None = None,
                       headers: dict | None = None, cookies: Cookies | None = None, proxy: str | None = None):
        if not proxy or proxy.startswith('http://'):
            async with self._session.request(method, url, params=params, data=data, headers=headers, cookies=cookies, proxy=proxy) as rsp:
                if rsp.status == 200:
                    return await rsp.content.read()
                raise ValueError(f'{rsp.status} {rsp.reason}')
        else:
            headers = {**(headers or {}), 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61'}
            async with aiohttp_socks.ProxyConnector.from_url(proxy) as connector:
                async with aiohttp.request(method, url, params=params, data=data, headers=headers,
                                           cookies=cookies, connector=connector) as rsp:
                    if rsp.status == 200:
                        return await rsp.content.read()
                    raise ValueError(f'{rsp.status} {rsp.reason}')

    async def get_single_meta(self, api: API, song_id: str) -> SongMeta:
        if cache_entry := await CacheEntry.get_cache_entry(api, song_id):
            return cache_entry.to_songinfo().as_meta()

        self._logger.info(f'从{api.key}获取歌曲元信息: {song_id}')
        song_info = await api.songinfo(song_id, proxy=self._player._config.cache_proxy)
        cache_entry = await CacheEntry.save_new_meta_entry(
            api,
            song_id,
            song_source=api.key,
            song_title=song_info.title,
            song_singer=song_info.singer or '',
            song_meta=song_info.meta
        )
        self._logger.info(f'从{api.key}保存歌曲元信息: {cache_entry.song_title} ({song_id})')
        return cache_entry.to_songinfo().as_meta()

    async def _get_single_cache(self, api: API, song_id: str, check_keyword: bool = True) -> CacheEntry | None:
        if not (cache_entry := await CacheEntry.get_cache_entry(api, song_id)):
            return
        if check_keyword and (banned_keyword := self._player._check_keyword_banned(cache_entry.song_title)):
            raise KeywordBannedError(f'{banned_keyword} ({cache_entry.song_title})')
        if not await cache_entry.update_valid(self._is_valid_entry(cache_entry)):
            return
        if not cache_entry.file_size == os.stat(self._to_cache_path(cache_entry.song_file)).st_size:
            self._logger.warning(f'缓存文件大小不匹配: {cache_entry.song_file}，可能文件已损坏')
            await self._delete_entry_and_file(cache_entry)
            return
        if cache_entry.song_decibel is None:
            if decibel := await self._get_decibel(cache_entry.song_file):
                await cache_entry.update_decibel(decibel)
        asyncio.ensure_future(cache_entry.update_access())
        return cache_entry

    async def _get_single(self, api: API, song_id: str,
                          query: PlayerQuery | None = None, check_keyword: bool = True) -> SongInfo:
        if cache_entry := await self._get_single_cache(api, song_id, check_keyword=check_keyword):
            return cache_entry.to_songinfo()

        self._logger.info(f'从{api.key}获取歌曲信息: {song_id}')
        song_info = await api.songinfo(song_id, proxy=self._player._config.cache_proxy)
        if check_keyword and (banned_keyword := self._player._check_keyword_banned(song_info.title)):
            raise KeywordBannedError(f'{banned_keyword} ({song_info.title})')

        self._logger.info(f'正在从{api.key}下载歌曲: "{song_info.title}" ({song_id})')
        if query:
            query.dispatch_loading()
        async with self._session.get(song_info.url, headers=song_info.headers) as r:
            if r.status != 200:
                raise ValueError(f'Failed to download music file, status={r.status}')
            content = await r.content.read()

        # use hash of song_id to avoid filename conflict due to case-insensitive filesystem
        name_prefix = f'{api.key}-{song_id}-{hashlib.md5(song_id.encode()).hexdigest()[:8]}'
        filename = f'{name_prefix}-{os.path.basename(urllib.parse.urlparse(song_info.url).path)}'
        filename = re.sub(r'\.m4s$', '.m4a', filename)

        entry = await CacheEntry.save_cache_entry(
            api,
            song_id,
            song_source=api.key,
            song_file=filename,
            song_title=song_info.title,
            song_singer=song_info.singer or '',
            song_decibel=None,
            song_duration=song_info.meta.pop('duration', None),
            song_meta={**song_info.meta, 'size': len(content)},
            file_size=len(content)
        )

        async with aiofiles.open(self._to_cache_path(entry.song_file), 'wb') as f:
            await f.write(content)

        await entry.update_decibel(await self._get_decibel(entry.song_file))
        self._logger.info(f'歌曲从{api.key}缓存完成: "{entry.song_title}" ({entry.song_id})')
        return entry.to_songinfo()

    async def get_single(self, api: API, song_id: str,
                         query: PlayerQuery | None = None, check_keyword: bool = True) -> SongInfo:
        song_info = await self._get_single(api, song_id, query, check_keyword)
        self._player._fallback.check_bilibili_multipart(song_info)
        return song_info

    async def get_from_query(self, api: API, query_text: str, query_obj: PlayerQuery | None = None) -> SongInfo:
        results = await api.search(query_text)
        self._logger.debug(f'{api.key}搜索结果: {results}')
        if not results:
            raise NoQueryMatchError(api.key)
        if query_obj:
            query_obj.increment_search_count(len(results))
        for result in results:
            try:
                return await self.get_single(api, result.id, query_obj)
            except (KeywordBannedError, asyncio.CancelledError):
                raise
            except NoPlayurlError:
                self._logger.debug(f'未从{api.key}找到 "{result.title}" ({result.id}) 的播放链接')
            except Exception as e:
                self._logger.debug(f'从{api.key}获取歌曲信息失败: {str(e)[:100]}')
        raise NoPlayurlError(api.key)

    async def handle_query(self, query: PlayerQuery):
        query.dispatch_searching()
        if banned_keyword := self._player._check_keyword_banned(query.keywords):
            await asyncio.sleep(random.uniform(0.5, 1.5))
            raise KeywordBannedError(f'{banned_keyword} ({query.keywords})')

        api_list: list[API] = [self._qqmusic, self._netease] if not query.api else [query.api]

        for api in api_list:
            if match_id := api.match_song_id(query.keywords):
                self._logger.debug(f'匹配到ID，直接获取单曲: {match_id}')
                try:
                    song = await self.get_single(api, match_id, query)
                    return await self._player.add_song(query.user, song, query)
                except KeywordBannedError:
                    raise
                except Exception as e:
                    query.dispatch_failed('no-resource')
                    self._logger.debug(f'从{api.key}获取匹配ID的歌曲信息时失败: {str(e)[:100]}')
                    return None

        pending = [self.get_from_query(api, query.keywords, query) for api in api_list]
        errors = []
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    songinfo_result = task.result()
                    [task.cancel() for task in pending]
                    return await self._player.add_song(query.user, songinfo_result, query)
                except KeywordBannedError:
                    raise
                except Exception as e:
                    errors.append(e)
                    if isinstance(e, NoQueryMatchError):
                        self._logger.debug(f'没有从{e}找到匹配结果: "{query}"')
                    elif isinstance(e, NoPlayurlError):
                        self._logger.debug(f'未从{e}找到"{query}"的播放链接')
                    else:
                        self._logger.exception('查找歌曲时出错')
        query.dispatch_failed('no-resource')
        if all(isinstance(e, NoQueryMatchError) for e in errors):
            self._logger.info(f'"{query.user.summary}"的请求没有匹配结果: "{query}"')
        else:
            self._logger.info(f'"{query.user.summary}"的请求没有歌曲资源: "{query}"')

    async def user_playlists_handler(self, request: aiohttp.web.Request):
        all_playlists = {}
        for api in self.apis:
            try:
                if playlists := await api.user_playlists():
                    all_playlists[api.key] = [dataclasses.asdict(data) for data in playlists]
            except Exception:
                self._logger.exception(f'从{api.key}获取用户播放列表时出错')
        return aiohttp.web.json_response(status=200, data=all_playlists)

    async def serve_file_handler(self, request: aiohttp.web.Request):
        filepath = self._to_cache_path(request.query['path'])
        if not os.path.isfile(filepath):
            return aiohttp.web.Response(status=404)

        return aiohttp.web.FileResponse(filepath)


if typing.TYPE_CHECKING:
    from ..main import Server
    from ..db import SongMeta
    from ..api.common import API, PlaylistInfo, CookiesGetter, Cookies
    from ..cookies.loaders import CookieLoader
    from .events import BaseEvent
    from .commands import BaseCmd
