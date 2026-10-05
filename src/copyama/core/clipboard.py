"""剪贴板变更监听：基于 Qt QClipboard，稳定跨平台。

用 Qt 自带的 ``QClipboard.dataChanged`` 信号监听剪贴板变更，
读取也通过 ``QMimeData`` / ``QClipboard`` 完成，彻底避免 Win32
ctypes 的类型、线程、窗口过程等坑。

回调签名 ``on_clip(clip, blob)``：``blob`` 仅在图片条目时为 PNG 原始字节，
供存储层落原图 + 生成缩略图；其余类型为 None。
"""

from __future__ import annotations

import json
import sys
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QClipboard, QGuiApplication, QPixmap

from copyama.core.file_kinds import classify_file, summarize
from copyama.core.models import Clip, ClipType
from copyama.utils.logger import get_logger

log = get_logger(__name__)

ClipCallback = Callable[[Clip, bytes | None], None]


def _build_clip_from_mime(mime: QMimeData, config) -> tuple[Clip, bytes | None] | None:
    """从 QMimeData 解析出 Clip 对象；返回 (clip, blob) 或 None。"""
    blob: bytes | None = None

    # —— 图片 ——
    if mime.hasImage() and config.capture_image:
        pixmap = QPixmap(mime.imageData())
        if not pixmap.isNull():
            from PySide6.QtCore import QBuffer, QIODevice

            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            pixmap.save(buf, "PNG")
            png_bytes = bytes(buf.data())
            size = len(png_bytes)
            if size > config.max_image_mb * 1024 * 1024:
                log.debug("图片超过 %d MB，跳过", config.max_image_mb)
                return None
            clip = Clip(
                type=ClipType.IMAGE,
                content="",
                size_bytes=size,
                preview=f"图片 {size // 1024} KB",
            )
            return clip, png_bytes

    # —— 文件列表（通过 URL 拖放格式）——
    if mime.hasUrls() and config.capture_files:
        paths = []
        for url in mime.urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            primary = classify_file(paths[0]).value
            if primary in set(config.excluded_kinds):
                log.debug("文件类型 %s 在排除列表中，跳过", primary)
                return None
            clip = Clip(
                type=ClipType.FILE,
                content=json.dumps(paths, ensure_ascii=False),
                kind=primary,
                preview=summarize(paths),
            )
            return clip, None

    # —— 文本（包括 HTML、代码等，统一当文本处理）——
    if mime.hasText() and config.capture_text:
        text = mime.text()
        if len(text) < config.min_text_length:
            return None
        preview = text[:200].replace("\n", " ")
        clip = Clip(
            type=ClipType.TEXT,
            content=text,
            kind=None,
            preview=preview,
            size_bytes=len(text.encode("utf-8", errors="replace")),
        )
        return clip, None

    return None


class ClipboardWatcher(QObject):
    """监听系统剪贴板变更并回调解析后的 Clip。

    基于 Qt QClipboard，跨平台稳定。使用时确保 QApplication 已创建。
    """

    # 内部信号：把剪贴板变更从 Qt 信号线程排到我们的处理逻辑
    _changed = Signal()

    def __init__(
        self,
        on_clip: ClipCallback,
        config=None,
    ) -> None:
        super().__init__()
        self._on_clip = on_clip
        self._config = config
        self._running = False
        self._paused = False
        self._suppress_next = False  # 下次变更忽略（用于自己写入时）
        self._clipboard: QClipboard | None = None
        self._changed.connect(self._on_changed, Qt.ConnectionType.QueuedConnection)

    # —— 控制 ——

    def start(self) -> bool:
        """启动监听。需要 QApplication 已存在。"""
        if self._running:
            return True
        app = QGuiApplication.instance()
        if app is None:
            log.error("QApplication 未创建，无法启动剪贴板监听")
            return False
        self._clipboard = app.clipboard()
        if self._clipboard is None:
            log.error("无法获取系统剪贴板")
            return False
        self._clipboard.dataChanged.connect(self._on_data_changed)
        self._running = True
        log.info("剪贴板监听已启动（Qt QClipboard）")
        return True

    def stop(self) -> None:
        """停止监听。"""
        if not self._running:
            return
        if self._clipboard is not None:
            try:
                self._clipboard.dataChanged.disconnect(self._on_data_changed)
            except RuntimeError:
                pass  # 已断开
        self._running = False
        log.info("剪贴板监听已停止")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    # —— 写入（写入时自动抑制一次回调，避免自己抓自己）——

    def write_text(self, text: str) -> bool:
        """写文本到剪贴板，自动抑制一次变更通知。"""
        if self._clipboard is None:
            return False
        self._suppress_next = True
        self._clipboard.setText(text)
        return True

    def write_image(self, png_bytes: bytes) -> bool:
        """写图片（PNG 字节）到剪贴板，自动抑制一次变更通知。"""
        if self._clipboard is None:
            return False
        pix = QPixmap()
        if not pix.loadFromData(png_bytes):
            return False
        self._suppress_next = True
        self._clipboard.setPixmap(pix)
        return True

    # —— 内部：Qt 信号回调 ——

    def _on_data_changed(self) -> None:
        """QClipboard.dataChanged 的直接回调（在 GUI 线程）。"""
        if not self._running or self._paused:
            return
        # 通过信号队列排一下，避免嵌套调用导致问题
        self._changed.emit()

    def _on_changed(self) -> None:
        """处理一次剪贴板变更（队列连接，安全）。"""
        if not self._running or self._paused:
            return
        if self._suppress_next:
            self._suppress_next = False
            return
        if self._clipboard is None:
            return
        mime = self._clipboard.mimeData()
        if mime is None:
            return
        try:
            result = _build_clip_from_mime(mime, self._config)
        except Exception:  # noqa: BLE001
            log.exception("解析剪贴板内容失败")
            return
        if result is None:
            return
        clip, blob = result
        try:
            self._on_clip(clip, blob)
        except Exception:  # noqa: BLE001 - 单条入库失败不应中断监听
            log.exception("剪贴内容入库回调异常")

    # —— 兼容旧接口 ——

    def poll_once(self):
        """读取当前剪贴板一次（不回调）。"""
        if self._clipboard is None:
            return None
        mime = self._clipboard.mimeData()
        if mime is None:
            return None
        result = _build_clip_from_mime(mime, self._config)
        return result[0] if result else None
