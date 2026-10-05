"""气泡类型判定单测（代码块 / 图片 / 音视频 / 压缩包 / 链接 等差异化样式）。"""

from __future__ import annotations

from copyama.core.tokenizer import BubbleKind, classify_bubble, looks_like_code, split_bubbles


def test_links_and_emails():
    assert classify_bubble("https://example.com/a?b=1") is BubbleKind.LINK
    assert classify_bubble("www.qq.com") is BubbleKind.LINK
    assert classify_bubble("me@example.com") is BubbleKind.EMAIL


def test_file_kinds_by_extension():
    assert classify_bubble(r"C:\Users\a\photo.PNG") is BubbleKind.IMAGE
    assert classify_bubble("D:/video/demo.mp4") is BubbleKind.MEDIA
    assert classify_bubble("/tmp/backup.zip") is BubbleKind.ARCHIVE
    assert classify_bubble("/home/me/report.docx") is BubbleKind.PATH
    assert classify_bubble(r"C:\Windows\notepad.exe") is BubbleKind.PATH


def test_code_detection():
    assert classify_bubble("def foo():\n    return 1") is BubbleKind.CODE
    assert classify_bubble("```python\nprint(1)\n```") is BubbleKind.CODE
    assert classify_bubble("const x = 1;") is BubbleKind.CODE
    assert looks_like_code('{"a": 1}') is True
    # 普通路径与句子不应误判为代码
    assert looks_like_code(r"C:\Users\a\photo.png") is False
    assert looks_like_code("今天天气不错") is False


def test_numbers_and_plain_text():
    assert classify_bubble("¥88.00") is BubbleKind.NUMBER
    assert classify_bubble("-3.14") is BubbleKind.NUMBER
    assert classify_bubble("你好世界") is BubbleKind.TEXT
    assert classify_bubble("   ") is BubbleKind.TEXT


def test_split_bubbles_pairs_kind_with_text():
    pairs = split_bubbles("访问 https://a.com 打开 C:\\a\\b.png")
    kinds = dict(pairs)
    assert kinds["https://a.com"] is BubbleKind.LINK
    assert kinds[r"C:\a\b.png"] is BubbleKind.IMAGE
    assert [t for t, _ in pairs][0] == "访问"


def test_code_with_path_not_misclassified_as_image():
    snippet = "def save(path):\n    return open(path + '.png').read()"
    assert classify_bubble(snippet) is BubbleKind.CODE
