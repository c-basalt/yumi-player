from __future__ import annotations
import asyncio
import typing
import logging
import collections
import time


verbose_logger = logging.getLogger('merger_verbose')
logger = logging.getLogger('merger')


class Merger:
    def __init__(self, duration=300, buffer_size=1000, seen_history=5000):
        self._queue: asyncio.Queue[Msg_Packet] | None = None
        self._tasks: set[asyncio.Task] = set()
        self._seen: collections.OrderedDict[tuple[str, str], float] = collections.OrderedDict()
        self._seen_limit = max(100, seen_history)
        self._duration = max(5, duration)
        self._buffer_size = max(100, buffer_size)

    def init(self):
        self._queue = asyncio.Queue(maxsize=self._buffer_size)

    async def queue_get(self):
        if not self._queue:
            self._queue = asyncio.Queue(maxsize=self._buffer_size)
        return await self._queue.get()

    def queue_put_nowait(self, value: Msg_Packet):
        if not self._queue:
            self._queue = asyncio.Queue(maxsize=self._buffer_size)
        self._queue.put_nowait(value)

    @property
    def first_seen_item(self) -> tuple[tuple[str, str], float]:
        try:
            key = next(iter(self._seen))
            return key, self._seen[key]
        except StopIteration:
            return ('', ''), 0

    @property
    def timestamp_limit(self):
        if len(self._seen) < self._seen_limit:
            return time.time() - self._duration
        else:
            return (self.first_seen_item[1] + time.time()) / 2

    def _trim_seen(self):
        while len(self._seen) > self._seen_limit:
            self._seen.popitem(last=False)
        ts_limit = time.time() - self._duration
        while self.first_seen_item[1] < ts_limit:
            self._seen.popitem(last=False)

    async def close(self):
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _handle_generator(self, iterator: DanmakuAsyncIter):
        try:
            async for msg in iterator:
                self.queue_put_nowait(msg)
            logger.info('generator closed', iterator)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception:
            logger.exception('Error while adding msg from generator')

    def add_iter(self, iterator: DanmakuAsyncIter):
        for done in [task for task in self._tasks if task.done()]:
            self._tasks.discard(done)
        task = asyncio.create_task(self._handle_generator(iterator))
        self._tasks.add(task)
        asyncio.ensure_future(task)

    async def next(self):
        def _filter(entry: Msg_Packet):
            _, timestamp, msg = entry
            if timestamp < self.timestamp_limit:
                return False
            cmd, feature = Features.get_features(msg)
            if (cmd, feature) in self._seen:
                return False
            else:
                self._seen[(cmd, feature)] = timestamp
                self._trim_seen()
                return True

        while True:
            msg = await self.queue_get()
            if _filter(msg):
                verbose_logger.debug(f'recv new cmd: {str(msg)[:100]}')
                return msg


class Features:
    @classmethod
    def get_features(cls, msg):
        cmd = str(msg.get('cmd', ''))
        if hasattr(cls, cmd):
            try:
                return cmd, str(getattr(cls, cmd)(msg))
            except Exception:
                pass
        return cmd, str(msg)

    @staticmethod
    def DANMU_MSG(msg):
        info = msg['info']
        return [info[9], info[0][4], info[1]]

    @staticmethod
    def SEND_GIFT(msg):
        data = msg['data']
        return [data['tid'], data['timestamp']]

    @staticmethod
    def SUPER_CHAT_MESSAGE(msg):
        data = msg['data']
        return [data['id'], data['1720455699'], data['price'], data['message']]


if typing.TYPE_CHECKING:
    Msg_Packet = typing.Tuple[int, float, typing.Any]
    DanmakuAsyncIter = typing.AsyncGenerator[Msg_Packet, typing.Any]
