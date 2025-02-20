import logging
import re
import typing

import aiohttp

from ..db import UserInfo
from ..config import aiohttp_session

logger = logging.getLogger('player.bilibili_api')


async def fetch_bili_uname(uid: int) -> str | None:
    async with aiohttp_session(headers={
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
    }, timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.get(f'https://space.bilibili.com/{uid}') as rsp:
                if rsp.status != 200:
                    logger.warning(f'Failed to fetch username for {uid}: HTTP status {rsp.status}')
                    return None
                text = await rsp.text()
                if match := re.search(r'<title>([^<]+?)的个人空间', text):
                    logger.info(f'Fetched username for {uid}: {match.group(1)}')
                    return match.group(1)
                else:
                    logger.warning(f'Failed to match username for {uid}')
        except Exception:
            logger.exception(f'Failed to fetch username for {uid}')


async def _fetch_chat_history(session: aiohttp.ClientSession, roomid: int) -> list[typing.Any] | None:
    async with session.get(f'https://api.live.bilibili.com/xlive/web-room/v1/dM/gethistory?roomid={roomid}&room_type=0') as rsp:
        data = await rsp.json()
        if data['code'] == 0:
            return data['data']['room']
        else:
            logger.warning(f'Failed to fetch chat history: {data}')


async def _fetch_rank_list(session: aiohttp.ClientSession, roomid: int, uid: int) -> list[typing.Any] | None:
    async with session.get(f'https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank?ruid={uid}&room_id={roomid}&page=1&page_size=100&type=online_rank&switch=contribution_rank&platform=web') as rsp:
        data = await rsp.json()
        if data['code'] == 0:
            return data['data']['item']
        else:
            logger.warning(f'Failed to fetch rank list: {data}')


async def fetch_recent_users(roomid: int, uid: int) -> list[UserInfo]:
    async with aiohttp_session(headers={
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.61',
        'referer': f'https://www.bilibili.com/{roomid}',
        'origin': 'https://www.bilibili.com',
    }, timeout=aiohttp.ClientTimeout(total=10)) as session:
        users = []

        if not roomid:
            return users
        try:
            chat_history = await _fetch_chat_history(session, roomid)
            users.extend([UserInfo(msg['uid'], '', msg['nickname']) for msg in reversed(chat_history or [])])
        except Exception:
            logger.exception('Error while fetching chat history')

        if not uid:
            return users
        try:
            rank_list = await _fetch_rank_list(session, roomid, uid)
            users.extend([UserInfo(user['uid'], '', user['name']) for user in reversed(rank_list or [])])
        except Exception:
            logger.exception('Error while fetching rank list')

        return users
