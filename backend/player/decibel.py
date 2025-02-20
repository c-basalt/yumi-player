import asyncio
import re
import logging
import os

FFMPEG_UNAVAILABLE = False
RETRY_UNEXPECTED = True

logger = logging.getLogger('player.decibel')


async def get_decibel(filepath: str) -> float | None:
    global FFMPEG_UNAVAILABLE, RETRY_UNEXPECTED
    if FFMPEG_UNAVAILABLE:
        logger.warning(f"无ffmpeg程序，跳过: {filepath}")
        return None

    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-i", filepath,
            "-filter:a", "volumedetect",
            "-vn", "-sn", "-dn",
            "-f", "null", "-"
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            timeout = 5 + os.path.getsize(filepath) / 4e6
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stderr.decode().replace('\r', '')
        except asyncio.TimeoutError:
            process.kill()
            logger.warning(f"ffmpeg进程超时 ({timeout:.1f}秒): {filepath}")
            return None

        logger.debug(f"ffmpeg输出 {filepath}:\n{output}")

        # Extract mean_volume from ffmpeg output
        if match := re.search(r"mean_volume: ([-\d.]+) dB", output):
            return float(match.group(1))
        else:
            logger.warning(f"无法用ffmpeg获取分贝: {filepath}")
            return None
    except FileNotFoundError:
        logger.warning(f"未找到ffmpeg，设置FFMPEG_UNAVAILABLE=True: {filepath}")
        FFMPEG_UNAVAILABLE = True
        return None
    except Exception as e:
        logger.warning(f"处理时发生未知错误 {filepath}: {e}")
        if RETRY_UNEXPECTED:
            RETRY_UNEXPECTED = False
            return await get_decibel(filepath)
        return None
