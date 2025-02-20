import re
import dataclasses

from ..config import DataConfig


@dataclasses.dataclass
class UnsheildRuleConfig(DataConfig):
    keywords: tuple[str, ...] = ('少nv,少女', )

    def __post_init__(self):
        super().__post_init__()
        self._keyword_map: dict[str, str] | None = None

    def validate(self, key: str, value):
        if key == 'keywords':
            self._keyword_map = None
            return tuple(w for w in value if w.count(',') == 1 and w[0] != ',')
        return value

    @property
    def keyword_map(self) -> dict[str, str]:
        if self._keyword_map is None:
            self._keyword_map = {k: v for k, v in (keyword.split(',', 1) for keyword in self.keywords) if k}
        return self._keyword_map


SPACER_CHARS = '\U000e0020\u0592'


def unshield(text: str, rules: UnsheildRuleConfig) -> str:
    text = re.sub(rf'[{SPACER_CHARS}]+', '', text)

    for match in re.finditer(rf'({"|".join(rules.keyword_map)})', text):
        text = text.replace(match.group(0), rules.keyword_map.get(match.group(0), match.group(0)))
    return text
