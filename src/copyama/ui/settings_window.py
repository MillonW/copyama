"""设置界面：10 个标签页，承载全部可配置项。

实现思路（降低后续维护成本）：
- 用 ``SettingSpec`` 声明式描述每个设置项，UI 层循环生成控件，新增配置只改声明；
- 每个 spec 的 key 必须存在于 Config，启动时做一致性校验（见 ``validate_specs``）；
- 修改经 ``on_apply`` 回传，由 app 层负责落盘，避免 UI 直接写配置。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from copyama.config import Config
from copyama.ui.hotkey import (
    probe_available,
    suggest_hotkey,
    validate as validate_hotkey,
)
from copyama.ui.theme import ColorScheme, SCHEME_LABELS

# 配色方案候选项（与 theme.SCHEMES 同源，避免两处维护）
SCHEME_VALUES: tuple[str, ...] = tuple(s.value for s in ColorScheme)
SCHEME_CHOICES: str = " / ".join(SCHEME_LABELS[s] for s in ColorScheme)


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    kind: str  # bool | int | str | choice | list | color | hotkey | path
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


TABS: dict[str, list[SettingSpec]] = {
    "general": [
        SettingSpec("preset", "默认模板", "choice", "一键套用职业预设", tuple(
            ["general", "programmer", "designer", "writer", "student",
             "finance", "support", "hr", "sales"]
        )),
        SettingSpec("max_items", "历史条数上限", "int",
                    "默认 200；超出的未固定记录会被淘汰（固定条目永不淘汰）",
                    minimum=20, maximum=10000),
        SettingSpec("max_age_days", "保留天数", "int",
                    "默认 7 天，更早的记录自动清理；0 = 不按时间清理",
                    minimum=0, maximum=365),
        SettingSpec("date_grouping", "按日期折叠", "bool", "历史按今天 / 昨天 / 日期分组"),
        SettingSpec("group_mode", "分组粒度", "choice", "自然日 / 今天·昨天·本周内·更早",
                    choices=("day", "bucket")),
        SettingSpec("page_size", "每页加载条数", "int",
                    "滚动到底再加载下一页，条数越小越省内存", minimum=20, maximum=500),
        SettingSpec("purge_interval_minutes", "后台清理周期(分钟)", "int",
                    "定期执行过期 / 超限 / 配额清理；0 = 仅启动时清理",
                    minimum=0, maximum=1440),
        SettingSpec("single_instance", "单实例运行", "bool", "重复启动时唤起已有窗口"),
        SettingSpec("autostart", "开机自启", "bool",
                    "⚠️ 会写入注册表启动项（HKCU\\...\\Run），开启时需确认"),
    ],
    "appearance": [
        SettingSpec("theme", "主题", "choice", "跟随系统 / 浅色 / 深色",
                    choices=("system", "light", "dark")),
        SettingSpec("color_scheme", "配色方案", "choice",
                    f"黑白线条风的多套中性配色：{SCHEME_CHOICES}",
                    choices=SCHEME_VALUES),
        SettingSpec("accent_color", "强调色", "color", "线条风建议用深灰或纯黑"),
        SettingSpec("line_width", "线条宽度", "int", "1px 细线是高级感的关键",
                    minimum=1, maximum=4),
        SettingSpec("font_family", "字体", "str"),
        SettingSpec("font_size", "字号", "int", minimum=10, maximum=22),
        SettingSpec("corner_radius", "圆角", "int", minimum=0, maximum=24),
        SettingSpec("list_density", "列表密度", "choice",
                    choices=("compact", "comfortable")),
        SettingSpec("show_preview", "显示预览面板", "bool"),
        SettingSpec("animation", "交互动效", "bool", "关闭可进一步降低开销"),
    ],
    "popup": [
        SettingSpec("popup_width", "窗口宽度", "int", minimum=320, maximum=1200),
        SettingSpec("popup_height", "窗口高度", "int", minimum=360, maximum=1200),
        SettingSpec("popup_position", "出现位置", "choice",
                    "光标旁 / 当前屏居中 / 主屏居中 / 托盘附近 / 记住上次 / 固定坐标",
                    choices=("cursor", "active_center", "primary_center",
                             "tray", "remember", "fixed")),
        SettingSpec("fixed_position", "固定坐标", "list", "仅「固定坐标」策略生效，格式 [x, y]"),
        SettingSpec("auto_hide_seconds", "自动消失", "int",
                    "单位秒；0 表示不自动消失", minimum=0, maximum=600),
        SettingSpec("pin_on_click", "点击后常驻", "bool", "点击条目后窗口不自动关闭"),
        SettingSpec("hide_on_blur", "失焦即隐藏", "bool"),
    ],
    "hotkey": [
        SettingSpec("hotkey", "唤起快捷键", "hotkey", "支持自定义与冲突检测"),
    ],
    "capture": [
        SettingSpec("capture_text", "捕获文本", "bool"),
        SettingSpec("capture_image", "捕获图片", "bool"),
        SettingSpec("capture_files", "捕获文件", "bool",
                    "支持图片 / 音视频 / 压缩包 / 文档等任意类型"),
        SettingSpec("excluded_kinds", "排除的文件类型", "list",
                    "如 ['executable', 'font']"),
        SettingSpec("store_images", "保存图片原图", "bool",
                    "开启后原图落盘、列表只加载缩略图；关闭则仅保留缩略图"),
        SettingSpec("thumb_max_px", "缩略图最长边(px)", "int",
                    "越小越省空间，列表仍清晰", minimum=64, maximum=1024),
        SettingSpec("thumb_format", "缩略图格式", "choice",
                    "webp 体积最小", choices=("webp", "jpeg", "png")),
        SettingSpec("blob_quota_mb", "原图占用上限(MB)", "int",
                    "超过后从最旧的图片开始清理；0 = 不限制",
                    minimum=0, maximum=10000),
        SettingSpec("max_image_mb", "单张图片上限(MB)", "int", minimum=1, maximum=200),
        SettingSpec("min_text_length", "文本最小长度", "int", "过滤误触空复制",
                    minimum=1, maximum=1000),
    ],
    "content": [
        SettingSpec("token_bubbles", "选词气泡", "bool",
                    "自动把文本切成可点选片段（代码 / 链接 / 图片 / 文件样式略有区分）"),
        SettingSpec("token_min_length", "气泡最小长度", "int", minimum=1, maximum=20),
        SettingSpec("cjk_segmenter", "中文分词", "choice",
                    "内置规则 / jieba（需额外依赖）", choices=("builtin", "jieba")),
        SettingSpec("clean_whitespace_on_paste", "粘贴前清洗空白", "bool"),
        SettingSpec("format_json", "JSON 自动格式化", "bool"),
        SettingSpec("code_highlight", "代码语法高亮", "bool"),
        SettingSpec("ocr_enabled", "OCR 图片取字", "bool", "需额外依赖，二期"),
    ],
    "privacy": [
        SettingSpec("exclude_passwords", "密码框过滤", "bool", "启发式，不完全覆盖 UWP"),
        SettingSpec("blacklist", "应用黑名单", "list", "按进程名匹配，如 ['KeePass.exe']"),
        SettingSpec("encrypt_db", "本地加密", "bool", "开启后条目以密文存储"),
    ],
    "storage": [
        SettingSpec("vacuum_on_start", "启动回收空间", "bool",
                    "启动时压缩数据库空洞，控制体积"),
        SettingSpec("backup_enabled", "定时本地备份", "bool"),
        SettingSpec("backup_interval_hours", "备份间隔(小时)", "int",
                    minimum=1, maximum=168),
        SettingSpec("backup_keep", "保留份数", "int", minimum=1, maximum=60),
    ],
}


def validate_specs(config: Config | None = None) -> list[str]:
    """校验所有 spec 的 key 在 Config 中存在，返回问题列表（空表示通过）。"""
    known = set((config or Config()).__dataclass_fields__)
    problems: list[str] = []
    for tab, specs in TABS.items():
        for spec in specs:
            if spec.key not in known:
                problems.append(f"[{tab}] 未知配置项：{spec.key}")
            if spec.kind == "choice" and spec.choices and spec.key in known:
                default = getattr(config or Config(), spec.key)
                if default not in spec.choices:
                    problems.append(f"[{tab}] {spec.key} 默认值 {default!r} 不在候选中")
    return problems


def tab_specs(tab: str) -> list[SettingSpec]:
    """取某个标签页的声明（UI 循环生成控件用）。"""
    return TABS.get(tab, [])


# —— 类型转换与回填（纯逻辑，跨平台可单测）——


def coerce_value(spec: SettingSpec, raw: Any) -> Any:
    """把控件原始值按 spec.kind 转成配置类型，越界值夹紧、非法值报错。"""
    if spec.kind == "bool":
        return bool(raw)
    if spec.kind == "int":
        value = int(raw)
        if spec.minimum is not None:
            value = max(spec.minimum, value)
        if spec.maximum is not None:
            value = min(spec.maximum, value)
        return value
    if spec.kind == "choice":
        text = str(raw)
        if spec.choices and text not in spec.choices:
            raise ValueError(f"{spec.label} 取值非法：{text}")
        return text
    if spec.kind == "list":
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            data = json.loads(text)
        else:
            data = list(raw)
        if not isinstance(data, list):
            raise ValueError(f"{spec.label} 需要 JSON 数组，例如 [\"a\", \"b\"]")
        if any(isinstance(item, (list, dict)) for item in data):
            raise ValueError(f"{spec.label} 只支持一维数组")
        # 保留元素原类型：坐标是数字、黑名单是字符串，强行 str 会让来回转换失型
        return list(data)
    return str(raw)


def dump_value(spec: SettingSpec, value: Any) -> str:
    """把配置值转成控件里显示的文本（list 用 JSON）。"""
    if spec.kind == "list":
        return json.dumps(list(value or []), ensure_ascii=False)
    return "" if value is None else str(value)


class SettingsWindow(QDialog):
    """设置窗口：左侧标签页 + 右侧表单。

    控件按 ``TABS`` 声明式生成，新增配置项只需改声明；
    点「保存」后经 ``on_apply`` 把整份 Config 回传 app 层落盘，
    UI 不直接写配置文件。
    """

    def __init__(
        self,
        config: Config,
        on_apply: Callable[[Config], None],
        probe_hotkey: Callable[[str], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._on_apply = on_apply
        self._probe_hotkey = probe_hotkey
        self._editors: dict[str, Any] = {}
        self._specs: dict[str, SettingSpec] = {}
        self._drag_pos = None
        self._can_drag = False
        self.setWindowTitle("Copyama 设置")
        self.resize(720, 560)
        self.setObjectName("SettingsDialog")
        # 标准窗口：带系统标题栏+边框，稳定可靠
        self.setWindowFlags(Qt.Window)
        self._build()
        self.reload()

    # —— 构建 ——
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._hotkey_status: QLabel | None = None   # 热键实时状态标签
        self._hotkey_debounce = QTimer(self)        # 输入防抖
        self._hotkey_debounce.setSingleShot(True)
        self._hotkey_debounce.setInterval(300)      # 停止输入 300ms 后探测
        self._hotkey_debounce.timeout.connect(self._refresh_hotkey_status)

        for tab, specs in TABS.items():
            page = QWidget()
            form = QFormLayout(page)
            for spec in specs:
                editor = self._make_editor(spec)
                self._editors[spec.key] = editor
                self._specs[spec.key] = spec
                if spec.help:
                    editor.setToolTip(spec.help)
                label = QLabel(spec.label)
                if spec.help:
                    label.setToolTip(spec.help)

                if spec.kind == "hotkey":
                    # —— 热键行：输入框 + 推荐按钮 + 状态提示 ——
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(editor, 1)
                    btn_suggest = QPushButton("推荐")
                    btn_suggest.setFixedWidth(60)
                    btn_suggest.clicked.connect(self._on_suggest_hotkey)
                    row_layout.addWidget(btn_suggest)
                    form.addRow(label, row)

                    # 状态提示（单独占一行，无标签）
                    status = QLabel("")
                    status.setTextFormat(Qt.TextFormat.RichText)
                    status.setStyleSheet("font-size: 12px;")
                    status.setWordWrap(True)
                    form.addRow("", status)
                    self._hotkey_status = status
                    editor.textChanged.connect(self._on_hotkey_text_changed)
                else:
                    form.addRow(label, editor)
            self._tabs.addTab(page, _TAB_TITLES.get(tab, tab))
        outer.addWidget(self._tabs)

        buttons = QHBoxLayout()
        self._btn_reset = QPushButton("恢复默认")
        self._btn_reset.clicked.connect(self.reset_to_defaults)
        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_save = QPushButton("保存")
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._on_save_clicked)
        buttons.addWidget(self._btn_reset)
        buttons.addStretch(1)
        buttons.addWidget(self._btn_cancel)
        buttons.addWidget(self._btn_save)
        outer.addLayout(buttons)

    def _make_editor(self, spec: SettingSpec) -> Any:
        if spec.kind == "bool":
            return QCheckBox()
        if spec.kind == "int":
            box = QSpinBox()
            box.setRange(
                spec.minimum if spec.minimum is not None else -1_000_000,
                spec.maximum if spec.maximum is not None else 1_000_000,
            )
            return box
        if spec.kind == "choice":
            combo = QComboBox()
            combo.addItems(list(spec.choices))
            return combo
        return QLineEdit()

    # —— 数据流 ——
    def reload(self) -> None:
        """按当前配置刷新全部控件。"""
        for key, spec in self._specs.items():
            self._set_editor_value(self._editors[key], spec, getattr(self._config, key))

    def _set_editor_value(self, editor: Any, spec: SettingSpec, value: Any) -> None:
        if isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QSpinBox):
            editor.setValue(int(value))
        elif isinstance(editor, QComboBox):
            index = editor.findText(str(value))
            if index >= 0:
                editor.setCurrentIndex(index)
        elif isinstance(editor, QLineEdit):
            editor.setText(dump_value(spec, value))

    def _raw_value(self, editor: Any) -> Any:
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, QSpinBox):
            return editor.value()
        if isinstance(editor, QComboBox):
            return editor.currentText()
        return editor.text()

    def collect(self) -> dict:
        """从控件收集当前值（按 spec.kind 做类型转换）。"""
        values: dict[str, Any] = {}
        for key, editor in self._editors.items():
            values[key] = coerce_value(self._specs[key], self._raw_value(editor))
        return values

    def apply(self) -> list[str]:
        """校验并回传配置，返回问题列表（空表示无警告）。"""
        values = self.collect()
        for key, value in values.items():
            setattr(self._config, key, value)
        problems = validate_specs(self._config)
        problems.extend(validate_hotkey(self._config.hotkey))
        self._on_apply(self._config)
        return problems

    def reset_to_defaults(self) -> None:
        """恢复默认值（不落盘，需用户确认后 apply）。"""
        defaults = Config()
        for key, spec in self._specs.items():
            self._set_editor_value(self._editors[key], spec, getattr(defaults, key))

    def _on_save_clicked(self) -> None:
        try:
            problems = self.apply()
        except ValueError as exc:
            QMessageBox.warning(self, "设置未保存", str(exc))
            return
        if problems:
            QMessageBox.warning(self, "已保存，但有提示", "\n".join(problems))
        self.accept()

    def show(self) -> None:  # noqa: D102 - 覆盖以先同步配置
        self.reload()
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()
        self.activateWindow()
        # 淡入动画
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_in.start()

    # —— 热键实时检测 & 推荐 ——

    def _on_hotkey_text_changed(self) -> None:
        """热键输入变化：重启防抖定时器，避免每敲一个键都调系统 API。"""
        self._hotkey_debounce.start()
        if self._hotkey_status is not None:
            self._hotkey_status.setText(
                '<span style="color: gray;">正在检测…</span>'
            )

    def _refresh_hotkey_status(self) -> None:
        """防抖到期：真实探测热键占用情况，更新状态标签。"""
        editor = self._editors.get("hotkey")
        status = self._hotkey_status
        if editor is None or status is None:
            return
        text = editor.text().strip()
        if not text:
            status.setText('<span style="color: gray;">请输入热键，如 Ctrl+Alt+V</span>')
            return

        # 1) 先做格式校验
        problems = validate_hotkey(text)
        hard_errors = [p for p in problems if "无法识别" in p or "至少" in p or "未知修饰键" in p or "修饰键重复" in p]
        if hard_errors:
            status.setText(
                f'<span style="color: #d4380d;">✗ {hard_errors[0]}</span>'
            )
            return

        # 2) 静态冲突提示（常见软件）
        conflict_msgs = [p for p in problems if "冲突" in p]

        # 3) 真实探测（优先用 app 层注入的真实探测，结果与实际注册 100% 一致；
        #    没有回调则退化为本地 probe_available）
        try:
            if self._probe_hotkey is not None:
                available = self._probe_hotkey(text)
            else:
                available = probe_available(text)
        except Exception:
            available = False

        if available:
            if conflict_msgs:
                status.setText(
                    f'<span style="color: #d48806;">⚠ 当前可注册，但{conflict_msgs[0]}</span>'
                )
            else:
                status.setText(
                    '<span style="color: #389e0d;">✓ 该热键可用，未被占用</span>'
                )
        else:
            if conflict_msgs:
                status.setText(
                    f'<span style="color: #d4380d;">✗ 已被占用（{conflict_msgs[0]}），建议更换</span>'
                )
            else:
                status.setText(
                    '<span style="color: #d4380d;">✗ 该热键已被其它程序占用，请更换</span>'
                )

    def _on_suggest_hotkey(self) -> None:
        """推荐按钮：自动找一个未被占用的热键并填入输入框。

        优先用 app 层注入的真实探测（和注册同一 hwnd），保证推荐的一定能注册上。
        """
        editor = self._editors.get("hotkey")
        status = self._hotkey_status
        if editor is None:
            return

        current = editor.text().strip()
        exclude = {current} if current else None

        # 用真实探测逐个试，找到第一个可用的
        from copyama.ui.hotkey import _RECOMMEND_POOL, check_conflict, normalize

        probe_fn = self._probe_hotkey or probe_available
        suggested = None
        skip = set()
        if exclude:
            for s in exclude:
                try:
                    skip.add(normalize(s).casefold())
                except ValueError:
                    pass
        for spec in _RECOMMEND_POOL:
            try:
                canon = normalize(spec).casefold()
            except ValueError:
                continue
            if canon in skip:
                continue
            if check_conflict(spec):
                continue
            try:
                if probe_fn(spec):
                    suggested = spec
                    break
            except Exception:
                continue

        if suggested is None:
            if status is not None:
                status.setText(
                    '<span style="color: #d48806;">⚠ 没找到合适的推荐组合，请手动输入</span>'
                )
            return

        editor.setText(suggested)
        self._hotkey_debounce.start()


# 标签页中文名（声明用英文 key，展示用中文）
_TAB_TITLES = {
    "general": "通用",
    "appearance": "外观",
    "popup": "弹窗",
    "hotkey": "热键",
    "capture": "捕获",
    "content": "内容",
    "privacy": "隐私",
    "storage": "存储",
}
