import typing
import hashlib
import json
import base64
import itertools
import aiohttp
import urllib.parse
import uuid
import re
import logging

import aiohttp.web
from Crypto.Cipher import AES

from .utils import run_as_sync, filter_cookies_by_domains


class CookieCloudBase:
    @staticmethod
    def _pass_digest(uuid: str, password: str):
        return hashlib.md5(f'{uuid}-{password}'.encode()).hexdigest()[:16].encode()

    @classmethod
    def _decrypt(cls, encrypted_data: bytes, uuid: str, password: str):
        encrypted_data = base64.b64decode(encrypted_data)
        if encrypted_data[0:8] != b"Salted__":
            raise ValueError('Invalid encrypted data')
        passphrase = cls._pass_digest(uuid, password) + encrypted_data[8:16]
        key_iv = digest = b''
        for _ in range(3):
            digest = hashlib.md5(digest + passphrase).digest()
            key_iv += digest
        cipher = AES.new(key_iv[:32], AES.MODE_CBC, key_iv[32:48])
        decrypted = cipher.decrypt(encrypted_data[16:])
        if decrypted[:1] != b'{':
            raise ValueError('Failed to decrypt cookie data')
        return json.loads(decrypted[:-decrypted[-1]])

    @staticmethod
    def _format_cookies(cookie_data: dict):
        return [{
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie['path'],
            'http_only': cookie['httpOnly'],
        } for cookie in itertools.chain(*cookie_data.values())]


class CookieCloudClient(CookieCloudBase):
    def __init__(self, cookie_cloud_url: str):
        parsed = urllib.parse.urlparse(cookie_cloud_url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f'Invalid scheme: {parsed.scheme}')
        if not parsed.username or not parsed.password:
            raise ValueError('Username (uuid) and password are required')
        self._uuid = parsed.username
        self._password = parsed.password
        self._load_url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc.split('@')[-1],
            f'{parsed.path.rstrip("/")}/get/{self._uuid}', parsed.params, parsed.query, ''
        ))

    def __call__(self, domains: list[str] | None = None) -> list[dict[str, typing.Any]]:
        return run_as_sync(self.load(domains))

    @classmethod
    async def _load(cls, url: str, uuid: str, password: str):
        async with aiohttp.request('GET', url) as resp:
            resp.raise_for_status()
            encrypted_data = (await resp.json())['encrypted']
        decrypted = cls._decrypt(encrypted_data, uuid, password)
        return cls._format_cookies(decrypted['cookie_data'])

    async def load(self, domains: list[str] | None = None) -> list[dict[str, typing.Any]]:
        cookies = await self._load(self._load_url, self._uuid, self._password)
        return filter_cookies_by_domains(cookies, domains)


class CookieCloudServer(CookieCloudBase):
    def __init__(self, salt: str, on_update: typing.Callable[[], None] | None = None):
        self._uuid = self._generate(f'uuid{salt}')
        self._password = self._generate(f'password{salt}')
        self._logger = logging.getLogger('cookies.cookie_cloud_server')
        self._on_update = on_update
        self._cookie_data = {}

    @staticmethod
    def _encode(data: bytes):
        return re.sub(r'[^A-Za-z0-9]', '', base64.b64encode(data).decode())

    @classmethod
    def _generate(cls, salt: str, size=22):
        hasher = hashlib.sha256(f'{uuid.getnode()}{salt}'.encode())
        generated = cls._encode(hasher.digest())
        while len(generated) < size:
            hasher.update(hasher.digest())
            generated += cls._encode(hasher.digest())
        return generated[:size]

    @property
    def uuid(self):
        return self._uuid

    @property
    def password(self):
        return self._password

    async def handle_update_request(self, request: aiohttp.web.Request):
        if request.method == 'OPTIONS':
            return aiohttp.web.Response(status=200)
        data = await request.json()
        if data.get('uuid') != self._uuid or not data.get('encrypted'):
            return aiohttp.web.Response(status=400)
        try:
            self._cookie_data = self._decrypt(data['encrypted'], self._uuid, self._password)['cookie_data']
        except Exception:
            self._logger.exception('解析CookieCloud扩展发送的数据时出错，请检查uuid和密码是否正确')
            return aiohttp.web.json_response(data={'action': 'error'})
        if self._on_update:
            self._on_update()
        return aiohttp.web.json_response(data={'action': 'done'})

    def __call__(self, domains: list[str] | None = None) -> list[dict[str, typing.Any]]:
        return filter_cookies_by_domains(self._format_cookies(self._cookie_data), domains)
