"""文本清洗单测：纯逻辑，任意平台可跑（pytest -q）。"""

from __future__ import annotations

from copyama.core.text_cleaner import (
    clean,
    collapse_blank_lines,
    collapse_spaces,
    normalize_newlines,
    strip_control_chars,
)


def test_normalize_newlines():
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"


def test_strip_control_chars():
    assert strip_control_chars("a\x00b\x07c") == "abc"
    assert strip_control_chars("a\tb\nc") == "a\tb\nc"  # tab / 换行保留


def test_collapse_spaces():
    assert collapse_spaces("a   b\t\tc   ") == "a b c"
    assert collapse_spaces("  lead  keep") == " lead keep"


def test_collapse_blank_lines():
    assert collapse_blank_lines("a\n\n\n\nb") == "a\n\nb"


def test_clean_is_idempotent():
    dirty = "  Hello\r\n\r\n\r\n\r\nWorld   !  \x00 "
    once = clean(dirty)
    assert once == clean(once)
    assert once == "Hello\n\nWorld !"


def test_clean_empty():
    assert clean("") == ""
