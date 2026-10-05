"""气泡切分单测。"""

from __future__ import annotations

from copyama.core.tokenizer import (
    TokenKind,
    bubbles,
    is_separator_only,
    split_tokens,
)


def test_bubbles_mixed_content():
    text = "访问 https://example.com 并联系 me@x.com，金额 ¥88.00，你好世界"
    assert bubbles(text) == [
        "访问",
        "https://example.com",
        "并联系",
        "me@x.com",
        "金额",
        "¥88.00",
        "你好世界",
    ]


def test_english_phrase_stays_one_bubble():
    assert bubbles("hello world foo_bar") == ["hello world foo_bar"]


def test_windows_path_is_one_bubble():
    p = r"C:\Users\me\a.txt"
    assert bubbles(p) == [p]


def test_unix_path_is_one_bubble():
    assert bubbles("/home/user/a.txt") == ["/home/user/a.txt"]


def test_kinds_are_classified():
    toks = split_tokens("访问 https://a.com")
    assert [(t.kind, t.text) for t in toks] == [
        (TokenKind.CJK, "访问"),
        (TokenKind.URL, "https://a.com"),
    ]


def test_empty_input():
    assert bubbles("") == []
    assert split_tokens("") == []


def test_separator_only():
    assert is_separator_only("，。 ") is True
    assert is_separator_only("a") is False
    assert is_separator_only("") is False
