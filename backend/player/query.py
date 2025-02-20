from __future__ import annotations
import asyncio
import typing
import logging

from ..db import QueryEntry, SongInfo
from .events import SearchingEvent, QueryLoadingEvent, QueryFailEvent, QuerySuccessEvent


logger = logging.getLogger('player.query')


class PlayerQuery:
    def __init__(self, player: Player, user: UserInfo, query_text: str):
        self._player = player
        self._user = user
        self._query_text = query_text
        self._db_entry: asyncio.Future[QueryEntry] = asyncio.Future()
        self._searching_dispatched = False
        self._loading_dispatched = False
        self._failed_dispatched = False
        self._success_dispatched = False

        self._keywords, self.api = self._parse_query(query_text)
        asyncio.create_task(self._init())

    @property
    def user(self) -> UserInfo:
        return self._user

    @property
    def raw_query(self) -> str:
        return self._query_text

    @property
    def keywords(self) -> str:
        return self._keywords

    @property
    def source(self) -> str | None:
        return self.api.key if self.api else None

    async def _init(self):
        self._db_entry.set_result(await QueryEntry.new_query(self._user, self.raw_query))

    def _parse_query(self, query_text: str) -> tuple[str, API | None]:
        keywords = query_text.strip()
        for key, api in [
            ('网易云音乐', self._player._downloader._netease),
            ('网易云', self._player._downloader._netease),
            ('QQ音乐', self._player._downloader._qqmusic)
        ]:
            if key in query_text:
                keywords = keywords.replace(key, '').strip()
                return keywords, api
        return keywords, None

    def increment_search_count(self, count: int):
        async def _increment():
            await (await self._db_entry).increment_match_count(count)
        asyncio.create_task(_increment())

    def _update_result(self, result_or_song_info: SongInfo | str, additional_info: str | None = None):
        async def _update():
            if isinstance(result_or_song_info, SongInfo):
                await (await self._db_entry).set_result(result_or_song_info)
            else:
                await (await self._db_entry).set_failed(result_or_song_info, additional_info)
        asyncio.create_task(_update())

    def dispatch_searching(self):
        if not self._searching_dispatched:
            self._searching_dispatched = True
            self._player.dispatch(SearchingEvent(
                user=self._user,
                query=self.raw_query,
                keywords=self.keywords,
                source=self.source,
            ))
        else:
            logger.warning(f'忽略发送过的dispatch_searching事件：{self.raw_query}')

    def dispatch_loading(self):
        if not self._loading_dispatched and not self._success_dispatched and not self._failed_dispatched:
            self._loading_dispatched = True
            self._player.dispatch(QueryLoadingEvent(
                user=self._user,
                query=self.raw_query,
                keywords=self.keywords,
                source=self.source,
            ))

    def dispatch_failed(self, reason: typing.Literal['keyword-banned', 'failed', 'already-queued', 'no-resource'] = 'failed', additional_info: str | None = None):
        if not self._failed_dispatched:
            self._failed_dispatched = True
            self._player.dispatch(QueryFailEvent(
                user=self._user,
                query=self.raw_query,
                keywords=self.keywords,
                source=self.source,
                reason=reason,
            ))
            self._update_result(reason, additional_info)
        else:
            logger.warning(f'忽略发送过的dispatch_failed事件：{self.raw_query}')

    def dispatch_success(self, song_info: SongInfo):
        if not self._success_dispatched:
            self._success_dispatched = True
            self._player.dispatch(QuerySuccessEvent(
                user=self._user,
                query=self.raw_query,
                keywords=self.keywords,
                source=self.source,
                song=song_info,
            ))
            self._update_result(song_info)
        else:
            logger.warning(f'忽略发送过的dispatch_success事件：{self.raw_query}')


if typing.TYPE_CHECKING:
    from .player import Player, API, UserInfo
