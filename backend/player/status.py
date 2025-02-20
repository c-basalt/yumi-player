from __future__ import annotations
import asyncio
import typing

from ..db import PlayerStatus


class PlayerStatusWrapper:
    def __init__(self, player: Player):
        self._player = player
        self._entry: PlayerStatus | None = None
        self.reported_volume: float | None = None

    async def init(self):
        self._entry = await PlayerStatus.get_status()

    @property
    def _current_song(self) -> PlaylistEntry | None:
        return self._player._playlist.current_entry

    @property
    def paused(self) -> bool:
        return self._entry.paused if self._entry else False

    @paused.setter
    def paused(self, value: bool):
        if self._entry and self._entry.paused != bool(value):
            self._entry.paused = bool(value)
            asyncio.create_task(self._entry.save(update_fields=['paused']))

    @property
    def progress(self) -> int:
        return self._current_song.progress if self._current_song else 0

    @progress.setter
    def progress(self, value: int):
        if self._current_song:
            if self._current_song.progress != int(value):
                self._current_song.progress = int(value)
                asyncio.create_task(self._current_song.save(update_fields=['progress']))

    def as_dict(self) -> dict:
        return {
            'paused': self.paused,
            'progress': self.progress,
            'volume': self.reported_volume,
        }


if typing.TYPE_CHECKING:
    from ..player import Player
    from ..db import PlaylistEntry
