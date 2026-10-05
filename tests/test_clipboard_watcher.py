"""剪贴板监听：内容过滤与事件分发（注入 reader，跨平台可测）。"""

from __future__ import annotations

import json
import sys

import pytest

from copyama.config import Config
from copyama.core.clipboard import ClipboardWatcher, build_clip
from copyama.core.models import ClipType


# —— build_clip 过滤规则 ——
def test_text_clip_ok():
    clip = build_clip(("text", "hello"), Config())
    assert clip is not None
    assert clip.type is ClipType.TEXT
    assert clip.content == "hello"
    assert clip.preview == "hello"


def test_text_blank_or_short_filtered():
    assert build_clip(("text", "   "), Config()) is None
    assert build_clip(("text", "abc"), Config(min_text_length=5)) is None
    assert build_clip(("text", "abcdef"), Config(min_text_length=5)) is not None


def test_text_capture_disabled():
    assert build_clip(("text", "hello"), Config(capture_text=False)) is None


def test_image_size_recorded_and_gate():
    clip = build_clip(("image", b"x" * 2048), Config())
    assert clip is not None
    assert clip.type is ClipType.IMAGE
    assert clip.size_bytes == 2048
    assert build_clip(("image", b"x"), Config(capture_image=False)) is None


def test_image_over_limit_filtered():
    big = b"x" * (1024 * 1024 + 1)
    assert build_clip(("image", big), Config(max_image_mb=1)) is None


def test_file_clip_and_kind_exclusion():
    payload = json.dumps(["/tmp/report.pdf"])
    clip = build_clip(("file", payload), Config())
    assert clip is not None
    assert clip.type is ClipType.FILE
    assert clip.file_paths == ["/tmp/report.pdf"]
    assert clip.kind  # 已按首个文件推断类型

    assert build_clip(("file", payload), Config(excluded_kinds=[clip.kind])) is None
    assert build_clip(("file", payload), Config(capture_files=False)) is None


def test_file_clip_bad_payload():
    assert build_clip(("file", "[]"), Config()) is None
    assert build_clip(("file", "{not json"), Config()) is None
    assert build_clip(("file", '{"a": 1}'), Config()) is None


def test_unknown_and_none():
    assert build_clip(None, Config()) is None
    assert build_clip(("weird", "x"), Config()) is None


# —— 事件分发 ——
def test_handle_update_invokes_callback():
    seen = []
    watcher = ClipboardWatcher(
        lambda clip, blob: seen.append((clip, blob)),
        Config(),
        reader=lambda: ("text", "hello"),
    )
    clip = watcher.handle_update()
    assert clip is not None
    assert len(seen) == 1
    assert seen[0][0] is clip
    assert seen[0][1] is None


def test_handle_update_passes_image_blob():
    blobs = []
    watcher = ClipboardWatcher(
        lambda clip, blob: blobs.append(blob),
        Config(),
        reader=lambda: ("image", b"PNGDATA"),
    )
    watcher.handle_update()
    assert blobs == [b"PNGDATA"]


def test_pause_blocks_capture():
    seen = []
    watcher = ClipboardWatcher(
        lambda clip, blob: seen.append(clip), Config(), reader=lambda: ("text", "hello")
    )
    watcher.handle_update()
    assert len(seen) == 1

    watcher.pause()
    assert watcher.paused is True
    assert watcher.handle_update() is None
    assert len(seen) == 1

    watcher.resume()
    assert watcher.paused is False
    watcher.handle_update()
    assert len(seen) == 2


def test_filtered_content_does_not_callback():
    seen = []
    watcher = ClipboardWatcher(
        lambda clip, blob: seen.append(clip),
        Config(capture_text=False),
        reader=lambda: ("text", "hello"),
    )
    assert watcher.handle_update() is None
    assert seen == []


def test_reader_oserror_is_swallowed():
    def boom():
        raise OSError("剪贴板被其它程序占用")

    watcher = ClipboardWatcher(lambda clip, blob: None, Config(), reader=boom)
    assert watcher.handle_update() is None


def test_callback_exception_does_not_propagate():
    def bad(_clip, _blob):
        raise RuntimeError("入库失败")

    watcher = ClipboardWatcher(bad, Config(), reader=lambda: ("text", "hello"))
    assert watcher.handle_update() is not None


def test_poll_once():
    watcher = ClipboardWatcher(lambda clip, blob: None, Config(), reader=lambda: ("text", "hi"))
    assert watcher.poll_once().content == "hi"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 上会真去建消息窗口")
def test_start_returns_false_on_other_platforms():
    watcher = ClipboardWatcher(lambda clip, blob: None, Config())
    assert watcher.start() is False
    assert watcher.running is False
    watcher.stop()  # 未启动时调用不应抛异常
