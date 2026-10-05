"""平台层纯逻辑单测：格式优先级、DROPFILES 解析、DIB→BMP 拼头。

这些函数不触碰任何系统调用，可在任意平台运行；真正的剪贴板读写只在 Windows
可用，此处只用平台守卫验证「不在 Windows 时明确失败」。
"""

from __future__ import annotations

import struct
import sys

import pytest

from copyama.platform import win32_clipboard as wc


class TestPickFormat:
    def test_file_wins_over_everything(self):
        assert wc.pick_format([wc.CF_UNICODETEXT, wc.CF_DIBV5, wc.CF_HDROP]) == "file"

    def test_image_beats_text(self):
        assert wc.pick_format([wc.CF_UNICODETEXT, wc.CF_DIB]) == "image"
        assert wc.pick_format([wc.CF_UNICODETEXT, wc.CF_DIBV5]) == "image"

    def test_text_only(self):
        assert wc.pick_format([wc.CF_UNICODETEXT]) == "text"

    def test_empty_and_unknown(self):
        assert wc.pick_format([]) is None
        assert wc.pick_format([999, 1000]) is None


class TestParseHdrop:
    @staticmethod
    def _hdrop(paths: list[str], wide: bool = True) -> bytes:
        encoding = "utf-16-le" if wide else "latin-1"
        blob = ("\0".join(paths) + "\0\0").encode(encoding)
        return struct.pack("<Iiiii", 20, 0, 0, 0, int(wide)) + blob

    def test_wide_paths(self):
        data = self._hdrop(["C:\\a.txt", "D:\\目录\\b.png"])
        assert wc.parse_hdrop_paths(data) == ["C:\\a.txt", "D:\\目录\\b.png"]

    def test_ansi_paths(self):
        assert wc.parse_hdrop_paths(self._hdrop(["C:\\a.txt"], wide=False)) == ["C:\\a.txt"]

    def test_single_path(self):
        assert wc.parse_hdrop_paths(self._hdrop(["C:\\only.txt"])) == ["C:\\only.txt"]

    def test_too_short(self):
        assert wc.parse_hdrop_paths(b"abc") == []

    def test_offset_beyond_buffer(self):
        assert wc.parse_hdrop_paths(struct.pack("<Iiiii", 9999, 0, 0, 0, 1)) == []


class TestDibToBmp:
    @staticmethod
    def _dib(*, bits: int = 24, compression: int = 0, header: int = 40, colors: int = 0) -> bytes:
        return struct.pack(
            "<IiiHHIIiiII", header, 2, 2, 1, bits, compression, 16, 2835, 2835, colors, 0
        ) + b"\0" * 16

    def test_basic_header(self):
        dib = self._dib()
        bmp = wc.dib_to_bmp(dib)
        assert bmp[:2] == b"BM"
        assert struct.unpack_from("<I", bmp, 2)[0] == 14 + len(dib)
        assert struct.unpack_from("<I", bmp, 10)[0] == 14 + 40

    def test_8bit_palette_offset(self):
        dib = self._dib(bits=8, colors=256)
        bmp = wc.dib_to_bmp(dib)
        assert struct.unpack_from("<I", bmp, 10)[0] == 14 + 40 + 256 * 4

    def test_bitfields_extra_masks(self):
        dib = self._dib(compression=3)
        bmp = wc.dib_to_bmp(dib)
        assert struct.unpack_from("<I", bmp, 10)[0] == 14 + 40 + 12

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            wc.dib_to_bmp(b"\0" * 10)


class TestPlatformGuard:
    @pytest.mark.skipif(sys.platform == "win32", reason="Windows 上真实可用")
    def test_read_clipboard_requires_windows(self):
        with pytest.raises(OSError):
            wc.read_clipboard()

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows 上真实可用")
    def test_foreground_info_is_soft_on_other_platforms(self):
        assert wc.get_foreground_info() == (None, None, None, None)
