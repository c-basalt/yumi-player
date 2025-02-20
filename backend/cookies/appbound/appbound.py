import subprocess
import asyncio
import aiohttp
import logging
import contextlib
import os
import json


logger = logging.getLogger('cookies.appbound')
HEADLESS = False


def find_free_port(start_port=9222, end_port=9322):
    """Find first available port in the given range."""
    result = subprocess.check_output(['netstat', '-anp', 'TCP'], text=True, stderr=subprocess.DEVNULL)
    in_use: set[int] = set()
    for line in result.splitlines():
        if 'LISTENING' in line:
            with contextlib.suppress(ValueError, IndexError):
                addr = line.split()[1]
                in_use.add(int(addr.split(':')[-1]))

    for port in range(start_port, end_port + 1):
        if port not in in_use:
            return port
    raise RuntimeError(f"No free ports available in range {start_port}-{end_port}")


async def get_debug_ws_url(debug_port: int):
    logger.info(f'Getting debug ws url for port {debug_port}')
    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://localhost:{debug_port}/json') as response:
            data = await response.json()
            return data[0]['webSocketDebuggerUrl'].strip()


def kill_running_arg(path: str) -> str | None:
    ps_command = '''
    Get-WmiObject Win32_Process -Filter "name = '%s'" |
    where {$_.CommandLine -like '*%s*'} |
    Select-Object CommandLine, ProcessId |
    ConvertTo-Json
    ''' % (os.path.basename(path), path)
    logger.debug(f'运行命令: {ps_command}')
    p = subprocess.run(['powershell', '-Command', ps_command], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f'Failed to get running chrome return={p.returncode}: {p.stderr}')
    if not p.stdout.strip():
        logger.info('没有运行中的浏览器')
        return None

    running_arg = ''
    processes = json.loads(p.stdout)
    processes = [processes] if isinstance(processes, dict) else processes
    for process in processes:
        cmd = process['CommandLine']
        if '--type=' not in cmd and '--no-startup-window' not in cmd:
            arg_list = cmd.split(maxsplit=1)[1:] if cmd[0] != '"' else cmd.split('"', maxsplit=2)[2:]
            running_arg = ' '.join(arg_list)
            break

    pids = ','.join(str(process['ProcessId']) for process in processes)
    ps_command = '''Get-Process -Id %s -ErrorAction SilentlyContinue|
    ForEach-Object {
        Write-Output "$($_.Id) "
        $_ | Stop-Process -Force
    }
    ''' % pids
    logger.debug(f'运行命令: {ps_command}')
    result = subprocess.run(['powershell', '-Command', ps_command], text=True, capture_output=True)
    stdout = result.stdout.replace('\n', '').replace('\r', '').strip()
    logger.info(f'停止浏览器进程: {stdout} {result.stderr.strip()}')

    return running_arg


def restart_chrome(path: str, args: str):
    cmd = f'start "" /B "{path}" {args} --restore-last-session'
    os.system(cmd)


async def start_debugged_chrome(chrome_path: str, user_data_dir: str, debug_port: int, restart: bool = False):
    logger.info(f'启动浏览器，远程调试端口{debug_port}: {chrome_path}')
    process = await asyncio.create_subprocess_exec(
        chrome_path,
        f'--remote-debugging-port={debug_port}',
        '--remote-allow-origins=*',
        '--headless' if HEADLESS else '',
        f'--user-data-dir={user_data_dir}',
        '--restore-last-session',
    )

    await asyncio.sleep(1)
    return process


def _format_cookies(cookies: list[dict]):
    return [{
        'name': cookie['name'],
        'value': cookie['value'],
        'domain': cookie['domain'],
        'path': cookie['path'],
        'http_only': cookie['httpOnly'],
    } for cookie in cookies]


async def get_cookies(chrome_path: str, user_data_dir: str):
    # running process must be killed before a debugging session can start
    running_arg = kill_running_arg(chrome_path)
    debug_port = find_free_port()
    process = await start_debugged_chrome(chrome_path, user_data_dir, debug_port,
                                          restart=(running_arg is not None))

    try:
        url = await get_debug_ws_url(debug_port)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.ws_connect(url) as ws:
                logger.info(f'连接至 {url}')
                await ws.send_json({'id': 1, 'method': 'Storage.getCookies'})
                logger.info('等待响应')
                response = await ws.receive_json(timeout=10)
                logger.info('等待浏览器关闭')
                await ws.send_json({'id': 2, 'method': 'Browser.close'})
                await asyncio.sleep(0.5)
                return _format_cookies(response['result']['cookies'])
    finally:
        with contextlib.suppress(ProcessLookupError):
            logger.info('停止浏览器进程, pid: %s', process.pid)
            process.kill()
            logger.info('停止的浏览器进程, pid: %s', process.pid)
        if running_arg is not None:
            restart_chrome(chrome_path, running_arg)
