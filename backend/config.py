from __future__ import annotations
import json
import logging
import typing
import types
import os
import sys
import dataclasses
import ssl
import contextlib

import aiohttp
import certifi

logger = logging.getLogger('config')


def get_basedir():
    """Get the basedir path that works both in development and bundled mode"""
    if getattr(sys, 'frozen', False):
        # Running in PyInstaller bundle
        return os.path.join(sys._MEIPASS, 'backend')  # type: ignore[attr-defined]
    else:
        # Running in normal Python environment
        return os.path.join(os.path.dirname(__file__))


def create_connector() -> aiohttp.TCPConnector:
    """Create aiohttp TCP connector using certifi ssl context"""
    return aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))


def create_aiohttp_session(**kwargs) -> aiohttp.ClientSession:
    """Create aiohttp with connector using certifi ssl context"""
    return aiohttp.ClientSession(connector=create_connector(), **kwargs)


@contextlib.asynccontextmanager
async def aiohttp_session(**kwargs):
    async with create_aiohttp_session(**kwargs) as session:
        yield session


def parse_types(cls: type, allowed_types: list[type] = [int, float, str, bool, tuple, type(None)]):
    field_types: dict[str, type | tuple[type, ...]] = {}
    for k, v in typing.get_type_hints(cls, globalns=globals(), localns=locals()).items():
        if v in allowed_types:
            field_types[k] = v
        elif typing.get_origin(v) in allowed_types:
            field_types[k] = typing.get_origin(v)  # type: ignore
        elif typing.get_origin(v) in (typing.Union, types.UnionType):
            field_types[k] = typing.get_args(v)
            if not all(t in allowed_types for t in field_types[k]):  # type: ignore
                raise ValueError(
                    f'{k} as union type {v} contains invalid types: {field_types[k]}, only {allowed_types} are allowed')
        else:
            raise ValueError(f'Invalid type hint for {k}: {v}, only {allowed_types} are allowed')
    return field_types


class DataConfig():
    '''Abstract base class for providing save on assignment management
    subclasses follow typical dataclass usage to use helper methods defined here
    Allowed field types are int, float, str, bool, tuple, None, and their Unions'''

    def __post_init__(self):
        self._init = False
        self._config_fn: str | None = None
        self._prefix: str | None = None
        self._parent: DataConfig | None = None
        self._sub_configs: dict[str, DataConfig] = {}
        self._fields: dict[str, type | tuple[type, ...]] = self.get_fields()
        self._suppress_save = False
        logger.debug(f'init {self.__class__.__name__} with fields: {self._fields}')

    def validate(self, key: str, value: typing.Any):
        return value

    def add_sub_config(self, prefix: str, sub_config: DataConfig) -> DataConfig:
        assert prefix not in self._fields, f'sub config prefix {prefix} conflicts with field name'
        if prefix in self._sub_configs:
            logger.warning(f'sub config {prefix} already exists, overwriting')
        self._sub_configs[prefix] = sub_config
        sub_config._parent = self
        sub_config._prefix = prefix
        return sub_config

    def remove_sub_config(self, prefix: str):
        self._sub_configs.pop(prefix)
        self.save_config()

    @classmethod
    def get_fields(cls):
        return parse_types(cls)

    @classmethod
    def _assert_dataclass(cls):
        assert dataclasses.is_dataclass(cls), f'{cls.__name__} must be decorated with @dataclass'

    @classmethod
    def create_root(cls, config_fn: str):
        cls._assert_dataclass()
        config = cls()
        config._config_fn = config_fn
        config.load_config()
        return config

    @classmethod
    def create_sub(cls, parent: DataConfig, prefix: str, *args, **kwargs):
        cls._assert_dataclass()
        sub_config = cls(*args, **kwargs)
        parent.add_sub_config(prefix, sub_config)
        sub_config.load_config()
        return sub_config

    @property
    def path(self) -> str:
        if self._parent:
            return f'{self._parent.path}.{self._prefix}'
        return 'root'

    @property
    def sub_configs(self):
        return self._sub_configs

    def _load_from_file(self) -> dict:
        if self._config_fn:
            with open(self._config_fn, 'rt', encoding='utf-8') as f:
                return dict(json.load(f))
        else:
            assert self._parent, f'sub config {self._prefix} must have a parent'
            return self._parent._load_from_file()[self._prefix]

    def load_config(self):
        self._init = False
        try:
            data = self._load_from_file()
        except FileNotFoundError:
            logger.debug(f'[{self.path}] config file {self._config_fn or ""} not found')
            data = {}
        except Exception as e:
            logger.error(f'failed to load config from {self._config_fn}: {e}')
            data = {}
        for key, value in data.items():
            if key in self._fields:
                logger.debug(f'"{self.path}" load {key} = {value}')
                setattr(self, key, value)
        self._init = True

    @contextlib.contextmanager
    def suppress_save(self):
        assert not self._parent, 'suppress_save can only be used on root config'
        assert not self._suppress_save, 'suppress_save is already active'
        self._suppress_save = True
        try:
            yield
        finally:
            self._suppress_save = False

    def save_config(self):
        if self._suppress_save:
            logger.warning('save is suppressed, not writing should have been performed', stack_info=True)
            return
        if self._parent:
            self._parent.save_config()
        else:
            assert self._config_fn, 'root config must have a config file'
            with open(f'{self._config_fn}.tmp', 'wt', encoding='utf-8') as f:
                json.dump(self.as_dict(recursive=True), f, indent=4, ensure_ascii=False)
            os.replace(f'{self._config_fn}.tmp', self._config_fn)

    def reset_config(self, recursive: bool = False, exclude: typing.Iterable[str] = ()):
        assert not (exclude and recursive), 'exclude and recursive cannot be both set'
        default_config = self.__class__()
        for key in self._fields:
            if key in exclude:
                continue
            setattr(self, key, getattr(default_config, key))
        if recursive:
            for sub_config in self._sub_configs.values():
                sub_config.reset_config(recursive=True)

    def as_dict(self, recursive: bool = False, exclude_keys: typing.Iterable[str] = ()):
        assert dataclasses.is_dataclass(self)
        data = {k: v for k, v in dataclasses.asdict(self).items() if k not in exclude_keys}
        if recursive:
            if exclude_keys:
                logger.warning('exclude_keys only applies to the current level')
            return {**data,
                    **{k: v.as_dict(recursive=True) for k, v in self._sub_configs.items()}}
        else:
            return data

    def update(self, data):
        if not isinstance(data, dict):
            raise ValueError(f'[{self.path}] update data must be a dict, got {type(data)}: {data}')
        for key, value in data.items():
            if key in self._fields:
                logger.debug(f'[{self.path}] update {key} = {value}')
                setattr(self, key, value)
            elif key in self._sub_configs:
                self._sub_configs[key].update(value)
            else:
                logger.warning(f'[{self.path}] update data contains invalid key: {key}')

    def __setattr__(self, name, value):
        if name not in getattr(self, '_fields', {}):
            return super().__setattr__(name, value)

        value = self.validate(name, value)

        if isinstance(value, list):
            value = tuple(value)

        if not isinstance(value, self._fields[name]):
            logger.warning(f'Invalid type for {name}: expected {self._fields[name]}, got {type(value)}. Ignoring update.')
            return

        super().__setattr__(name, value)
        if self._init:
            self.save_config()
