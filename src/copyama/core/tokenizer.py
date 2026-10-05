"""智能气泡切分：把一段文本按语义切成可单独点选的片段。

设计目标（对应需求「选词粘贴」）：
    "访问 https://a.com 并联系 me@x.com，金额 ¥88.00，你好世界"
    →  ["访问", "https://a.com", "并联系", "me@x.com", "，", "金额", "¥88.00", "，", "你好世界"]
    其中标点默认丢弃，URL / 邮箱 / 路径 / 数字各自成泡，连续英文串合成一泡。

纯逻辑、可单测；不引入分词库（可选 jieba 增强见 README §9）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TokenKind(str, Enum):
    URL = "url"
    EMAIL = "email"
    PATH = "path"
    NUMBER = "number"
    ENGLISH = "english"
    CJK = "cjk"
    OTHER = "other"


@dataclass(frozen=True)
class Token:
    """一个气泡片段。start/end 为原文下标，便于「复制片段」时定位。"""

    kind: TokenKind
    text: str
    start: int
    end: int


# 匹配优先级：结构化信息在前，通用文本在后。
_PATTERN = re.compile(
    r"""
      (?P<url>(?:https?|ftp)://[^\s<>"'\u3000-\u303f\uff00-\uffef）)】\]]+)
    | (?P<www>www\.[^\s<>"'\u3000-\u303f\uff00-\uffef）)】\]]+)
    | (?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})
    | (?P<winpath>[A-Za-z]:\\[^\s<>"'|*?\r\n]+)
    | (?P<unixpath>/(?:[\w.\-]+/)+[\w.\-]*)
    | (?P<number>[¥$€£]?-?\d[\d,.]*%?)
    | (?P<cjk>[\u4e00-\u9fff]+)
    | (?P<english>[A-Za-z][A-Za-z0-9_'\u2019-]*(?:[ \t]+[A-Za-z0-9_'\u2019-]+)*)
    """,
    re.VERBOSE,
)

_KIND_BY_GROUP: dict[str, TokenKind] = {
    "url": TokenKind.URL,
    "www": TokenKind.URL,
    "email": TokenKind.EMAIL,
    "winpath": TokenKind.PATH,
    "unixpath": TokenKind.PATH,
    "number": TokenKind.NUMBER,
    "cjk": TokenKind.CJK,
    "english": TokenKind.ENGLISH,
}

# 中文 / 全角标点，仅作分隔，不产出气泡
_SEPARATOR = re.compile(r"[\s\u3000-\u303f\uff00-\uffef]+")


def split_tokens(text: str) -> list[Token]:
    """把文本切成气泡片段；标点与空白不产出片段。"""
    if not text:
        return []
    tokens: list[Token] = []
    for m in _PATTERN.finditer(text):
        kind = _KIND_BY_GROUP.get(m.lastgroup or "", TokenKind.OTHER)
        seg = m.group().strip()
        if seg:
            tokens.append(Token(kind=kind, text=seg, start=m.start(), end=m.end()))
    return tokens


def bubbles(text: str) -> list[str]:
    """便捷函数：只要气泡文本列表。"""
    return [t.text for t in split_tokens(text)]


def merge_short_cjk(
    tokens: list[Token], min_len: int = 2, max_gap: int = 1
) -> list[Token]:
    """把被单个标点打断的短中文片段合并（如「金额」「￥」之间的换行）。

    仅合并相邻 CJK 片段且中间间隔不超过 ``max_gap`` 个字符，避免贪心合并成一大块。
    """
    if not tokens:
        return []
    merged: list[Token] = [tokens[0]]
    for cur in tokens[1:]:
        prev = merged[-1]
        gap = cur.start - prev.end
        if (
            prev.kind is TokenKind.CJK
            and cur.kind is TokenKind.CJK
            and (len(prev.text) < min_len or len(cur.text) < min_len)
            and gap <= max_gap
        ):
            merged[-1] = Token(
                kind=TokenKind.CJK,
                text=f"{prev.text}{cur.text}",
                start=prev.start,
                end=cur.end,
            )
        else:
            merged.append(cur)
    return merged


def is_separator_only(text: str) -> bool:
    """判断一段文本是否只由分隔符构成（供 UI 决定是否跳过）。"""
    return bool(text) and _SEPARATOR.fullmatch(text) is not None

class BubbleKind(str, Enum):
    """气泡的展示类型：决定 UI 用哪种胶囊样式（风格统一，仅细节不同）。"""

    LINK = "link"
    EMAIL = "email"
    IMAGE = "image"
    MEDIA = "media"
    ARCHIVE = "archive"
    PATH = "path"
    CODE = "code"
    NUMBER = "number"
    TEXT = "text"


# 扩展名分组：决定文件类气泡的图标与样式细节
IMAGE_EXT = frozenset(
    "png jpg jpeg gif bmp webp svg ico tif tiff heic avif raw psd".split()
)
MEDIA_EXT = frozenset(
    "mp4 mkv mov avi wmv flv webm m4v mpg mpeg ts "
    "mp3 wav flac aac ogg m4a wma opus mid".split()
)
ARCHIVE_EXT = frozenset(
    "zip rar 7z tar gz bz2 xz zst iso cab tgz".split()
)

_CODE_HINTS = ("{", "}", ";", "=>", "==", "def ", "class ", "import ", "function ",
               "</", "();", "!=", "return ", "#include")
_CODE_HEAD = re.compile(
    r"^\s*(def|class|import|from|function|const|let|var|public|private|protected|"
    r"SELECT|INSERT|UPDATE|DELETE|#include|package)\b",
    re.IGNORECASE,
)
_PATHISH = re.compile(r"[\\/]")


def looks_like_code(text: str) -> bool:
    """启发式判断是否像代码片段（宁可漏判，不误判普通路径/句子）。"""
    if "```" in text:
        return True
    stripped = text.strip()
    if _CODE_HEAD.match(stripped):
        return True
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) >= 2:
        indented = sum(1 for ln in lines if ln[:1] in (" ", "\t"))
        if indented and any(h in text for h in _CODE_HINTS):
            return True
    if any(h in text for h in (";", "{", "}", "=>", "()")):
        if stripped.startswith(("{", "[", "(", "<", "@")) or stripped.endswith(
            (";", "}", ")", ":", "=>")
        ):
            return True
    return False


def _ext_of(text: str) -> str:
    tail = text.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in tail:
        return ""
    return tail.rsplit(".", 1)[-1].lower()


def classify_bubble(text: str) -> BubbleKind:
    """给一个气泡片段判定展示类型。"""
    t = text.strip()
    if not t:
        return BubbleKind.TEXT
    low = t.lower()
    if low.startswith(("http://", "https://", "ftp://", "www.")):
        return BubbleKind.LINK
    if _FULL_EMAIL.match(t):
        return BubbleKind.EMAIL
    if looks_like_code(t):
        return BubbleKind.CODE
    if _PATHISH.search(t) or _ext_of(t):
        ext = _ext_of(t)
        if ext in IMAGE_EXT:
            return BubbleKind.IMAGE
        if ext in MEDIA_EXT:
            return BubbleKind.MEDIA
        if ext in ARCHIVE_EXT:
            return BubbleKind.ARCHIVE
        if _PATHISH.search(t):
            return BubbleKind.PATH
    if _FULL_NUMBER.match(t):
        return BubbleKind.NUMBER
    return BubbleKind.TEXT


_FULL_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_FULL_NUMBER = re.compile(r"[¥$€£]?-?\d[\d,.]*%?")


def split_bubbles(text: str) -> list[tuple[str, BubbleKind]]:
    """返回 (片段, 类型) 列表，供 UI 渲染不同样式的胶囊。"""
    return [(tok.text, classify_bubble(tok.text)) for tok in split_tokens(text)]
