import dataclasses
from typing import Literal

from ..db import UserInfo, SongInfo


@dataclasses.dataclass
class BaseEvent:
    user: UserInfo

    def asdict(self) -> dict:
        return {
            'type': self.event_key(),
            **dataclasses.asdict(self),
        }

    @classmethod
    def event_key(cls) -> str:
        assert cls.__name__.endswith('Event')
        name = cls.__name__[:-len('Event')]
        return '-'.join(''.join(' ' + c.lower() if c.isupper() else c for c in name).split())


@dataclasses.dataclass
class QueryBaseEvent(BaseEvent):
    query: str
    keywords: str
    source: str | None


@dataclasses.dataclass
class SearchingEvent(QueryBaseEvent):
    pass


@dataclasses.dataclass
class QueryLoadingEvent(QueryBaseEvent):
    pass


@dataclasses.dataclass
class QuerySuccessEvent(QueryBaseEvent):
    song: SongInfo


@dataclasses.dataclass
class QueryFailEvent(QueryBaseEvent):
    reason: Literal['keyword-banned', 'failed', 'already-queued', 'no-resource']


@dataclasses.dataclass
class RequestFailEvent(BaseEvent):
    query: str
    reason: Literal['request-rate-limit', 'success-rate-limit']


@dataclasses.dataclass
class CancelFailEvent(BaseEvent):
    id: int | None
    reason: Literal['no-match']


@dataclasses.dataclass
class CancelSuccessEvent(BaseEvent):
    id: int
    title: str


@dataclasses.dataclass
class SkipFailEvent(BaseEvent):
    id: int | None
    reason: Literal['no-playing', 'not-user', 'use-startcmd']


@dataclasses.dataclass
class SkipSuccessEvent(BaseEvent):
    id: int
    title: str
