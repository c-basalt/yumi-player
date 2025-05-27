from __future__ import annotations

import asyncio
import json
import collections
import time
import logging
import typing
import contextlib
import re
import http.cookies
import urllib.parse
import hashlib

import aiohttp
import brotli

from .config import create_aiohttp_session


class DanmakuClient:
    _API_AUTH_URL = 'https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo'
    _HEARTBEAT_BYTES = bytes.fromhex('0000001f0010000100000002000000015b6f626a656374204f626a6563745d')
    _HEARTBEAT_INTERVAL = 30
    _HANDSHAKE_HEAD_HEX = '001000010000000700000001'
    _UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61'
    _ROOM_INFO_CACHE: dict[int, tuple[int, int, int]] = {}
    _OWNER_NAME_CACHE: dict[int, str] = {}
    _WBI_SIGN_CACHE: tuple[int, str] | None = None
    _WBI_CACHE_TIMEOUT = 120

    _logger = logging.getLogger('danmaku')

    def __init__(self, roomid: int, maxsize=10000):
        self.roomid = roomid
        self._token: str | None = None
        self._short_id = None
        self._uid = None
        self._session = create_aiohttp_session()
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._counter = 0
        self._maxsize = maxsize
        self._data: collections.deque[Msg_Packet] = collections.deque(maxlen=maxsize)
        self._listen_queues: dict[int, asyncio.Queue[Msg_Packet]] = {}
        self._error_count: dict[int, int] = {}

    @property
    def counter(self):
        self._counter += 1
        return self._counter

    @property
    def short_id(self):
        return self._short_id or self.roomid

    def handle(self, command):
        data: Msg_Packet = (self.counter, time.time(), command)
        self._data.append(data)
        for key, queue in list(self._listen_queues.items()):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                self._logger.warning(f'[{self.roomid}] discard queue due to queue full, possibly dead queue')
                self._listen_queues.pop(key, None)

    async def iter_msg(self, index_after: int = -1, include=[]):
        while not self.closed:
            try:
                with self.listen(index_after) as getter:
                    while True:
                        msg = await getter()
                        if msg:
                            if not include or msg[2].get('cmd') in include:
                                yield msg
            except Exception:
                self._logger.exception(f'[{self.roomid}] error while iter danmaku msg')

    @contextlib.contextmanager
    def listen(self, index_after: int = -1):
        if self.closed:
            raise RuntimeError('danmaku client is already closed')

        queue = asyncio.Queue(maxsize=self._maxsize * 2)
        if index_after > 0:
            for item in self._data:
                if item[0] > index_after:
                    queue.put_nowait(item)

        queue_key = max(self._listen_queues, default=0) + 1
        self._listen_queues[queue_key] = queue
        del queue
        try:
            if index_after > 0:
                for item in self._data:
                    if item[0] > index_after:
                        self._listen_queues[queue_key].put_nowait(item)

            async def getter(timeout=3):
                if queue_key not in self._listen_queues:
                    raise RuntimeError('msg queue is already discarded')
                try:
                    return await asyncio.wait_for(self._listen_queues[queue_key].get(), timeout=timeout)
                except asyncio.TimeoutError:
                    return None

            yield getter
        finally:
            self._listen_queues.pop(queue_key, None)

    @property
    def closed(self):
        return self._session.closed

    async def close(self):
        if self._websocket:
            await self._websocket.close()
        await self._session.close()
        self._listen_queues.clear()

    @property
    def headers(self):
        return {
            'User-Agent': self._UA,
            'Referer': f'https://live.bilibili.com/{self.short_id}',
        }

    @classmethod
    async def fetch_owner_uname(cls, roomid: int, session: aiohttp.ClientSession):
        if roomid in cls._OWNER_NAME_CACHE:
            return cls._OWNER_NAME_CACHE[roomid]
        url = f'https://live.bilibili.com/{roomid}'
        async with session.get(url, headers={'User-Agent': cls._UA}) as r:
            rsp = await r.text()
            for pattern in [r'"anchor_info":{"base_info":{"uname":"([^"]+)"',
                            r'name="description" content="(\w+)的哔哩哔哩直播间']:
                if match := re.search(pattern, rsp):
                    cls._OWNER_NAME_CACHE[roomid] = match.group(1)
                    return cls._OWNER_NAME_CACHE[roomid]
        async with session.get(f'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id={roomid}',
                               headers={'User-Agent': cls._UA, 'Referer': f'https://live.bilibili.com/{roomid}'}) as r:
            rsp = await r.json()
            if r.status == 200 and rsp.get('code') == 0:
                cls._OWNER_NAME_CACHE[roomid] = rsp['data']['anchor_info']['base_info']['uname']
                return cls._OWNER_NAME_CACHE[roomid]
            cls._logger.warning(f'[{roomid}] 主播用户名获取失败 status={r.status}: {rsp.get("message")}')
        return None

    @classmethod
    async def _fetch_wbi_sign(cls, roomid: int, session: aiohttp.ClientSession):
        headers = {'User-Agent': cls._UA, 'Referer': f'https://live.bilibili.com/{roomid}'}
        async with session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers) as r:
            data = (await r.json())['data']['wbi_img']
        lookup = ''.join(data[k].split('/')[-1].split('.')[0] for k in ('img_url', 'sub_url'))
        mixin_key_enc_tab = [
            46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
            33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
            61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
            36, 20, 34, 44, 52,
        ]
        return ''.join(lookup[i] for i in mixin_key_enc_tab)[:32]

    @classmethod
    async def _wbi_sign(cls, roomid: int, session: aiohttp.ClientSession, params):
        if cls._WBI_SIGN_CACHE is None or time.monotonic() > cls._WBI_SIGN_CACHE[0] + cls._WBI_CACHE_TIMEOUT:
            cls._WBI_SIGN_CACHE = (int(time.monotonic()), await cls._fetch_wbi_sign(roomid, session))
        params['wts'] = round(time.time())
        params = {
            k: ''.join(filter(lambda char: char not in "!'()*", str(v)))
            for k, v in sorted(params.items())
        }
        query = urllib.parse.urlencode(params)
        params['w_rid'] = hashlib.md5(f'{query}{cls._WBI_SIGN_CACHE[1]}'.encode()).hexdigest()
        return params

    @classmethod
    async def fetch_room_info(cls, roomid: int, session: aiohttp.ClientSession) -> tuple[int, int, int]:
        '''return (roomid, short_id, uid) for a given roomid or short_id'''
        if roomid in cls._ROOM_INFO_CACHE:
            return cls._ROOM_INFO_CACHE[roomid]
        url = f'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo?room_id={roomid}&no_playurl=0&mask=1&qn=0&platform=web&protocol=0,1&format=0,1,2&codec=0,1,2&dolby=5&panorama=1'
        headers = {'User-Agent': cls._UA, 'Referer': f'https://live.bilibili.com/{roomid}'}
        async with session.get(url, headers=headers) as r:
            rsp = await r.json()
            if rsp['code'] == 0 and r.status == 200:
                uid = int(rsp['data']['uid'])
                roomid = int(rsp['data']['room_id'])
                short_id = int(rsp['data']['short_id']) or roomid
                cls._ROOM_INFO_CACHE[roomid] = (roomid, short_id, uid)
                return cls._ROOM_INFO_CACHE[roomid]
            raise ValueError(f'Failed to fetch room info: {rsp}')

    async def update_room_info(self):
        try:
            roomid, short_id, uid = await self.fetch_room_info(self.roomid, self._session)
            self._uid = uid
            self.roomid = roomid
            self._short_id = short_id
        except Exception:
            self._logger.warning(f'[{self.roomid}] Failed to update room info', exc_info=True)

    async def reset_connection(self):
        self._logger.info(f'[{self.roomid}] 重置弹幕连接')
        self._token = None
        if websocket := self._websocket:
            self._websocket = None
            await websocket.close()

    async def connect_danmaku(self, servers: list[str], token: str, uid=0):
        try:
            start = time.time()
            self._token = token
            for server in servers:
                if time.time() - start > 300 or self._session.closed or not self._token:
                    break
                async with self._session.ws_connect(server, headers={'user-agent': self._UA},
                                                    receive_timeout=self._HEARTBEAT_INTERVAL + 5) as ws:
                    self._websocket = ws
                    self._logger.info(f'[{self.roomid}] 以uid={uid}身份连接弹幕服务器 {server}')
                    await ws.send_bytes(self._create_handshake(token, uid))
                    asyncio.ensure_future(self._heartbeat(ws))

                    async for msg in ws:
                        try:
                            assert msg.type == aiohttp.WSMsgType.BINARY, f'received non-binary msg {msg.type}'
                            self._handle_packet(msg.data)
                        except (asyncio.CancelledError, KeyboardInterrupt):
                            raise
                        except Exception:
                            self._logger.exception(f'[{self.roomid}] 处理弹幕数据包时出错')
                    self._logger.info(f'[{self.roomid}] 用uid={uid}身份的弹幕连接已断开 {server}')
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception:
            self._logger.exception(f'[{self.roomid}] 弹幕服务器连接出错')

    async def fetch_danmaku_handshake(self, cookies: dict[str, str] | http.cookies.SimpleCookie, **kwargs):
        try:
            cookie = cookies.get('DedeUserID')
            uid = int((cookie.value if isinstance(cookie, http.cookies.Morsel) else cookie) or 0)
        except ValueError:
            self._logger.warning(f'[{self.roomid}] cookies中的DedeUserID无效，使用uid=0')
            uid = 0
        if not uid and len(cookies):
            self._logger.warning(f'[{self.roomid}] 无有效的DedeUserID，使用空cookies')
            cookies = {}

        params = await self._wbi_sign(self.roomid, self._session, {'id': self.roomid, 'type': 0})
        async with self._session.get(self._API_AUTH_URL, params=params,
                                     cookies=cookies, headers=self.headers, **kwargs) as r:
            self._logger.info(
                f'[{self.roomid}] {"不使用cookies并" if not cookies else ""}获取弹幕握手信息')
            rsp = await r.json()
            if rsp.get('code') != 0 or r.status != 200:
                raise ValueError(f'Failed to get handshake info {r.status}: {rsp}')
            token = str(rsp['data']['token'])
            servers = [f"wss://{server['host']}:{server['wss_port']}/sub" for server in rsp['data']['host_list']]
            return servers, token, uid

    def _create_handshake(self, token: str, uid: int):
        payload = json.dumps({
            'uid': uid,
            'roomid': self.roomid,
            'protover': 3,
            'platform': 'web',
            'type': 2,
            'key': token,
        }, separators=(',', ':')).encode('utf-8')
        return bytes.fromhex(f'{(len(payload) + 16):08X}{self._HANDSHAKE_HEAD_HEX}') + payload

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse):
        while not ws.closed:
            await ws.send_bytes(self._HEARTBEAT_BYTES)
            await asyncio.sleep(self._HEARTBEAT_INTERVAL)

    def _handle_packet(self, raw_data):
        while raw_data:
            packet_size = int.from_bytes(raw_data[:4], 'big')
            header_size = int.from_bytes(raw_data[4:6], 'big')
            protocol = int.from_bytes(raw_data[6:8], 'big')
            msg_type = int.from_bytes(raw_data[8:12], 'big')

            try:
                if protocol == 3:  # brotli
                    self._handle_packet(brotli.decompress(raw_data[header_size:packet_size]))
                else:
                    if msg_type == 5:  # data msg
                        assert protocol == 0, f'Unexpected msg protocol ver={protocol}'
                        command = json.loads(raw_data[header_size:packet_size])
                        self.handle(command)
            except Exception:
                self._logger.exception(f'[{self.roomid}] Failed to decode danmaku packet')

            assert packet_size >= 8
            raw_data = raw_data[packet_size:]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class DanmakuRooms:
    def __init__(self, token_getter: Token_Callback | None = None, cookies_getter: Cookies_Callback | None = None,
                 entry_cache_size=10000):
        self._logger = logging.getLogger('danmaku_rooms')
        self._rooms: dict[int, DanmakuClient] = {}
        self._runners: dict[int, asyncio.Task] = {}
        self._cookies_getter = cookies_getter
        self._token_getter = token_getter
        self._entry_cache_size = entry_cache_size
        assert self._cookies_getter or self._token_getter, 'need either cookie or token getter'

    @property
    def rooms(self):
        return {
            **{room.roomid: room for room in self._rooms.values()},
            **{room.short_id: room for room in self._rooms.values()},
        }

    async def close(self):
        for task in self._runners.values():
            task.cancel()
        await asyncio.gather(*[room.close() for room in self._rooms.values()])

    async def reset_connections(self):
        self._logger.info(f'重置{len(self._rooms)}个弹幕连接')
        await asyncio.gather(*[room.reset_connection() for room in self._rooms.values()])

    async def _get_token(self, room: DanmakuClient):
        if self._cookies_getter:
            cookies = await self._cookies_getter()
            if cookies is not None:
                return await room.fetch_danmaku_handshake(cookies)
        assert self._token_getter
        return await self._token_getter(room.roomid)

    async def _run_room(self, room: DanmakuClient):
        while not room.closed:
            try:
                servers, token, uid = await self._get_token(room)
                await room.connect_danmaku(servers, token, uid)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception:
                self._logger.warning(f'连接直播间{room.roomid}时出错', exc_info=True)
            await asyncio.sleep(3)

    def _check_runners(self):
        for key, task in list(self._runners.items()):
            if task.done():
                self._runners.pop(key)

    def run_room(self, room: DanmakuClient):
        roomid = room.roomid
        if self._runners.get(roomid):
            self._runners[roomid].cancel()
        self._runners[roomid] = asyncio.ensure_future(self._run_room(room))
        self._check_runners()

    async def add_room(self, roomid):
        if roomid in self._rooms or roomid in self.rooms:
            return
        self._logger.info(f'添加直播间 roomid={roomid}')
        room = DanmakuClient(roomid, maxsize=self._entry_cache_size)
        await room.update_room_info()
        self._rooms[roomid] = room
        self.run_room(room)

    async def remove_room(self, roomid):
        for roomid, room in list(self._rooms.items()):
            if room.roomid == roomid or room.short_id == roomid:
                self._logger.info(f'移除直播间 roomid={roomid}')
                await self._rooms.pop(roomid).close()
                return

    async def update_rooms(self, roomids: list[int]):
        for roomid in roomids:
            await self.add_room(roomid)
        for room in list(self._rooms.values()):
            if room.roomid not in roomids and room.short_id not in roomids:
                await self.remove_room(room.roomid)


if typing.TYPE_CHECKING:
    Cookies_Callback = typing.Callable[[], typing.Coroutine[
        typing.Any, typing.Any, typing.Union[typing.Dict[str, str], http.cookies.SimpleCookie, None]]]
    Token_Callback = typing.Callable[[int], typing.Coroutine[typing.Any, typing.Any,
                                                             typing.Tuple[typing.List[str], str, int]]]
    Packet_Callback = typing.Callable[[typing.Any], typing.Any]
    Msg_Packet = typing.Tuple[int, float, typing.Any]
