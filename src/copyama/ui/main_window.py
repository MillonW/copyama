"""主窗口：剪贴历史（按日期折叠）+ 搜索 + 筛选 + 删除 + 预览 + 选词气泡。

设计要点（对应本次需求细化）：
- **按日期折叠**：用 QTreeWidget 的顶层项当「今天 / 昨天 / 10月01日 周三」组头，可折叠；
- **分页加载**：首屏只查 ``page_size`` 条，滚动到底再取下一页，历史再长也不卡；
- **可删除 / 可搜索**：搜索框带防抖；Delete 键或右键删除（默认软删，进回收站可撤销）；
- **图片走缩略图**：列表只解码 256px 缩略图，原图仅双击预览时才读；
- **气泡按类型微调**：文本 / 代码 / 链接 / 图片 / 音视频 / 压缩包 / 文件共用一套尺寸，
  只改左色条、底纹、字体，风格统一且一眼可辨。

窗口行为：按 ``popup_position`` 出现在合适位置；``auto_hide_seconds`` 到点自动消失。
"""

from __future__ import annotations

import os
import time
from dataclasses import replace

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QTime,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
)
from PySide6.QtGui import (
    QAction,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QColor,
    QBrush,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from copyama.config import Config
from copyama.core.file_kinds import KIND_LABELS, FileKind
from copyama.core.grouping import humanize_age, humanize_expiry
from copyama.core.grouping import groups as group_clips
from copyama.core.models import Clip, ClipType
from copyama.core.placement import Placement, compute_position, screen_at_point
from copyama.core.popup_policy import PopupState, should_auto_hide
from copyama.data.storage import Storage, now_ms
from copyama.core.tokenizer import split_bubbles
from copyama.ui.theme import (
    bubble_object_name, bubble_qss, build_qss, mode_from_str, palette_for,
    resolve_mode, scheme_from_str, thumbnail_qss,
)
from copyama.utils.logger import get_logger

log = get_logger(__name__)

FILTER_CHIPS: list[tuple[str, str]] = [
    ("all", "全部"),
    ("text", "文本"),
    (FileKind.IMAGE.value, "图片"),
    (FileKind.VIDEO.value, "视频"),
    (FileKind.AUDIO.value, "音频"),
    (FileKind.ARCHIVE.value, "压缩包"),
    (FileKind.PDF.value, "PDF"),
    (FileKind.CODE.value, "代码"),
]

SEARCH_DEBOUNCE_MS = 220
THUMB_PX = 48
USAGE_REFRESH_SECONDS = 5.0   # 占用统计要扫目录，节流避免拖慢刷新


def human_size(n: int) -> str:
    """字节 → 人类可读体积。"""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class MainWindow(QWidget):
    """弹窗主界面。"""

    clip_activated = Signal(int)   # 用户选中某条历史（携带 id）
    request_settings = Signal()    # 请求打开设置窗口

    def __init__(self, config: Config, storage: Storage, clipboard_watcher=None) -> None:
        super().__init__()
        self._config = config
        self._storage = storage
        self._watcher = clipboard_watcher  # 剪贴板监听器（写入时用于去重）
        self._last_foreground_hwnd: int | None = None  # 呼出前的前台窗口（用于粘贴回去）
        self._animating_out = False  # 是否正在执行收起动画（防止重复触发）
        self._clips: list[Clip] = []
        self._by_id: dict[int, Clip] = {}
        self._loaded = 0
        self._total = 0
        self._active_filter = "all"
        self._keyword = ""
        self._state = PopupState()
        self._tray_point: tuple[int, int] | None = None
        self._usage_at = 0.0

        self._build_ui()
        self._setup_timer()
        self.apply_theme()

    # —— 构建 ——
    def _build_ui(self) -> None:
        self.setObjectName("Root")
        # 用 Tool 而不是 Popup：无边框 + 圆角 + 可拖动 + 置顶
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._apply_smart_size()

        # 拖动相关
        self._drag_pos = None  # 拖动起始点（相对于窗口）
        self._can_drag = False
        self._user_moved = False  # 用户是否手动拖动过窗口

        # 外层：透明背景 + 边距（给圆角留空间）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        # 卡片容器：真正的圆角白底 + 细边框
        self._card = QWidget()
        self._card.setObjectName("Card")
        outer.addWidget(self._card)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        # 顶部拖拽条（标题栏区域，可拖动窗口）
        drag_bar = QHBoxLayout()
        drag_bar.setContentsMargins(0, 0, 0, 4)
        title_label = QLabel("Copyama · 剪贴历史")
        title_label.setObjectName("DragTitle")
        title_label.setStyleSheet("color: #999; font-size: 11px; letter-spacing: 1px;")
        drag_bar.addWidget(title_label)
        drag_bar.addStretch(1)
        # 让整个 drag_bar 区域可拖动
        self._drag_widget = title_label
        root.addLayout(drag_bar)

        # 顶部：搜索 + 计数 + 占用
        head = QHBoxLayout()
        head.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索历史（正文 / 文件名 / 路径 / 来源）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search_changed)
        head.addWidget(self.search, 1)

        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
        head.addWidget(self.count_label)

        self.usage_label = QLabel("")
        self.usage_label.setObjectName("Meta")
        head.addWidget(self.usage_label)
        root.addLayout(head)

        # 筛选 chips + 操作
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chip_buttons: list[QPushButton] = []
        for key, label in FILTER_CHIPS:
            btn = QPushButton(label)
            btn.setObjectName("Bubble")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            chips.addWidget(btn)
            self._chip_buttons.append(btn)
        chips.addStretch(1)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.setObjectName("Ghost")
        self.btn_delete.setToolTip("删除选中记录（进回收站，可撤销）")
        self.btn_delete.clicked.connect(self.delete_selected)
        chips.addWidget(self.btn_delete)

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("Ghost")
        self.btn_settings.clicked.connect(self.request_settings.emit)
        chips.addWidget(self.btn_settings)
        root.addLayout(chips)

        # 中部：日期折叠列表 + 预览
        body = QHBoxLayout()
        body.setSpacing(10)

        self.tree = QTreeWidget()
        self.tree.setObjectName("History")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)          # 组头可折叠
        self.tree.setUniformRowHeights(True)        # 统一行高：显著提升滚动性能
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setIconSize(QSize(THUMB_PX, THUMB_PX))
        self.tree.setIndentation(12)
        self.tree.setAnimated(False)                # 关掉动画，弹窗更跟手
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        body.addWidget(self.tree, 3)

        # 右侧面板：预览（上）+ 气泡（下），统一在一个卡片里
        right_panel = QWidget()
        right_panel.setObjectName("PreviewPanel")
        right_panel.setMinimumWidth(240)
        right_panel.setVisible(self._config.show_preview)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setText("选择条目以预览")
        right_layout.addWidget(self.preview, 3)

        # 气泡区（流式多行排列，在预览下方）
        self.bubble_area = QScrollArea()
        self.bubble_area.setWidgetResizable(True)
        self.bubble_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.bubble_area.setMinimumHeight(100)
        self.bubble_area.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._bubble_host = QWidget()
        from copyama.ui.flow_layout import FlowLayout

        self._bubble_layout = FlowLayout(self._bubble_host, margin=2, spacing=6)
        self.bubble_area.setWidget(self._bubble_host)
        right_layout.addWidget(self.bubble_area, 2)

        body.addWidget(right_panel, 2)
        root.addLayout(body, 1)

        self.empty_hint = QLabel("没有匹配的剪贴记录")
        self.empty_hint.setObjectName("EmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setVisible(False)
        root.addWidget(self.empty_hint)

    def _setup_timer(self) -> None:
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(500)
        self._hide_timer.timeout.connect(self._on_tick)
        self._elapsed_ms = 0

        # 搜索防抖：连续输入只在停顿后查一次库
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refresh)

    # —— 主题 ——
    def apply_theme(self) -> None:
        mode = resolve_mode(mode_from_str(self._config.theme))
        palette = palette_for(mode, scheme_from_str(self._config.color_scheme))
        self.setStyleSheet(
            build_qss(
                palette,
                radius=self._config.corner_radius,
                font_family=self._config.font_family,
                font_size=self._config.font_size,
                line_width=self._config.line_width,
            )
            + bubble_qss(
                palette,
                radius=max(8, self._config.corner_radius + 2),
                font_family=self._config.font_family,
                font_size=self._config.font_size,
            )
            + thumbnail_qss(palette, radius=max(2, self._config.corner_radius - 4),
                            line_width=self._config.line_width)
        )

    # —— 数据加载 ——
    def _kinds(self) -> list[str] | None:
        """筛选条件转 storage 的 kind 列表。"""
        if self._active_filter in ("all", "text"):
            return None
        return [self._active_filter]

    def refresh(self) -> None:
        """重载第一页（搜索、筛选、删除后调用）。"""
        self._keyword = self.search.text().strip()
        kinds = self._kinds()
        self._clips = self._storage.page(0, self._config.page_size, self._keyword, kinds)
        self._loaded = len(self._clips)
        self._total = self._storage.count_filtered(self._keyword, kinds)
        self._render()

    def load_more(self) -> None:
        """追加下一页（滚动到底触发）。"""
        if self._loaded >= self._total:
            return
        more = self._storage.page(self._loaded, self._config.page_size, self._keyword, self._kinds())
        if not more:
            return
        self._clips.extend(more)
        self._loaded = len(self._clips)
        self._render(keep_scroll=True)

    def _maybe_load_more(self, value: int) -> None:
        bar = self.tree.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 24:
            self.load_more()

    def set_filter(self, key: str) -> None:
        self._active_filter = key
        for btn, (chip_key, _label) in zip(self._chip_buttons, FILTER_CHIPS):
            btn.setChecked(chip_key == key)
        self.refresh()

    def _on_search_changed(self, _text: str) -> None:
        self._search_timer.start()

    # —— 渲染 ——
    def _render(self, keep_scroll: bool = False) -> None:
        """重建列表；分页 + 少量控件，重绘成本可控。"""
        bar = self.tree.verticalScrollBar()
        scroll = bar.value()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self._by_id = {c.id: c for c in self._clips if c.id}

        if self._config.date_grouping:
            for group in group_clips(self._clips, now_ms(), self._config.group_mode):
                header = QTreeWidgetItem([f"{group.label}  ·  {group.count}"])
                header.setFlags(Qt.ItemIsEnabled)
                header.setData(0, Qt.UserRole, None)
                font = header.font(0)
                font.setPointSize(max(8, self._config.font_size - 3))
                header.setFont(0, font)
                self.tree.addTopLevelItem(header)
                for clip in group.clips:
                    header.addChild(self._make_item(clip))
                header.setExpanded(True)
        else:
            for clip in self._clips:
                self.tree.addTopLevelItem(self._make_item(clip))

        self.tree.setUpdatesEnabled(True)
        if keep_scroll:
            bar.setValue(scroll)

        self.empty_hint.setVisible(not self._clips)
        suffix = f"{self._loaded}/{self._total}" if self._loaded < self._total else f"{self._total}"
        self.count_label.setText(f"{suffix} 条")
        self._update_usage()

    def _update_usage(self, force: bool = False) -> None:
        """更新「占用空间」；目录统计有成本，默认 5 秒内不重复扫盘。"""
        moment = time.monotonic()
        if not force and moment - self._usage_at < USAGE_REFRESH_SECONDS:
            return
        self._usage_at = moment
        usage = self._storage.disk_usage()
        self.usage_label.setText(
            f"占用 {human_size(usage['total_bytes'])}"
            f"（图 {human_size(usage['blob_bytes'])} / 缩略图 {human_size(usage['thumb_bytes'])}）"
        )

    def _make_item(self, clip: Clip) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._item_text(clip)])
        item.setData(0, Qt.UserRole, clip.id)
        item.setToolTip(0, self._item_tooltip(clip))
        if clip.type is ClipType.IMAGE:
            thumb = self._storage.thumb_file(clip)
            if thumb is not None:
                pixmap = QPixmap()
                if pixmap.load(str(thumb)):
                    # 列表只吃缩略图，不碰原图
                    item.setIcon(0, QIcon(pixmap.scaled(
                        THUMB_PX, THUMB_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )))
            else:
                item.setIcon(0, QIcon())
        return item

    @staticmethod
    def _kind_label(clip: Clip) -> str:
        if clip.type is ClipType.IMAGE:
            return "图片"
        if clip.type is ClipType.TEXT:
            return "文本"
        try:
            return KIND_LABELS.get(FileKind(clip.kind or ""), clip.kind or "文件")
        except ValueError:
            return clip.kind or "文件"

    def _item_text(self, clip: Clip) -> str:
        if clip.type is ClipType.IMAGE:
            head = f"图片 · {human_size(clip.size_bytes)}"
        elif clip.type is ClipType.FILE:
            paths = clip.file_paths
            name = os.path.basename(paths[0]) if paths else "文件"
            head = name + (f" 等 {len(paths)} 个文件" if len(paths) > 1 else "")
        else:
            head = " ".join((clip.content or "").split())[:90] or "(空)"
        star = "★ " if clip.pinned else ""
        meta = " · ".join(
            part for part in (
                self._kind_label(clip),
                humanize_age(clip.created_at, now_ms()),
                humanize_expiry(clip, now_ms(), self._config.max_age_days),
                clip.source_app,
            ) if part
        )
        return f"{star}{head}\n{meta}"

    def _item_tooltip(self, clip: Clip) -> str:
        if clip.type is ClipType.FILE:
            return "\n".join(clip.file_paths[:12])
        return (clip.content or "")[:600]

    # —— 选择与气泡 ——
    def _selected_clips(self) -> list[Clip]:
        result: list[Clip] = []
        for item in self.tree.selectedItems():
            clip_id = item.data(0, Qt.UserRole)
            if clip_id is not None and clip_id in self._by_id:
                result.append(self._by_id[clip_id])
        return result

    def _on_selection_changed(self) -> None:
        clips = self._selected_clips()
        clip = clips[0] if clips else None
        self._render_bubbles(clip)
        self._render_preview(clip)

    def _render_bubbles(self, clip: Clip | None) -> None:
        """把选中条目的文本切成气泡；类型不同则胶囊细节不同。"""
        while self._bubble_layout.count():
            item = self._bubble_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if clip is None or not self._config.token_bubbles:
            return
        for piece, kind in split_bubbles(clip.bubble_sources)[:80]:
            btn = QPushButton(piece)
            btn.setObjectName(bubble_object_name(kind.value))
            btn.setToolTip(f"{kind.value} · 点击复制此片段")
            btn.clicked.connect(lambda _=False, text=piece: self._copy_piece(text))
            self._bubble_layout.addWidget(btn)

    def _render_preview(self, clip: Clip | None) -> None:
        if not self._config.show_preview:
            return
        if clip is None:
            self.preview.clear()
            self.preview.setText("选择条目以预览")
            self.preview.setAlignment(Qt.AlignCenter)
        elif clip.type is ClipType.IMAGE:
            # 截图/图片数据：从 storage 读字节加载
            img_data = self._storage.image_bytes(clip)
            if img_data:
                pixmap = QPixmap()
                if pixmap.loadFromData(img_data):
                    pw = max(self.preview.width(), 180)
                    ph = max(self.preview.height(), 180)
                    self.preview.setAlignment(Qt.AlignCenter)
                    self.preview.setPixmap(pixmap.scaled(
                        pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    return
            self.preview.setAlignment(Qt.AlignCenter)
            self.preview.setText(f"🖼  图片\n{human_size(clip.size_bytes)}")
        elif clip.type is ClipType.FILE:
            # 文件类型：先看看是不是单个图片文件，是则预览图片
            import json
            try:
                paths = json.loads(clip.content or "[]")
            except (json.JSONDecodeError, TypeError):
                paths = []

            if isinstance(paths, list) and len(paths) == 1:
                # 单个文件 → 试试能不能当图片预览
                import os
                fpath = str(paths[0])
                ext = os.path.splitext(fpath)[1].lower()
                if ext in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"}:
                    if os.path.isfile(fpath):
                        pixmap = QPixmap(fpath)
                        if not pixmap.isNull():
                            pw = max(self.preview.width(), 180)
                            ph = max(self.preview.height(), 180)
                            self.preview.setAlignment(Qt.AlignCenter)
                            self.preview.setPixmap(pixmap.scaled(
                                pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            ))
                            return

            # 多个文件或非图片 → 显示文件列表
            self.preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            if isinstance(paths, list) and paths:
                lines = [f"📁 {len(paths)} 个文件：", ""]
                for p in paths[:15]:
                    lines.append(f"  • {p}")
                if len(paths) > 15:
                    lines.append(f"  … 还有 {len(paths) - 15} 个")
                self.preview.setText("\n".join(lines))
            else:
                self.preview.setText("（空文件列表）")
        else:
            # 文本 / 代码等：靠左对齐，便于阅读
            self.preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            content = clip.content or ""
            if len(content) > 1000:
                content = content[:1000] + "\n…"
            self.preview.setText(content)

    def _copy_piece(self, text: str) -> None:
        self._write_clipboard(text=text)
        self._state = PopupState(pinned=self._state.pinned, interacted=True)
        if not self._config.pin_on_click:
            # 动画收起后再粘贴，视觉更流畅
            self._hide_with_animation(on_finished=self._paste_back)
        else:
            self._paste_back()

    # —— 删除 ——
    def delete_selected(self) -> None:
        """删除选中记录：默认进回收站（软删，可撤销）。"""
        clips = self._selected_clips()
        if not clips:
            return
        ids = [c.id for c in clips if c.id is not None]
        removed = self._storage.delete(ids)
        self.refresh()
        self.count_label.setText(f"已删除 {removed} 条 · 可在设置里撤销")

    def purge_selected(self) -> None:
        """彻底删除选中记录（不可恢复，先二次确认）。"""
        clips = self._selected_clips()
        if not clips:
            return
        names = "\n".join(self._item_text(c).splitlines()[0] for c in clips[:8])
        box = QMessageBox(self)
        box.setWindowTitle("彻底删除")
        box.setText(f"将不可恢复地删除 {len(clips)} 条记录（含原图与缩略图）：")
        box.setInformativeText(names)
        confirm = box.addButton("彻底删除", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return
        self._storage.purge([c.id for c in clips if c.id is not None])
        self._storage.vacuum()
        self.refresh()

    def ask_autostart(self) -> bool | None:
        """首次使用时询问是否随系统启动（属系统启动项变更，由用户明确选择）。"""
        box = QMessageBox(self)
        box.setWindowTitle("开机自启")
        box.setText("要让 Copyama 随系统启动吗？")
        box.setInformativeText(
            "开启后会写入当前用户的注册表启动项（HKCU\\Software\\Microsoft\\Windows\\"
            "CurrentVersion\\Run），只影响你的账户，可随时在设置里关闭。"
        )
        yes = box.addButton("开启", QMessageBox.AcceptRole)
        no = box.addButton("暂不开启", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            return True
        if box.clickedButton() is no:
            return False
        return None

    def _show_context_menu(self, pos) -> None:
        clips = self._selected_clips()
        menu = QMenu(self)
        act_copy = QAction("复制", menu)
        act_copy.triggered.connect(self._copy_selected)
        act_pin = QAction("取消固定" if clips and clips[0].pinned else "固定置顶", menu)
        act_pin.triggered.connect(self._toggle_pin_selected)
        act_delete = QAction("删除（进回收站）", menu)
        act_delete.triggered.connect(self.delete_selected)
        act_purge = QAction("彻底删除…", menu)
        act_purge.triggered.connect(self.purge_selected)
        for action in (act_copy, act_pin, act_delete, act_purge):
            action.setEnabled(bool(clips))
            menu.addAction(action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _write_clipboard(self, *, text: str | None = None, image: bytes | None = None) -> bool:
        """写回系统剪贴板。优先走 watcher（自动抑制自己写入的变更通知）。"""
        # 优先通过 watcher 写入：自动抑制一次 dataChanged，避免自己抓自己
        if self._watcher is not None:
            if text is not None:
                return self._watcher.write_text(text)
            if image is not None:
                return self._watcher.write_image(image)
            return False
        # 兜底：直接用 QClipboard
        from PySide6.QtGui import QGuiApplication, QPixmap

        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        if image is not None:
            pix = QPixmap()
            if pix.loadFromData(image):
                clipboard.setPixmap(pix)
                return True
            return False
        if text is not None:
            clipboard.setText(text)
            return True
        return False

    def _copy_selected(self) -> None:
        clips = self._selected_clips()
        if not clips:
            return
        clip = clips[0]
        if clip.type is ClipType.IMAGE:
            data = self._storage.image_bytes(clip)
            if data and self._write_clipboard(image=data):
                if not self._config.pin_on_click:
                    self._hide_with_animation(on_finished=self._paste_back)
                else:
                    self._paste_back()
                return
        self._copy_piece(clip.bubble_sources)

    def _toggle_pin_selected(self) -> None:
        for clip in self._selected_clips():
            if clip.id is not None:
                self._storage.set_pinned(clip.id, not clip.pinned)
        self.refresh()

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        clip_id = item.data(0, Qt.UserRole)
        if clip_id is None:
            item.setExpanded(not item.isExpanded())
            return
        self._copy_selected()

    # —— 显示与位置 ——
    def set_tray_anchor(self, point: tuple[int, int] | None) -> None:
        """由托盘层注入图标坐标，供「托盘附近」位置策略使用。"""
        self._tray_point = point

    def _record_foreground(self) -> None:
        """记录当前前台窗口句柄（呼出前的输入框）。仅 Windows 有效。"""
        self._last_foreground_hwnd = None
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                self._last_foreground_hwnd = int(hwnd)
        except Exception:  # noqa: BLE001
            self._last_foreground_hwnd = None

    def _hide_with_animation(self, on_finished=None) -> None:
        """带淡出+下滑动画地隐藏窗口。

        Args:
            on_finished: 动画完成后的回调（比如粘贴回输入框）。
        """
        if self._animating_out:
            return
        if not self.isVisible():
            if on_finished:
                on_finished()
            return
        self._animating_out = True
        self._hide_timer.stop()

        # 淡出 + 下滑 10px
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._slide_anim = QPropertyAnimation(self, b"pos")
        self._slide_anim.setDuration(150)
        self._slide_anim.setStartValue(self.pos())
        self._slide_anim.setEndValue(self.pos() + QPoint(0, 10))
        self._slide_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._hide_group = QParallelAnimationGroup()
        self._hide_group.addAnimation(self._fade_anim)
        self._hide_group.addAnimation(self._slide_anim)

        def _on_done():
            self._animating_out = False
            self.hide()
            self.setWindowOpacity(1.0)  # 恢复不透明，下次弹出正常
            if on_finished:
                on_finished()

        self._hide_group.finished.connect(_on_done)
        self._hide_group.start()

    def _paste_back(self) -> None:
        """把剪贴板内容粘贴回呼出前的前台窗口。

        流程：切回原窗口 → 等 50ms → 模拟 Ctrl+V。
        非 Windows 或没记录到窗口时什么都不做（退化为普通复制）。
        """
        import sys
        if sys.platform != "win32" or self._last_foreground_hwnd is None:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # 1. 切回原前台窗口
            hwnd = self._last_foreground_hwnd
            user32.SetForegroundWindow(hwnd)

            # 2. 用 QTimer 延迟一下，等窗口切回去再模拟按键
            from PySide6.QtCore import QTimer

            def _do_paste() -> None:
                try:
                    VK_CONTROL = 0x11
                    VK_V = 0x56
                    KEYEVENTF_KEYUP = 0x0002
                    # 按下 Ctrl
                    user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    # 按下 V
                    user32.keybd_event(VK_V, 0, 0, 0)
                    # 松开 V
                    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                    # 松开 Ctrl
                    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                except Exception:  # noqa: BLE001
                    pass

            QTimer.singleShot(50, _do_paste)
        except Exception:  # noqa: BLE001
            pass

    def _apply_smart_size(self) -> None:
        """根据当前屏幕可用尺寸智能调整窗口大小，避免窗口超出屏幕或被任务栏挡住。

        规则：
        - 宽度不超过屏幕可用宽度的 60%，且不小于 360px
        - 高度不超过屏幕可用高度的 70%，且不小于 400px
        - 配置值在范围内就用配置值，否则夹紧到合理范围
        """
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(self._config.popup_width, self._config.popup_height)
            return
        geo = screen.availableGeometry()  # 可用区域（扣掉任务栏）
        sw, sh = geo.width(), geo.height()

        max_w = max(360, int(sw * 0.6))
        max_h = max(400, int(sh * 0.7))
        w = min(max(self._config.popup_width, 360), max_w)
        h = min(max(self._config.popup_height, 400), max_h)
        self.resize(w, h)

    def show_popup(self) -> None:
        """按配置的位置策略出现在合适位置，并开始倒计时。"""
        # 先记一下当前前台窗口，双击条目后要把内容粘贴回那里
        self._record_foreground()
        self._apply_smart_size()   # 每次显示前重新计算（可能换了屏幕）
        self.refresh()
        size = (self.width(), self.height())
        cursor = self._cursor_point()
        screens = self._screens()
        screen = screen_at_point(*cursor, screens) if cursor else screens[0]
        try:
            strategy = Placement(self._config.popup_position)
        except ValueError:
            strategy = Placement.CURSOR
        # 用户手动拖动过窗口 → 优先用记住的位置（更符合直觉）
        if self._user_moved and self._last_position is not None:
            strategy = Placement.REMEMBER
        pos = compute_position(
            strategy,
            size,
            cursor=cursor,
            screen=screen,
            tray=self._tray_point,
            last=self._last_position,
            fixed=tuple(self._config.fixed_position),
        )
        self.move(pos.x, pos.y)
        # 弹出动画：从下方 12px 处淡入 + 上滑
        self.setWindowOpacity(0.0)
        start_y = pos.y + 12
        self.move(pos.x, start_y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

        # 动画组：透明度 0→1 + 位置上移 12px
        self._anim_out = QPropertyAnimation(self, b"windowOpacity")
        self._anim_out.setDuration(180)
        self._anim_out.setStartValue(0.0)
        self._anim_out.setEndValue(1.0)
        self._anim_out.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_pos = QPropertyAnimation(self, b"pos")
        self._anim_pos.setDuration(200)
        self._anim_pos.setStartValue(self.pos())
        self._anim_pos.setEndValue(self.pos() + QPoint(0, -12))
        self._anim_pos.setEasingCurve(QEasingCurve.OutCubic)

        self._show_group = QParallelAnimationGroup()
        self._show_group.addAnimation(self._anim_out)
        self._show_group.addAnimation(self._anim_pos)
        self._show_group.start()

        self._animating_out = False
        self._elapsed_ms = 0
        if self._config.auto_hide_seconds > 0:
            self._hide_timer.start()
        else:
            self._hide_timer.stop()

    @staticmethod
    def _cursor_point() -> tuple[int, int] | None:
        pos = QCursor.pos()
        return (pos.x(), pos.y())

    def _screens(self) -> list[tuple[int, int, int, int]]:
        rects = []
        for screen in self.screen().virtualSiblings():
            # 用 availableGeometry 而不是 geometry，避开任务栏
            g = screen.availableGeometry()
            rects.append((g.x(), g.y(), g.width(), g.height()))
        return rects or [(0, 0, 1920, 1080)]

    @property
    def _last_position(self) -> tuple[int, int] | None:
        return getattr(self, "_remembered_pos", None)

    # —— 生命周期 ——
    def _on_tick(self) -> None:
        self._elapsed_ms += self._hide_timer.interval()
        if should_auto_hide(
            self._state,
            timeout_seconds=self._config.auto_hide_seconds,
            elapsed_ms=self._elapsed_ms,
            pin_on_click=self._config.pin_on_click,
        ):
            self._hide_with_animation()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hide_timer.stop()
        self._remembered_pos = (self.x(), self.y())
        super().hideEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._state = replace(self._state, hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._state = replace(self._state, hovered=False)
        super().leaveEvent(event)

    # —— 拖动窗口 ——
    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 左键按下且在顶部区域 → 开始拖动
        if event.button() == Qt.LeftButton:
            # 顶部 36px 区域都可以拖动（包含标题行和搜索行上方）
            if event.position().y() < 50:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._can_drag = True
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._can_drag and self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._can_drag:
            # 用户手动拖动了窗口，下次记住这个位置
            self._user_moved = True
            self._remembered_pos = (self.x(), self.y())
            self._can_drag = False
            self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._hide_with_animation()
        elif event.key() == Qt.Key_Delete:
            self.delete_selected()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._copy_selected()
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        # 失焦自动隐藏（可在设置中关闭）
        if event.type() == QEvent.ActivationChange and self._config.hide_on_blur:
            if not self.isActiveWindow() and not self._state.pinned:
                self._hide_with_animation()
        super().changeEvent(event)
