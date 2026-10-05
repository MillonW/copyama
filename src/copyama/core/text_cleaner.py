"""文本清洗：纯函数实现，无平台依赖，可跨平台单测。

约定：所有函数保证幂等，即 ``f(f(x)) == f(x)``。
"""

from __future__ import annotations

import re

# 控制字符（保留 \n \t，其余剔除，避免终端/渲染异常）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 行内连续空白（不含换行）
_INLINE_SPACES = re.compile(r"[ \t\u3000]{2,}")
# 连续空行（>=2 个换行）
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_newlines(text: str) -> str:
    """统一换行为 \\n（兼容 Windows / 旧 Mac 换行）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_control_chars(text: str) -> str:
    """剔除不可见控制字符。"""
    return _CONTROL_CHARS.sub("", text)


def collapse_spaces(text: str) -> str:
    """行内连续空格/制表符压为 1 个，并去掉每行尾随空白。"""
    lines = [_INLINE_SPACES.sub(" ", line).rstrip() for line in text.split("\n")]
    return "\n".join(lines)


def collapse_blank_lines(text: str) -> str:
    """连续空行压缩为最多 1 个空行。"""
    return _BLANK_LINES.sub("\n\n", text)


def strip_outer_blank(text: str) -> str:
    """去掉首尾空白与空白行。"""
    return text.strip()


def clean(text: str) -> str:
    """一键清洗：统一换行 → 去控制字符 → 压空格 → 压空行。

    保持幂等；对空串安全。
    """
    if not text:
        return ""
    text = normalize_newlines(text)
    text = strip_control_chars(text)
    text = collapse_spaces(text)
    text = collapse_blank_lines(text)
    return strip_outer_blank(text)
