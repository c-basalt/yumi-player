from __future__ import annotations
import argparse
import asyncio
import logging
import typing
import os
import webbrowser
import dataclasses
import subprocess

import aiohttp.web

from .config import get_basedir, DataConfig, aiohttp_session
from .cookies import CookieManager
from .danmaku import DanmakuRooms, DanmakuClient
from .merger import Merger
from .player import Player
from .db import Database, PlaylistEntry
from .version import get_version, get_environment
from .logging import setup_logging


class Plugin(typing.Protocol):
    def __init__(self, server: Server):
        ...

    async def init(self):
        ...

    async def close(self):
        ...

    def handle(self, msg):
        ...


@dataclasses.dataclass
class RootConfig(DataConfig):
    roomid: int = 0
    version: int = 1


class Server:
    def __init__(self, root_app: aiohttp.web.Application, config_fn: str, baseurl: str):
        self._baseurl = baseurl
        self.config = RootConfig.create_root(config_fn)
        with self.config.suppress_save():
            self.cookies = CookieManager(self)
            self._logger = logging.getLogger('main_server')
            self._app = aiohttp.web.Application()
            self._merger = Merger()
            self._local_danmaku = DanmakuRooms(cookies_getter=self.get_bilibili_cookies)
            self._closed = False
            self._worker: asyncio.Task | None = None
            self._sub_apps: set[str] = set()

            def _add_route(prefix: str, handler: aiohttp.typedefs.Handler):
                self._app.router.add_route('*', prefix, handler)
                self._sub_apps.add(prefix)
            _add_route('/roomid', self.roomid_config_handler)
            _add_route('/config', self.config_handler)
            _add_route('/cookie', self.cookies.cookie_handler)
            _add_route('/cookie/update', self.cookies.handle_cookie_cloud_update)
            _add_route('/logging', self.logging_handler)
            _add_route('/pid', self.pid_handler)
            _add_route('/baseurl', self.baseurl_handler)
            _add_route('/version', self.version_handler)

            self._plugins: list[Plugin] = [Player(self)]

            root_app.add_subapp('/api', self._app)

    async def get_bilibili_cookies(self):
        return self.cookies.get_cookies('Bilibili')

    async def init(self):
        self._merger.init()
        self._worker = asyncio.create_task(self._dispatch_worker())
        await self.cookies.init()
        await self._apply_roomid_config()
        await asyncio.gather(*[plugin.init() for plugin in self._plugins])

    async def close(self):
        if self._worker:
            self._worker.cancel()
        await asyncio.gather(*[plugin.close() for plugin in self._plugins])
        await self._local_danmaku.close()
        await self._merger.close()
        self._closed = True

    async def _apply_roomid_config(self):
        asyncio.ensure_future(self._merger.close())
        self._merger = Merger()
        if self.roomid:
            await self._local_danmaku.update_rooms([self.roomid])
            self._merger.add_iter(self._local_danmaku.rooms[self.roomid].iter_msg())

    async def _dispatch_worker(self):
        while not self._closed:
            try:
                _, _, msg = await asyncio.wait_for(self._merger.next(), timeout=3)
                for plugin in self._plugins:
                    plugin.handle(msg)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except asyncio.TimeoutError:
                pass
            except Exception:
                self._logger.exception('error while dispatch msg')

    async def context(self, *args):
        try:
            await Database.init()
            await PlaylistEntry.remove_played_auto_entries()
            await self.init()
        except Exception:
            self._logger.exception('error while init server')
            raise
        yield
        try:
            await self.close()
        finally:
            await Database.close()

    @property
    def roomid(self) -> int:
        return int(self.config.roomid)

    @roomid.setter
    def roomid(self, value: int):
        self.config.roomid = int(value)

    @property
    def room_uid(self):
        if room := self._local_danmaku.rooms.get(self.roomid):
            return room._uid

    def add_subapp(self, prefix: str, app: aiohttp.web.Application):
        assert prefix[0] == '/'
        prefix = prefix.rstrip('/')
        if prefix in self._sub_apps:
            raise RuntimeError(f'app {prefix} already added')
        self._app.add_subapp(prefix, app)
        self._sub_apps.add(prefix)

    async def reset_danmaku_connections(self):
        await self._local_danmaku.reset_connections()

    async def roomid_config_handler(self, request: aiohttp.web.Request):
        if request.method == 'POST':
            try:
                data = await request.json()
                roomid = int(data['roomid'])
                assert roomid > 0
                self.roomid = roomid
                await self._apply_roomid_config()
            except Exception as e:
                self._logger.exception('error while applying roomid config')
                return aiohttp.web.json_response({'error': str(e)}, status=400)
        if not self.roomid:
            return aiohttp.web.json_response({'roomid': 0, 'uid': 0, 'short_id': 0, 'uname': ''})
        try:
            async with aiohttp_session(timeout=aiohttp.ClientTimeout(total=10)) as session:
                [roomid, short_id, uid], uname = await asyncio.gather(
                    DanmakuClient.fetch_room_info(self.roomid, session),
                    DanmakuClient.fetch_owner_uname(self.roomid, session),
                )
            return aiohttp.web.json_response({
                'roomid': roomid, 'uid': uid, 'short_id': short_id, 'uname': uname})
        except Exception:
            self._logger.exception('error while fetching room info')
            return aiohttp.web.json_response({
                'roomid': self.roomid, 'uid': 'UID读取失败', 'short_id': self.roomid, 'uname': '用户名读取失败'})

    async def config_handler(self, request: aiohttp.web.Request):
        if request.method == 'POST':
            data = await request.json()
            self.config.update(data)
        if request.method == 'DELETE':
            data = await request.json()
            config = self.config
            for path in data['config_path']:
                config = config.sub_configs[path]
            self._logger.info(f'resetting config {config._prefix or "root"}, recursive={data["recursive"]}, exclude={data["exclude"]}')
            config.reset_config(recursive=data['recursive'], exclude=data['exclude'])
        return aiohttp.web.json_response(self.config.as_dict(recursive=True))

    async def logging_handler(self, request: aiohttp.web.Request):
        if request.method == 'POST':
            data = await request.json()
            logger = logging.getLogger('browser')
            level: str = data['level'].lower()
            msg: str = data['message']
            getattr(logger, level)(msg)
        return aiohttp.web.json_response({})

    async def pid_handler(self, request: aiohttp.web.Request):
        return aiohttp.web.json_response({'pid': os.getpid()})

    async def baseurl_handler(self, request: aiohttp.web.Request):
        return aiohttp.web.json_response({'baseurl': self._baseurl})

    async def version_handler(self, request: aiohttp.web.Request):
        return aiohttp.web.json_response({'version': get_version()})


allowed_hosts: set[str] = set()


@aiohttp.web.middleware
async def cors_middleware(request: aiohttp.web.Request, handler: aiohttp.typedefs.Handler):
    resp = await handler(request)
    if request.headers.get('origin') in allowed_hosts:
        resp.headers.update({
            'Access-Control-Allow-Origin': request.headers.get('origin', '*'),
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Max-Age': '3600',
        })
    return resp


async def index_handler(_):
    return aiohttp.web.FileResponse(os.path.join(get_basedir(), 'static', 'index.html'))


async def run(args: argparse.Namespace):
    app = aiohttp.web.Application(middlewares=[cors_middleware])
    app.router.add_get('/', index_handler)
    app.router.add_static('/', os.path.join(get_basedir(), 'static'))

    baseurl = f'http://{args.host if args.host != "0.0.0.0" else "127.0.0.1"}:{args.port}'

    server = Server(app, args.config_fn, baseurl)
    app.cleanup_ctx.append(server.context)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()

    port_in_use = False

    try:
        site = aiohttp.web.TCPSite(runner, args.host, args.port)
        try:
            await site.start()
        except OSError:
            port_in_use = True
            logging.exception('Failed to start site')
            raise
        if not args.no_browser:
            ip_addr = determine_primary_ip() if args.host == '0.0.0.0' else args.host
            webbrowser.open(f'http://{ip_addr}:{args.port}/')
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await runner.shutdown()
        logging.info("Shutting down server...")
    except Exception:
        logging.exception('error while running server')
        raise
    finally:
        await runner.cleanup()
        if port_in_use:
            await asyncio.sleep(1)
            print()
            print(f'端口{args.port}被占用，请检查是否已经有程序正在运行')
            await asyncio.sleep(10)


def determine_primary_ip(default='127.0.0.1') -> str:
    try:
        if os.name == 'nt':
            output = subprocess.check_output(['route', 'print', '0.0.0.0'], text=True)
        for line in output.splitlines():
            if '0.0.0.0' in line:
                if '0.0.0.0' == line.split()[1]:
                    return line.split()[3]
    except Exception:
        pass
    return default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9823)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--config_fn', default='config.json')
    parser.add_argument('--allow-host', action='append', default=[])
    args = parser.parse_args()

    # Set up logging configuration
    setup_logging(verbose=args.verbose)
    logging.info(f'Starting server, version {get_version()}')
    logging.debug(f'Environment: {get_environment()}')

    logging.debug(f'Setting up CORS for {args.allow_host}')
    allowed_hosts.update(args.allow_host)

    asyncio.run(run(args))


if __name__ == '__main__':
    main()

if typing.TYPE_CHECKING:
    import aiohttp.typedefs
