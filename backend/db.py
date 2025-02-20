from __future__ import annotations
import os
import dataclasses
import time
import typing
import functools
import asyncio

import tortoise
import tortoise.fields
import tortoise.models
import tortoise.functions
import tortoise.transactions
import tortoise.exceptions
from tortoise.expressions import Q, Subquery

from .config import get_basedir


CRC32_TABLE = [0] * 256
for i in range(256):
    crc = i
    for _ in range(8):
        if crc & 1:
            crc = (crc >> 1) ^ 0xEDB88320
        else:
            crc >>= 1
        CRC32_TABLE[i] = crc


@dataclasses.dataclass
class UserInfo:
    uid: int
    uid_hash: str
    username: str
    privilege: typing.Literal['owner'] | typing.Literal['admin'] | typing.Literal['user'] = 'user'

    def __post_init__(self):
        if self.uid != 0 and not self.uid_hash:
            self.uid_hash = self._generate_hash_from_uid(self.uid)

    @staticmethod
    @functools.lru_cache(maxsize=1024)
    def _generate_hash_from_uid(uid: int) -> str:
        crc = 0xFFFFFFFF
        for byte in str(uid).encode():
            crc = (crc >> 8) ^ CRC32_TABLE[(crc & 0xFF) ^ byte]
        return f"{crc ^ 0xFFFFFFFF:08x}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UserInfo):
            return False
        if self.uid and other.uid:
            return self.uid == other.uid
        if self.uid_hash and other.uid_hash:
            return self.uid_hash == other.uid_hash
        return False

    @property
    def summary(self) -> str:
        if self.uid:
            if not self.username and self.privilege == 'owner':
                return f'主播 ({self.uid})'
            else:
                return f'{self.username or "???"} ({self.uid})'
        return f'{self.username or "???"}'


@dataclasses.dataclass
class SongInfo:
    id: str
    title: str
    singer: str
    source: str
    filename: str
    decibel: float | None
    duration: int | None
    meta: dict = dataclasses.field(default_factory=dict)

    @property
    def composite_id(self) -> str:
        return f'{self.source}-{self.id}'

    def as_meta(self) -> SongMeta:
        return SongMeta(
            id=self.id,
            title=self.title,
            singer=self.singer,
            source=self.source,
            duration=self.duration,
            meta=self.meta,
        )


@dataclasses.dataclass
class SongMeta:
    id: str
    title: str
    singer: str
    source: str
    duration: int | None
    meta: dict = dataclasses.field(default_factory=dict)

    @property
    def composite_id(self) -> str:
        return f'{self.source}-{self.id}'


@dataclasses.dataclass
class PlaylistInfo:
    url: str
    title: str
    api_key: str
    song_ids: list[str]
    songs_meta: dict[str, dict]


TORTOISE_CONFIG = {
    'connections': {'default': 'sqlite://db.sqlite3'},
    'apps': {
        'models': {
            'models': ['backend.db', 'aerich.models'],
            'default_connection': 'default',
        },
    },
}


def get_migrations_path():
    return os.path.join(get_basedir(), 'migrations')


class Database:
    _initialized = False
    _init_lock = asyncio.Lock()

    @classmethod
    async def init(cls):
        async with cls._init_lock:
            if cls._initialized:
                return

            await tortoise.Tortoise.init(
                db_url=TORTOISE_CONFIG['connections']['default'],
                modules={'models': TORTOISE_CONFIG['apps']['models']['models']}
            )

            # Initialize and run migrations using Aerich
            from aerich import Command
            command = Command(
                tortoise_config=TORTOISE_CONFIG,
                location=get_migrations_path()
            )
            # Create migration tables if they don't exist
            await command.init()
            # Apply all pending migrations
            await command.upgrade(run_in_transaction=True)
            cls._initialized = True

    @classmethod
    async def close(cls):
        await tortoise.Tortoise.close_connections()
        cls._initialized = False

    @classmethod
    def is_initialized(cls) -> bool:
        return tortoise.Tortoise._inited

    @classmethod
    def ensure_db(cls, func):
        @functools.wraps(func)
        async def wrapper(model_cls, *args, **kwargs):
            if not cls.is_initialized():
                await cls.init()
            return await func(model_cls, *args, **kwargs)
        return wrapper


class PlaylistEntry(tortoise.models.Model):
    id = tortoise.fields.IntField(pk=True)
    user_id = tortoise.fields.CharField(max_length=255)
    uid_hash = tortoise.fields.CharField(max_length=255)
    user_name = tortoise.fields.CharField(max_length=255)
    user_privilege = tortoise.fields.CharField(max_length=10, default='user')
    song_id = tortoise.fields.CharField(max_length=255)
    song_title = tortoise.fields.CharField(max_length=255)
    song_artist = tortoise.fields.CharField(max_length=255)
    song_source = tortoise.fields.CharField(max_length=255)
    song_file = tortoise.fields.CharField(max_length=32768)
    song_decibel = tortoise.fields.FloatField(null=True)
    song_duration = tortoise.fields.IntField(null=True)
    song_meta = tortoise.fields.JSONField(default=dict)
    progress = tortoise.fields.IntField(default=0)
    created_at = tortoise.fields.DatetimeField(auto_now_add=True)
    is_queued = tortoise.fields.BooleanField(default=True)
    is_canceled = tortoise.fields.BooleanField(default=False)
    is_auto_entry = tortoise.fields.BooleanField(default=False)
    is_from_control = tortoise.fields.BooleanField(default=False)
    is_fallback = tortoise.fields.BooleanField(default=False)
    queue_position = tortoise.fields.IntField(default=0)

    class Meta:
        table = "playlist_entries"
        ordering = ["id"]
        indexes = (
            ("is_queued", "id"),
            ("user_id", "user_name"),
            ("is_queued", "is_canceled", "id"),
            ("is_canceled", "is_from_control", "uid_hash", "id"),
        )

    @staticmethod
    def create_queued_ts() -> int:
        return int(time.time() * 1e6)

    @classmethod
    @Database.ensure_db
    async def remove_played_auto_entries(cls):
        await cls.filter(is_queued=False, user_name='', user_privilege='owner').delete()

    def to_user(self) -> UserInfo:
        return UserInfo(
            int(self.user_id) if self.user_id.isdigit() else 0,
            self.uid_hash,
            self.user_name,
            self.user_privilege if self.user_privilege in ('owner', 'admin', 'user') else 'user',
        )

    def set_user(self, user: UserInfo):
        self.user_id = str(user.uid)
        self.user_name = user.username
        self.user_privilege = user.privilege
        self.uid_hash = user.uid_hash

    def to_songinfo(self) -> SongInfo:
        return SongInfo(
            id=self.song_id,
            title=self.song_title,
            singer=self.song_artist,
            source=self.song_source,
            filename=self.song_file,
            decibel=self.song_decibel,
            duration=self.song_duration,
            meta=self.song_meta if isinstance(self.song_meta, dict) else {},
        )

    @classmethod
    def create_entry(cls, user: UserInfo, song: SongInfo,
                     position: int = 0, is_auto_entry: bool = False,
                     is_from_control: bool = False, is_fallback: bool = False) -> PlaylistEntry:
        entry = cls(
            user_id=str(user.uid),
            uid_hash=user.uid_hash,
            user_name=user.username,
            user_privilege=user.privilege,
            song_id=song.id,
            song_title=song.title,
            song_artist=song.singer,
            song_source=song.source,
            song_file=os.path.basename(song.filename),
            song_decibel=song.decibel,
            song_duration=song.duration,
            song_meta=song.meta,
            is_auto_entry=is_auto_entry,
            is_from_control=is_from_control,
            is_fallback=is_fallback,
            queue_position=position,
        )
        entry._saved_in_db = False
        return entry

    @Database.ensure_db
    async def new_entry_save(self, callback: typing.Callable[[], None] | None = None):
        await self.save(force_create=True)
        if callback:
            callback()
        return self

    @classmethod
    @Database.ensure_db
    async def get_queued_entries(cls, limit: int = 50) -> list[PlaylistEntry]:
        entries = await cls.filter(
            is_queued=True,
        ).order_by('id').limit(limit)
        return [entry for entry in entries]

    @classmethod
    @Database.ensure_db
    async def get_user_history_entries(cls, uid_hash: str, limit: int = 50) -> list[PlaylistEntry]:
        """Get history entries of successful requests from user"""
        entries = await cls.filter(
            is_canceled=False,
            is_from_control=False,
            uid_hash=uid_hash
        ).order_by('-id').limit(limit)
        return [entry for entry in entries]

    @classmethod
    @Database.ensure_db
    async def get_past_history_entries(cls, page_num: int, size: int,
                                       hide_canceled: bool = False, filter='') -> tuple[int, list[PlaylistEntry]]:
        offset = (page_num - 1) * size
        if hide_canceled:
            query = cls.filter(is_queued=False, is_canceled=False)
        else:
            query = cls.filter(is_queued=False)
        if filter:
            for keyword in filter.split():
                query = query.filter(Q(song_title__icontains=keyword) | Q(song_artist__icontains=keyword) | Q(user_name__icontains=keyword))
        entries = await query.order_by('-id').offset(offset).limit(size)
        return await query.count(), [entry for entry in entries]

    @classmethod
    @Database.ensure_db
    async def get_recent_users(cls, limit: int = 10) -> list[UserInfo]:
        """Get recent users with unique uid"""
        subquery = cls.filter(
            ~Q(user_id='0') & ~Q(user_name='')
        ).order_by('-id').group_by('user_id').values('id')

        query = cls.filter(
            id__in=Subquery(subquery)
        ).order_by('-id').values_list('user_id', 'user_name', 'uid_hash')

        return [UserInfo(
            uid=int(user_id),
            uid_hash=uid_hash,
            username=username,
            privilege='user'
        ) for user_id, username, uid_hash in (await query) if user_id.isdigit()]

    @Database.ensure_db
    async def set_canceled(self):
        if self.is_auto_entry:
            await self.delete()
        else:
            self.is_queued = False
            self.is_canceled = True
            await self.save(update_fields=['is_queued', 'is_canceled'])

    @Database.ensure_db
    async def set_played(self):
        if self.is_auto_entry:
            await self.delete()
        else:
            self.is_queued = False
            await self.save(update_fields=['is_queued'])


class QueryEntry(tortoise.models.Model):
    query_id = tortoise.fields.IntField(pk=True)
    query_text = tortoise.fields.CharField(max_length=1024)
    created_at = tortoise.fields.DatetimeField(auto_now_add=True)
    user_id = tortoise.fields.CharField(max_length=255)
    uid_hash = tortoise.fields.CharField(max_length=255)
    user_name = tortoise.fields.CharField(max_length=255)
    user_privilege = tortoise.fields.CharField(max_length=10, default='user')
    result = tortoise.fields.CharField(max_length=1024, null=True)
    match_count = tortoise.fields.IntField()
    song_id = tortoise.fields.CharField(max_length=255, null=True)
    song_title = tortoise.fields.CharField(max_length=255, null=True)
    song_singer = tortoise.fields.CharField(max_length=255, null=True)
    song_source = tortoise.fields.CharField(max_length=255, null=True)

    class Meta:
        table = "query_entries"
        ordering = ["query_id"]

    def to_user(self) -> UserInfo:
        return UserInfo(
            uid=int(self.user_id) if self.user_id.isdigit() else 0,
            uid_hash=self.uid_hash,
            username=self.user_name,
            privilege=self.user_privilege if self.user_privilege in ('owner', 'admin', 'user') else 'user',
        )

    def to_songinfo(self) -> SongInfo:
        return SongInfo(
            id=self.song_id or '',
            title=self.song_title or '',
            singer=self.song_singer or '',
            source=self.song_source or '',
            filename='',
            decibel=None,
            duration=None,
            meta={},
        )

    @classmethod
    @Database.ensure_db
    async def new_query(cls, user: UserInfo, query_text: str) -> QueryEntry:
        return await cls.create(
            query_text=query_text,
            user_id=str(user.uid),
            uid_hash=user.uid_hash,
            user_name=user.username,
            user_privilege=user.privilege,
            match_count=0,
        )

    @classmethod
    @Database.ensure_db
    async def get_history_entries(cls, page_num: int, size: int) -> list[QueryEntry]:
        offset = (page_num - 1) * size
        entries = await cls.all().order_by('-query_id').offset(offset).limit(size)
        return [entry for entry in entries]

    @classmethod
    @Database.ensure_db
    async def get_history_count(cls) -> int:
        return await cls.all().count()

    @classmethod
    @Database.ensure_db
    async def discard_old_queries(cls, limit: int = 100):
        remove_ids = cls.all().order_by('-query_id').offset(limit).values('query_id')
        query = cls.filter(query_id__in=Subquery(remove_ids)).delete()
        await query

    @Database.ensure_db
    async def increment_match_count(self, increment: int = 1):
        self.match_count = self.match_count + increment
        await self.save(update_fields=['match_count'])

    @Database.ensure_db
    async def set_failed(self, reason: str = 'failed', additional_info: str | None = None):
        self.result = reason
        if additional_info:
            self.song_title = additional_info
        await self.save(update_fields=['result', 'song_title'])

    @Database.ensure_db
    async def set_result(self, song_info: SongInfo):
        self.result = 'success'
        self.song_id = song_info.id
        self.song_title = song_info.title
        self.song_singer = song_info.singer
        self.song_source = song_info.source
        await self.save(update_fields=['result', 'song_id', 'song_title', 'song_singer', 'song_source'])


class CacheEntry(tortoise.models.Model):
    cache_id = tortoise.fields.CharField(max_length=1024, primary_key=True)
    file_size = tortoise.fields.IntField()
    last_accessed = tortoise.fields.IntField()
    song_id = tortoise.fields.CharField(max_length=255)
    song_source = tortoise.fields.CharField(max_length=255)
    song_file = tortoise.fields.CharField(max_length=32768)
    song_title = tortoise.fields.CharField(max_length=255)
    song_singer = tortoise.fields.CharField(max_length=255)
    song_decibel = tortoise.fields.FloatField(null=True)
    song_duration = tortoise.fields.IntField(null=True)
    song_meta = tortoise.fields.JSONField(default=dict)
    is_valid = tortoise.fields.BooleanField(default=True)

    class Meta:
        table = "cache_entries"
        ordering = ["last_accessed"]

    def to_songinfo(self) -> SongInfo:
        return SongInfo(
            source=self.song_source,
            id=self.song_id,
            title=self.song_title,
            singer=self.song_singer,
            filename=os.path.basename(self.song_file),
            decibel=self.song_decibel,
            duration=self.song_duration,
            meta=self.song_meta if isinstance(self.song_meta, dict) else {},
        )

    async def update_decibel(self, decibel: float | None):
        if decibel:
            self.song_decibel = decibel
            await self.save(update_fields=['song_decibel'])

    async def update_valid(self, is_valid: bool) -> bool:
        '''update is_valid and return the value'''
        if self.is_valid != is_valid:
            self.is_valid = is_valid
            await self.save(update_fields=['is_valid'])
        return self.is_valid

    async def update_access(self):
        '''update last access to current timestamp'''
        if int(time.time()) > self.last_accessed:
            self.last_accessed = int(time.time())
            await self.save(update_fields=['last_accessed'])

    @staticmethod
    def get_cache_id(api: API, song_id: str) -> str:
        return f'{api.key}-{song_id}'

    @classmethod
    @Database.ensure_db
    async def get_cache_entry(cls, api: API, song_id: str) -> CacheEntry | None:
        return await cls.get_or_none(cache_id=cls.get_cache_id(api, song_id))

    @classmethod
    @Database.ensure_db
    async def save_cache_entry(cls, api: API, song_id: str, song_source: str, song_file: str, song_title: str, song_singer: str, song_decibel: float | None, song_duration: int | None, song_meta: dict, file_size: int) -> CacheEntry:
        entry, _ = await cls.update_or_create(
            cache_id=cls.get_cache_id(api, song_id),
            defaults={
                'song_id': song_id,
                'song_source': song_source,
                'song_file': song_file,
                'song_title': song_title,
                'song_singer': song_singer,
                'song_decibel': song_decibel,
                'song_duration': song_duration,
                'song_meta': song_meta,
                'file_size': file_size,
                'last_accessed': int(time.time()),
                'is_valid': True,
            }
        )
        return entry

    @classmethod
    @Database.ensure_db
    async def save_new_meta_entry(cls, api: API, song_id: str, song_source: str, song_title: str, song_singer: str, song_meta: dict) -> CacheEntry:
        """Save meta in new entry if not exists"""
        try:
            return await cls.create(
                cache_id=cls.get_cache_id(api, song_id),
                song_id=song_id,
                song_source=song_source,
                song_file='meta-only',
                song_title=song_title,
                song_singer=song_singer,
                song_decibel=None,
                song_duration=None,
                song_meta=song_meta,
                file_size=0,
                last_accessed=int(time.time()),
                is_valid=False,
            )
        except tortoise.exceptions.IntegrityError:
            return await cls.get(cache_id=cls.get_cache_id(api, song_id))

    @classmethod
    @Database.ensure_db
    async def get_total_size(cls) -> int:
        result = await cls.filter(is_valid=True).annotate(
            total=tortoise.functions.Sum('file_size')
        ).values('total')
        return result[0]['total'] or 0

    @classmethod
    @Database.ensure_db
    def get_entries_by_access(cls, limit: int = 50):
        return cls.all().order_by('last_accessed').limit(limit)


class PlaylistCacheEntry(tortoise.models.Model):
    cache_id = tortoise.fields.CharField(max_length=1024, pk=True)
    playlist_title = tortoise.fields.CharField(max_length=255)
    song_ids = tortoise.fields.JSONField()
    songs_meta = tortoise.fields.JSONField()

    class Meta:
        table = "playlist_cache_entries"

    def as_playlist_info(self, url: str, api_key: str) -> PlaylistInfo:
        return PlaylistInfo(
            url=url,
            title=self.playlist_title,
            api_key=api_key,
            song_ids=list(self.song_ids),
            songs_meta=self.songs_meta if isinstance(self.songs_meta, dict) else {},
        )

    @classmethod
    @Database.ensure_db
    async def get_playlist(cls, api_key: str, prefix: str, playlist_id: str, url: str) -> PlaylistInfo | None:
        """Get playlist from cache if it exists"""
        cache_id = f"{api_key}-{prefix}-{playlist_id}"
        if entry := await cls.get_or_none(cache_id=cache_id):
            return entry.as_playlist_info(url, api_key)
        return None

    @classmethod
    @Database.ensure_db
    async def save_playlist(cls, api_key: str, prefix: str, playlist_id: str,
                            title: str, song_ids: list[str], songs_meta: dict[str, dict]) -> PlaylistCacheEntry:
        """Update or create playlist cache entry"""
        cache_id = f"{api_key}-{prefix}-{playlist_id}"
        entry, _ = await cls.update_or_create(
            cache_id=cache_id,
            defaults={
                'playlist_title': title[:255],
                'song_ids': song_ids,
                'songs_meta': songs_meta,
            }
        )
        return entry


class BannedUserCache(tortoise.models.Model):
    user_id = tortoise.fields.CharField(max_length=255, pk=True)
    user_name = tortoise.fields.CharField(max_length=255)
    modified_at = tortoise.fields.IntField()

    class Meta:
        table = "banned_user_cache"

    @classmethod
    @Database.ensure_db
    async def get_banned_username(cls, uid: int, expired_days: int | float = 3) -> str | None:
        '''get username if saved within expired_days'''
        if entry := await cls.get_or_none(user_id=str(uid)):
            if not expired_days or time.time() < entry.modified_at + 86400 * expired_days:
                return entry.user_name
        return None

    @classmethod
    @Database.ensure_db
    async def get_banned_users(cls, uids: list[int]) -> dict[int, UserInfo]:
        entries = await cls.filter(user_id__in=[str(uid) for uid in uids if uid])
        return {int(entry.user_id): UserInfo(
            uid=int(entry.user_id),
            uid_hash='',
            username=entry.user_name,
            privilege='user'
        ) for entry in entries if entry.user_id.isdigit()}

    @classmethod
    @Database.ensure_db
    async def save_banned_user(cls, uid: int, username: str) -> UserInfo:
        if not username:
            raise ValueError('username cannot be empty')
        await cls.update_or_create(
            user_id=str(uid),
            defaults={'user_name': username[:255], 'modified_at': int(time.time())}
        )
        return UserInfo(uid, '', username, 'user')


class RecentBvidEntry(tortoise.models.Model):
    id = tortoise.fields.IntField(pk=True)
    bvid = tortoise.fields.CharField(max_length=255)
    user_id = tortoise.fields.CharField(max_length=255)
    uid_hash = tortoise.fields.CharField(max_length=255)
    user_name = tortoise.fields.CharField(max_length=255)
    user_privilege = tortoise.fields.CharField(max_length=10, default='user')

    class Meta:
        table = "recent_bvid"

    def to_user(self) -> UserInfo:
        return UserInfo(
            uid=int(self.user_id) if self.user_id.isdigit() else 0,
            uid_hash=self.uid_hash,
            username=self.user_name,
            privilege=self.user_privilege,  # type: ignore[assignment]
        )

    @classmethod
    @Database.ensure_db
    async def add_entry(cls, bvid: str, user: UserInfo):
        await cls.create(
            bvid=bvid,
            user_id=str(user.uid),
            uid_hash=user.uid_hash,
            user_name=user.username,
            user_privilege=user.privilege,
        )

    @classmethod
    @Database.ensure_db
    async def get_recent_bvid(cls, limit: int = 10) -> list[tuple[UserInfo, str]]:
        entries = await cls.all().order_by('-id').limit(limit)
        return [(entry.to_user(), entry.bvid) for entry in entries]

    @classmethod
    @Database.ensure_db
    async def discard_old_bvid(cls, limit: int = 10):
        remove_ids = cls.all().order_by('-id').offset(limit).values('id')
        query = cls.filter(id__in=Subquery(remove_ids)).delete()
        await query


class PlayerStatus(tortoise.models.Model):
    key = tortoise.fields.CharField(max_length=255, pk=True)
    paused = tortoise.fields.BooleanField()

    class Meta:
        table = "player_status"

    @classmethod
    @Database.ensure_db
    async def get_status(cls) -> PlayerStatus:
        entry, _ = await cls.get_or_create(
            defaults={'paused': False},
            key='status'
        )
        return entry


if typing.TYPE_CHECKING:
    from .api.common import API
