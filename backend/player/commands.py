import dataclasses
import typing
import functools

from ..config import parse_types

from .events import BaseEvent


@dataclasses.dataclass
class BaseCmd:
    value: typing.Any

    def __post_init__(self):
        if not isinstance(self.value, self.allowed_value_type()):
            raise ValueError(f'Expected cmd value type {self.allowed_value_type()}, got {type(self.value).__name__}: "{self.value}"')

    def asdict(self) -> dict:
        return {
            'cmd': self.cmd_key(),
            **dataclasses.asdict(self),
        }

    @classmethod
    def cmd_key(cls) -> str:
        assert cls.__name__.endswith('Cmd')
        name = cls.__name__[:-len('Cmd')]
        return '-'.join(''.join(' ' + c.lower() if c.isupper() else c for c in name).split())

    @property
    def type(self) -> str:
        return self.cmd_key()

    @classmethod
    @functools.cache
    def allowed_value_type(cls) -> typing.Type | tuple[typing.Type, ...]:
        return parse_types(cls, allowed_types=[bool, int, float, str, tuple, type(None), BaseEvent])['value']


player_commands: dict[str, typing.Type[BaseCmd]] = {}
T = typing.TypeVar('T', bound=BaseCmd)


def register_command(cmd: typing.Type[T]) -> typing.Type[T]:
    player_commands[cmd.cmd_key()] = cmd
    return cmd


@register_command
@dataclasses.dataclass
class PausedCmd(BaseCmd):
    """
    value: bool, the new paused state
    """
    value: bool


@register_command
@dataclasses.dataclass
class NextCmd(BaseCmd):
    """
    value: int, the playlist id of the song to skip
    """
    value: int


@register_command
@dataclasses.dataclass
class MoveToTopCmd(BaseCmd):
    """
    value: int, the playlist id of the song to move to the top
    """
    value: int


@register_command
@dataclasses.dataclass
class MoveToEndCmd(BaseCmd):
    """
    value: int, the playlist id of the song to move to the end
    """
    value: int


@register_command
@dataclasses.dataclass
class MoveDownCmd(BaseCmd):
    """
    value: int, the playlist id of the song to move down
    """
    value: int


@register_command
@dataclasses.dataclass
class SeekCmd(BaseCmd):
    """
    value: int, the progress in seconds to change to
    """
    value: int


@register_command
@dataclasses.dataclass
class ProgressCmd(BaseCmd):
    """
    value: int, the progress in seconds to store
    """
    value: int


@register_command
@dataclasses.dataclass
class CancelCmd(BaseCmd):
    """
    value: int, the playlist id of the song to cancel
    """
    value: int


@register_command
@dataclasses.dataclass
class StatusCmd(BaseCmd):
    value: None = None


@register_command
@dataclasses.dataclass
class ShowEventCmd(BaseCmd):
    value: BaseEvent

    def asdict(self) -> dict:
        return {
            **super().asdict(),
            'value': self.value.asdict(),
        }


@register_command
@dataclasses.dataclass
class SetIsFallbackCmd(BaseCmd):
    """
    value: int, the playlist id to set the is_fallback to True
    """
    value: int


@register_command
@dataclasses.dataclass
class UnsetIsFallbackCmd(BaseCmd):
    """
    value: int, the playlist id to set the is_fallback to False
    """
    value: int


@register_command
@dataclasses.dataclass
class VolumeReportCmd(BaseCmd):
    """
    value: float, player volume
    """
    value: float | int
