import logging
import logging.handlers
import os
import re
import queue
import threading


def setup_logging(verbose=False):
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    formatter = logging.Formatter('[%(asctime)s][%(name)s][%(levelname)s] %(message)s')

    class ThreadedStreamHandler(logging.StreamHandler):
        """Threaded handler to prevent QuickEdit from blocking the main thread"""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._msg_queue = queue.Queue(maxsize=1000)
            self._shutdown = threading.Event()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

        def emit(self, record):
            try:
                self._msg_queue.put_nowait(logging.makeLogRecord(record.__dict__))
            except queue.Full:
                pass

        def _worker(self):
            while not self._shutdown.is_set():
                try:
                    msg = self._msg_queue.get(timeout=0.3)
                    super().emit(msg)
                except queue.Empty:
                    pass

        def close(self):
            self._shutdown.set()
            if self._thread.is_alive():
                self._thread.join(timeout=1)
            super().close()

    class MaskFilter(logging.Filter):
        user_path = os.path.expanduser('~')

        def filter(self, record):
            if isinstance(record.msg, str):
                record.msg = record.msg.replace(self.user_path, '~')
                if record.name != 'aiohttp.access':
                    record.msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[masked IP address]', record.msg)
                if record.name == 'danmaku':
                    record.msg = re.sub(r'as uid=[1-9]\d*', 'as uid=***', record.msg)
                elif record.name == 'config':
                    if 'cache_proxy' in record.msg:
                        record.msg = re.sub(r'//.*', '//***', record.msg)
                    elif 'uid' in record.msg:
                        record.msg = re.sub(r'[1-9]\d*', '***', record.msg)
                    elif '_cookie_cloud_salt' in record.msg:
                        record.msg = re.sub(r'=.*', '= ***', record.msg)
            return True

    def create_file_handler(filename: str, level: int = logging.DEBUG, max_mb: int = 5, backup_count: int = 3):
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, filename),
            maxBytes=max_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(MaskFilter())
        return file_handler

    def create_console_handler(level: int):
        console_handler = ThreadedStreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        return console_handler

    def redirect_logging(logger_name: str, filename: str | None, console_level: int | None = None, **kwargs):
        logger = logging.getLogger(logger_name)
        logger.propagate = False  # Prevent logs from propagating to root logger
        if filename:
            logger.addHandler(create_file_handler(filename, **kwargs))
        if console_level is not None:
            logger.addHandler(create_console_handler(console_level))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.addHandler(create_console_handler(logging.DEBUG if verbose else logging.INFO))
    root_logger.addHandler(create_file_handler('backend_main.log'))

    redirect_logging('aiosqlite', 'sql.log', console_level=logging.WARNING)
    redirect_logging('tortoise.db_client', 'sql.log', console_level=logging.WARNING)
    redirect_logging('aiohttp.access', 'http.log', console_level=logging.WARNING)
    redirect_logging('browser', 'browser.log', console_level=logging.DEBUG if verbose else logging.INFO)
    redirect_logging('merger_verbose', None, console_level=logging.DEBUG if verbose else None)
    redirect_logging('rookie.common.paths', None, console_level=None)
