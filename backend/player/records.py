from __future__ import annotations
import typing
import collections
import logging
import asyncio
import dataclasses
import datetime

import aiohttp.web

from ..db import RecentBvidEntry, PlaylistEntry, QueryEntry


def _combine_tasks(tasks: typing.Iterable[asyncio.Task]):
    async def _resolve():
        for task in tasks:
            await task
    return asyncio.create_task(_resolve())


class RecentBvid:
    def __init__(self, player: Player):
        self._player = player
        self._recent_bvid: collections.deque[tuple[UserInfo, str]] = collections.deque()
        self._recent_bvid_meta: dict[str, SongMeta] = {}
        self._logger = logging.getLogger('player.recent_bvid')
        self._meta_task_lock = asyncio.Lock()

    @property
    def num_limit(self) -> int:
        return self._player._config.recent_bvid_limit

    async def init(self):
        self._recent_bvid.extend(await RecentBvidEntry.get_recent_bvid(self.num_limit))
        asyncio.create_task(RecentBvidEntry.discard_old_bvid(self.num_limit))
        asyncio.create_task(self._fetch_meta())

    async def _fetch_meta(self):
        async with self._meta_task_lock:
            for bvid in {bvid for _, bvid in self._recent_bvid} - set(self._recent_bvid_meta):
                try:
                    self._recent_bvid_meta[bvid] = await self._player._downloader.get_single_meta(
                        self._player._downloader._bilibili, bvid)
                    self._player.dispatch_status()
                except Exception:
                    self._logger.exception(f'BV号元数据缓存失败：{bvid}')
            for bvid in set(self._recent_bvid_meta) - {bvid for _, bvid in self._recent_bvid}:
                self._recent_bvid_meta.pop(bvid, None)

    async def record_bvid(self, user: UserInfo, bvid: str):
        self._recent_bvid.appendleft((user, bvid))
        while len(self._recent_bvid) > self.num_limit:
            self._recent_bvid.pop()
        self._player.dispatch_status()
        await RecentBvidEntry.add_entry(bvid, user)
        await self._fetch_meta()

    def _get_meta_data(self, bvid: str) -> dict | None:
        if meta := self._recent_bvid_meta.get(bvid):
            return dataclasses.asdict(meta)

    def as_list(self):
        return [
            {'bvid': bvid, 'user': dataclasses.asdict(user), 'meta': self._get_meta_data(bvid)}
            for user, bvid in self._recent_bvid
        ]


class PlayerPlaylist:
    def __init__(self, player: Player):
        self._player = player
        self._playlist: list[PlaylistEntry] = []
        self._logger = logging.getLogger('player.playlist')
        self._commit_pos_lock = asyncio.Lock()

    async def init(self):
        self._playlist = await PlaylistEntry.get_queued_entries()
        self._playlist.sort(key=lambda x: x.queue_position)

    async def _commit_pos(self, entries: list[PlaylistEntry]):
        async with self._commit_pos_lock:
            return await PlaylistEntry.bulk_update(entries, fields=['queue_position'])

    @property
    def _main_queue(self) -> list[PlaylistEntry]:
        return [entry for entry in self._playlist if not entry.is_fallback]

    @property
    def _fallback_queue(self) -> list[PlaylistEntry]:
        return [entry for entry in self._playlist if entry.is_fallback]

    @property
    def current_entry(self) -> PlaylistEntry | None:
        if self._main_queue:
            return self._main_queue[0]
        elif self._fallback_queue:
            return self._fallback_queue[0]
        return None

    def get_next_position(self) -> int:
        return max((entry.queue_position for entry in self._playlist), default=0) + 1

    @property
    def all_song_info(self) -> list[SongInfo]:
        return [entry.to_songinfo() for entry in self._playlist]

    @property
    def pending_main_entries(self) -> list[PlaylistEntry]:
        return self._main_queue[1:]

    @property
    def is_empty(self) -> bool:
        return not self._playlist

    @staticmethod
    def as_dict_entry(entry: PlaylistEntry) -> dict:
        return {
            'id': entry.id,
            'progress': entry.progress,
            'is_fallback': entry.is_fallback,
            'is_from_control': entry.is_from_control,
            'user': dataclasses.asdict(entry.to_user()),
            'music': dataclasses.asdict(entry.to_songinfo()),
        }

    @property
    def status(self) -> dict:
        return {
            'current': self.as_dict_entry(self.current_entry) if self.current_entry else None,
            'playlist': [self.as_dict_entry(entry) for entry in self._main_queue],
            'fallback': [self.as_dict_entry(entry) for entry in self._fallback_queue],
            'combined_list': [self.as_dict_entry(entry) for entry in self._playlist],
        }

    def _on_list_update(self):
        if self._player._config.clear_playing_fallback:
            if self.current_entry and self.current_entry.is_fallback:
                self.current_entry.is_fallback = False
                asyncio.create_task(self.current_entry.save(update_fields=['is_fallback']))

        self._player.dispatch_status()

    def get_queued_entry(self, song_info: SongInfo) -> PlaylistEntry | None:
        for entry in self._playlist:
            if entry.song_id == song_info.id and entry.song_source == song_info.source:
                return entry
        return None

    def is_queued(self, song_info: SongInfo) -> bool:
        return any(song_info.id == queued.id and song_info.source == queued.source for queued in self.all_song_info)

    def add_song(self, user: UserInfo, song_info: SongInfo,
                 is_auto_entry: bool, is_from_control: bool, is_fallback: bool) -> asyncio.Task[PlaylistEntry]:
        entry = PlaylistEntry.create_entry(
            user, song_info, position=self.get_next_position(),
            is_auto_entry=is_auto_entry, is_from_control=is_from_control, is_fallback=is_fallback)
        self._playlist.append(entry)
        # dispatch after saved and got pk id
        return asyncio.create_task(entry.new_entry_save(callback=self._on_list_update))

    def _find_entry(self, entry_id: int) -> PlaylistEntry | None:
        for entry in self._playlist:
            if entry.id == entry_id:
                return entry

    def _move_entry_pos(self, entry_id: int, new_pos: int) -> asyncio.Task[int | None]:
        """Move an entry to a new position in the playlist, pushing back entries beginning from `new_pos`"""
        if not (entry := self._find_entry(entry_id)):
            self._logger.warning(f'未找到要移动到位置{new_pos}的条目：ID {entry_id}')
            return asyncio.create_task(asyncio.sleep(0))
        to_update = [e for e in self._playlist if e.queue_position >= new_pos]
        for i, _after_entry in enumerate(to_update, start=1):
            _after_entry.queue_position = new_pos + i
        entry.queue_position = new_pos
        to_update.append(entry)
        self._playlist.sort(key=lambda x: x.queue_position)
        self._on_list_update()
        return asyncio.ensure_future(self._commit_pos(to_update))

    def reorder_entries(self, ordered_entry_ids: list[int]) -> asyncio.Task[int]:
        self._logger.info(f'重新排序条目：{ordered_entry_ids}')
        for new_pos, entry_id in enumerate(ordered_entry_ids, start=1):
            if entry := self._find_entry(entry_id):
                entry.queue_position = new_pos
        for new_pos, entry in enumerate(self._playlist, start=(new_pos + 1)):
            if entry.id not in ordered_entry_ids:
                entry.queue_position = new_pos
        self._playlist.sort(key=lambda x: x.queue_position)
        self._on_list_update()
        return asyncio.ensure_future(self._commit_pos(self._playlist))

    def move_to_end(self, entry_id: int) -> asyncio.Task[int | None]:
        self._logger.info(f'将条目{entry_id}移至末尾')
        return self._move_entry_pos(entry_id, self.get_next_position())

    def move_down(self, entry_id: int) -> asyncio.Task[int | None]:
        if not (entry := self._find_entry(entry_id)):
            self._logger.warning(f'未找到要后移的条目：ID {entry_id}')
            return asyncio.create_task(asyncio.sleep(0))
        next_pos = next((e.queue_position for e in self._playlist
                         if e.queue_position > entry.queue_position and e.is_fallback == entry.is_fallback), None)
        if next_pos is None:
            self._logger.warning('没有后续待播，无法后移')
            return asyncio.create_task(asyncio.sleep(0))
        return self._move_entry_pos(entry_id, next_pos + 1)

    def move_to_top(self, entry_id: int) -> asyncio.Task[int | None]:
        self._logger.info(f'将条目{entry_id}移至开始')
        if not self.current_entry:
            self._logger.warning('无播放条目，忽略前移操作')
        elif not (entry := self._find_entry(entry_id)):
            self._logger.warning(f'未找到要移至开始的条目：ID {entry_id}')
        else:
            if entry.is_fallback and not self.current_entry.is_fallback:
                return self._move_entry_pos(entry_id, min([entry.queue_position for entry in self._fallback_queue]))
            else:
                return self._move_entry_pos(entry_id, self.current_entry.queue_position + 1)
        return asyncio.create_task(asyncio.sleep(0))

    def remove_played_entry(self, entry_id: int) -> asyncio.Task[None]:
        return asyncio.create_task(self._remove_entry(entry_id, canceled=False))

    def remove_canceled_entry(self, entry_id: int) -> asyncio.Task[None]:
        return asyncio.create_task(self._remove_entry(entry_id, canceled=True))

    async def _remove_entry(self, entry_id: int, canceled: bool):
        if entry := self._find_entry(entry_id):
            self._playlist.remove(entry)
            self._on_list_update()
            if canceled:
                await entry.set_canceled()
            else:
                await entry.set_played()
        else:
            self._logger.warning(f'未找到ID={entry_id}的条目从队列移除')

    def promote_from_fallback(self, entry_id: int, user: UserInfo) -> asyncio.Task[None]:
        tasks = []

        if entry := self._find_entry(entry_id):
            entry.is_fallback = False
            if entry.to_user().privilege == 'owner' and entry.to_user().username == '':
                entry.set_user(user)
                entry.created_at = datetime.datetime.now(datetime.timezone.utc)
            self._on_list_update()
            tasks.append(asyncio.create_task(entry.save()))
            if self.current_entry and entry.queue_position < self.current_entry.queue_position:
                tasks.append(self._move_entry_pos(entry_id, self.current_entry.queue_position + 1))
        else:
            self._logger.warning(f'未找到ID={entry_id}的条目取消后备')

        return _combine_tasks(tasks)

    def update_is_fallback(self, entry_id: int, is_fallback: bool) -> asyncio.Task[None]:
        if entry := self._find_entry(entry_id):
            entry.is_fallback = is_fallback
            self._on_list_update()
            return asyncio.create_task(entry.save(update_fields=['is_fallback']))
        else:
            self._logger.warning(f'未找到ID={entry_id}的条目修改后备')
            return asyncio.create_task(asyncio.sleep(0))


async def handle_get_playlist_history(request: aiohttp.web.Request):
    total, entries = await PlaylistEntry.get_past_history_entries(
        page_num=int(request.query['page_num']),
        size=int(request.query['size']),
        hide_canceled=bool(request.query.get('hide_canceled', None)),
        filter=request.query.get('filter', ''))
    return aiohttp.web.json_response(
        status=200, data={
            'total': total,
            'filter': request.query.get('filter', ''),
            'data': [{
                'user': dataclasses.asdict(entry.to_user()),
                'song': dataclasses.asdict(entry.to_songinfo()),
                'progress': entry.progress,
                'created_at': entry.created_at.timestamp(),
                'canceled': entry.is_canceled,
            } for entry in entries]})


async def handle_get_query_history(request: aiohttp.web.Request):
    page_num = int(request.query['page_num'])
    size = int(request.query['size'])
    return aiohttp.web.json_response(
        status=200, data={
            'total': await QueryEntry.get_history_count(),
            'data': [{
                'query_text': entry.query_text,
                'user': dataclasses.asdict(entry.to_user()),
                'song': dataclasses.asdict(entry.to_songinfo()),
                'created_at': entry.created_at.timestamp(),
                'result': entry.result,
                'match_count': entry.match_count,
            } for entry in await QueryEntry.get_history_entries(page_num, size)]})


if typing.TYPE_CHECKING:
    from .player import Player
    from ..db import SongMeta, UserInfo, SongInfo
