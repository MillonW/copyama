"""Windows 剪贴板读写：格式优先级与解析。

格式优先级：CF_HDROP(文件) → CF_DIBV5/CF_DIB(图片) → CF_UNICODETEXT(文本)。

实现全部走 ``ctypes``，不依赖 pywin32，保持安装包轻量。
所有 win32 调用延迟导入 / 延迟取库，保证本模块在非 Windows 平台可被 import，
真正调用时若不在 Windows 则抛 ``OSError``（不静默失败、不假装成功）。

其中「格式优先级选择」「DROPFILES 解析」「DIB→BMP 包头拼接」为纯逻辑，
不触碰任何系统调用，可在任意平台单测。
"""

from __future__ import annotations

import struct
import sys
from collections.abc import Iterable

# 剪贴板格式（Win32 常量）
CF_UNICODETEXT = 13
CF_DIB = 8
CF_DIBV5 = 17
CF_HDROP = 15

# OpenClipboard 失败时的重试退避（毫秒）
RETRY_BACKOFF_MS = (20, 50, 100)

# 图片原图落盘统一格式
IMAGE_FORMAT = "PNG"


# ——————————————————————————————————————————————
# 纯逻辑（跨平台可测）
# ——————————————————————————————————————————————
def pick_format(available: Iterable[int]) -> str | None:
    """按优先级从可用格式中挑一个，返回 ``"file" | "image" | "text" | None``。"""
    formats = set(available)
    if CF_HDROP in formats:
        return "file"
    if CF_DIBV5 in formats or CF_DIB in formats:
        return "image"
    if CF_UNICODETEXT in formats:
        return "text"
    return None


def parse_hdrop_paths(data: bytes) -> list[str]:
    """解析 CF_HDROP 的 HGLOBAL 内容（DROPFILES 结构）为路径列表。

    DROPFILES 布局：``DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide;`` 之后紧跟
    以 NUL 分隔（双 NUL 结尾）的文件名串。fWide 非 0 时按 UTF-16LE 解码。
    """
    if len(data) < 20:
        return []
    offset = struct.unpack_from("<I", data, 0)[0]
    wide = struct.unpack_from("<i", data, 16)[0]
    if offset >= len(data):
        return []
    blob = data[offset:]
    encoding = "utf-16-le" if wide else ("mbcs" if sys.platform == "win32" else "latin-1")
    text = blob.decode(encoding, "replace")
    return [p for p in text.split("\0") if p]


def dib_to_bmp(dib: bytes) -> bytes:
    """给裸 DIB（BITMAPINFOHEADER 起头）补上 14 字节 BMP 文件头。

    剪贴板里的 CF_DIB/CF_DIBV5 不含文件头，Pillow 只认 BMP，故需补齐。
    像素数据偏移量要算上头部、调色板与（BI_BITFIELDS 时）掩码。
    """
    if len(dib) < 40:
        raise ValueError("DIB 数据过短")
    header_size = struct.unpack_from("<I", dib, 0)[0]
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    compression = struct.unpack_from("<I", dib, 16)[0]

    palette_bytes = 0
    if bit_count <= 8:
        colors_used = struct.unpack_from("<I", dib, 32)[0]
        palette_bytes = (colors_used or (1 << bit_count)) * 4
    if compression == 3 and header_size == 40:  # BI_BITFIELDS + BITMAPINFOHEADER
        palette_bytes += 12

    pixel_offset = 14 + header_size + palette_bytes
    file_size = 14 + len(dib)
    file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
    return file_header + dib


# ——————————————————————————————————————————————
# Win32 运行时（延迟加载）
# ——————————————————————————————————————————————
def _require_windows() -> None:
    if sys.platform != "win32":
        raise OSError("剪贴板读写仅支持 Windows")


def _user32():
    _require_windows()
    import ctypes

    user32 = ctypes.windll.user32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    return user32


def _kernel32():
    _require_windows()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    return kernel32


class _Clipboard:
    """OpenClipboard / CloseClipboard 的上下文管理器，带短重试。"""

    def __init__(self) -> None:
        self._user32 = _user32()

    def __enter__(self):
        import time

        for delay in (0, *RETRY_BACKOFF_MS):
            if delay:
                time.sleep(delay / 1000.0)
            if self._user32.OpenClipboard(None):
                return self
        raise OSError("打开剪贴板失败：可能被其它程序占用")

    def __exit__(self, *exc) -> None:
        self._user32.CloseClipboard()


def _read_bytes(fmt: int) -> bytes | None:
    """读取指定格式的 HGLOBAL 原始字节。"""
    import ctypes

    user32 = _user32()
    kernel32 = _kernel32()
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return None
    try:
        size = kernel32.GlobalSize(handle)
        if not size:
            return None
        return ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(handle)


def _read_text() -> str:
    """读取 CF_UNICODETEXT（按空字符截断，去掉 HGLOBAL 尾部填充）。"""
    import ctypes

    user32 = _user32()
    kernel32 = _kernel32()
    handle = user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return ""
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        return ""
    try:
        return ctypes.wstring_at(ptr)
    finally:
        kernel32.GlobalUnlock(handle)


def _read_file_paths() -> list[str]:
    """读取 CF_HDROP 的路径列表（std::vector<std::string> 一致的结果）。"""
    _require_windows()
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint

    handle = _user32().GetClipboardData(CF_HDROP)
    if not handle:
        return []
    count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
    paths: list[str] = []
    for i in range(count):
        length = shell32.DragQueryFileW(handle, i, None, 0)
        buf = ctypes.create_unicode_buffer(length + 1)
        shell32.DragQueryFileW(handle, i, buf, length + 1)
        paths.append(buf.value)
    return paths


def _dib_to_png(dib: bytes) -> bytes:
    """DIB → PNG（用 Pillow，仅此处需要图像库）。"""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(dib_to_bmp(dib))) as img:
        img.load()
        out = BytesIO()
        img.save(out, format=IMAGE_FORMAT)
        return out.getvalue()


# ——————————————————————————————————————————————
# 对外接口
# ——————————————————————————————————————————————
def read_clipboard() -> tuple[str, str | bytes] | None:
    """读取当前剪贴板。

    返回 ``(type, payload)``：``("file", json_paths)`` / ``("image", png_bytes)`` /
    ``("text", text)``；无可用格式返回 None。
    """
    import json

    _require_windows()
    user32 = _user32()
    with _Clipboard():
        available = [fmt for fmt in (CF_HDROP, CF_DIBV5, CF_DIB, CF_UNICODETEXT)
                     if user32.IsClipboardFormatAvailable(fmt)]
        kind = pick_format(available)
        if kind is None:
            return None
        if kind == "file":
            paths = _read_file_paths()
            return ("file", json.dumps(paths, ensure_ascii=False)) if paths else None
        if kind == "image":
            for fmt in (CF_DIBV5, CF_DIB):
                if not user32.IsClipboardFormatAvailable(fmt):
                    continue
                raw = _read_bytes(fmt)
                if raw:
                    try:
                        return ("image", _dib_to_png(raw))
                    except Exception:  # noqa: BLE001 - 换下一种格式再试
                        continue
            return None
        text = _read_text()
        return ("text", text) if text else None


def write_text(text: str) -> bool:
    """把文本写入剪贴板（用于「选词气泡回写」）。成功返回 True。"""
    import ctypes

    _require_windows()
    user32 = _user32()
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    buffer = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buffer)

    with _Clipboard():
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0042, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, ctypes.byref(buffer), size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
    return True


def get_foreground_info() -> tuple[str | None, str | None, str | None, int | None]:
    """返回前台窗口信息：``(进程名, 窗口标题, 窗口类名, 窗口样式)``。

    供黑名单过滤与密码框启发式使用。任一项取不到时为 None。
    """
    if sys.platform != "win32":
        return (None, None, None, None)
    import ctypes

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return (None, None, None, None)

    # 窗口标题
    length = user32.GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buf, length + 1)

    # 窗口类名
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)

    # 窗口样式（用于判断密码框）
    style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE

    # 进程名
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = None
    if pid.value:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    process_name = buf.value.rsplit("\\", 1)[-1]
            finally:
                kernel32.CloseHandle(handle)

    return (
        process_name,
        title_buf.value or None,
        class_buf.value or None,
        style if style else None,
    )


def to_dib(png_bytes: bytes) -> bytes:
    """PNG 字节 → DIB（粘贴图片回写时用，去掉 BMP 的 14 字节文件头）。"""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(png_bytes)) as img:
        rgb = img.convert("RGB")
        out = BytesIO()
        rgb.save(out, format="BMP")
    return out.getvalue()[14:]


def write_image(png_bytes: bytes) -> bool:
    """把 PNG 图片写入剪贴板（CF_DIB）。成功返回 True。"""
    import ctypes

    _require_windows()
    dib = to_dib(png_bytes)
    user32 = _user32()
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    with _Clipboard():
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0042, len(dib))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, dib, len(dib))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_DIB, handle):
            kernel32.GlobalFree(handle)
            return False
    return True
