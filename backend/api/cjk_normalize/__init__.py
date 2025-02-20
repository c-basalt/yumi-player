import string

from .ja import cn_ja

char_map = {}

for line in cn_ja.splitlines():
    cn_char, ja_char = line.split()
    char_map[ja_char] = cn_char

for char in string.ascii_letters:
    char_map[char] = char.lower()


def cjk_norm(text: str) -> str:
    """Normalize CJK characters in to zh_CN characters and ascii letters to lowercase"""
    return ''.join(char_map.get(char, char) for char in text)
