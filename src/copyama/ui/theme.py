"""主题与样式（面向 PySide6/Qt 的 QSS 生成）。

设计语言：**ins 黑白线条高级风** —— 1px 细线、无重底色、大留白、少圆角，
视觉靠「线条 + 字重 + 间距」区分层级，而不是靠色块。

- 6 套配色方案（纯黑白 / 墨 / 石墨 / 雾 / 冷蓝 / 樱粉），每套含深浅两版；
- 气泡按内容类型（文本 / 代码 / 链接 / 图片 / 音视频 / 压缩包 / 文件）微调：
  左色条、底纹、字体三选其一，其余参数完全一致，保证风格统一。

纯字符串生成逻辑，可跨平台单测；只有读取系统深浅色时才触碰 Windows 注册表。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

MONO_FONT = "Cascadia Mono, Consolas, Menlo, monospace"


class ThemeMode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ColorScheme(str, Enum):
    """配色方案（黑白线条风的多种中性变体）。"""

    MONO = "mono"          # 纯黑白
    INK = "ink"            # 墨色（暖黑 + 米白）
    GRAPHITE = "graphite"  # 石墨（中性灰）
    FOG = "fog"            # 雾（冷灰）
    NORD = "nord"          # 冷蓝
    SAKURA = "sakura"      # 樱粉


SCHEME_LABELS: dict[ColorScheme, str] = {
    ColorScheme.MONO: "纯黑白",
    ColorScheme.INK: "墨",
    ColorScheme.GRAPHITE: "石墨",
    ColorScheme.FOG: "雾",
    ColorScheme.NORD: "冷蓝",
    ColorScheme.SAKURA: "樱粉",
}


@dataclass(frozen=True)
class Palette:
    """一套配色。字段含义见命名，均为 CSS 颜色字面量。"""

    bg: str            # 窗口背景
    surface: str       # 卡片 / 列表背景
    surface_alt: str   # 次级表面（表头、hover 底色）
    text: str
    text_muted: str
    accent: str
    border: str
    hover: str
    selected: str
    # —— 线条风扩展 ——
    line: str = "#DDDDDD"        # 常规分线 / 描边
    line_strong: str = "#111111"  # 强调线条（选中、聚焦）
    accent_text: str = "#FFFFFF"  # accent 底色上的文字
    code_bg: str = "#F7F7F7"      # 代码块底纹
    code_line: str = "#111111"    # 代码块左色条
    image_line: str = "#111111"   # 图片气泡左色条
    file_line: str = "#9A9A9A"    # 文件气泡左色条


# —— 六套方案 × 深浅两版 ——
SCHEMES: dict[ColorScheme, tuple[Palette, Palette]] = {
    ColorScheme.MONO: (
        Palette("#FFFFFF", "#FFFFFF", "#FAFAFA", "#0A0A0A", "#8A8A8A", "#111111",
                "#E6E6E6", "#F5F5F5", "#EDEDED",
                line="#DDDDDD", line_strong="#111111", code_bg="#F7F7F7",
                code_line="#111111", image_line="#111111", file_line="#9A9A9A"),
        Palette("#0A0A0A", "#101010", "#161616", "#F5F5F5", "#8F8F8F", "#FFFFFF",
                "#262626", "#1A1A1A", "#222222", accent_text="#0A0A0A",
                line="#333333", line_strong="#EDEDED", code_bg="#141414",
                code_line="#EDEDED", image_line="#EDEDED", file_line="#7A7A7A"),
    ),
    ColorScheme.INK: (
        Palette("#FAF8F5", "#FFFFFF", "#F4F1EC", "#12100E", "#7C7468", "#12100E",
                "#E7E2DA", "#F1ECE4", "#EAE3D9",
                line="#DED8CE", line_strong="#12100E", code_bg="#F6F3EE",
                code_line="#12100E", image_line="#12100E", file_line="#9C948A"),
        Palette("#121110", "#181614", "#1F1C19", "#EDE9E3", "#948C81", "#EDE9E3",
                "#2B2723", "#211E1B", "#282320", accent_text="#121110",
                line="#332E29", line_strong="#EDE9E3", code_bg="#1B1917",
                code_line="#EDE9E3", image_line="#EDE9E3", file_line="#8A8175"),
    ),
    ColorScheme.GRAPHITE: (
        Palette("#F2F3F5", "#FFFFFF", "#EAECEF", "#16181B", "#6E747C", "#3F444B",
                "#DFE2E6", "#EFF1F4", "#E4E7EB",
                line="#D6DAE0", line_strong="#3F444B", code_bg="#F4F5F7",
                code_line="#3F444B", image_line="#3F444B", file_line="#8C939B"),
        Palette("#16181B", "#1D2024", "#25292E", "#E9EBEE", "#8B929A", "#C9CDD3",
                "#2C3137", "#22262B", "#2A2F35", accent_text="#16181B",
                line="#343A41", line_strong="#C9CDD3", code_bg="#1B1E22",
                code_line="#C9CDD3", image_line="#C9CDD3", file_line="#7C838B"),
    ),
    ColorScheme.FOG: (
        Palette("#F4F6F8", "#FFFFFF", "#EBEFF3", "#141A20", "#647382", "#5B7A99",
                "#DCE2E8", "#EFF3F7", "#E3E9EF",
                line="#D2DAE2", line_strong="#5B7A99", code_bg="#F5F8FA",
                code_line="#5B7A99", image_line="#5B7A99", file_line="#8496A6"),
        Palette("#141A20", "#1A2129", "#212A33", "#E7EDF3", "#8593A1", "#9DB8D0",
                "#293440", "#1F272F", "#26303A", accent_text="#141A20",
                line="#2F3C48", line_strong="#9DB8D0", code_bg="#181F26",
                code_line="#9DB8D0", image_line="#9DB8D0", file_line="#75838F"),
    ),
    ColorScheme.NORD: (
        Palette("#ECEFF4", "#FFFFFF", "#E5E9F0", "#2E3440", "#6E7A8A", "#5E81AC",
                "#D8DEE9", "#EAEDF3", "#DFE4EC",
                line="#D0D7E3", line_strong="#5E81AC", code_bg="#F1F3F7",
                code_line="#5E81AC", image_line="#5E81AC", file_line="#8C99AC"),
        Palette("#2E3440", "#343B48", "#3B4252", "#ECEFF4", "#8B95A6", "#88C0D0",
                "#434C5E", "#39404E", "#414959", accent_text="#2E3440",
                line="#4A5364", line_strong="#88C0D0", code_bg="#303745",
                code_line="#88C0D0", image_line="#88C0D0", file_line="#7A8598"),
    ),
    ColorScheme.SAKURA: (
        Palette("#FDF7F8", "#FFFFFF", "#F8EFF1", "#1F1A1B", "#7E6C70", "#C9788E",
                "#EEDDDF", "#F7EDEF", "#F1E3E5",
                line="#E8D6D9", line_strong="#C9788E", code_bg="#FBF3F5",
                code_line="#C9788E", image_line="#C9788E", file_line="#A88B90"),
        Palette("#1F1A1B", "#262021", "#2E2628", "#F2E9EA", "#9A888B", "#E0A0B0",
                "#3A3133", "#2A2325", "#332B2D", accent_text="#1F1A1B",
                line="#413638", line_strong="#E0A0B0", code_bg="#241E1F",
                code_line="#E0A0B0", image_line="#E0A0B0", file_line="#8E7B7E"),
    ),
}

# 默认方案（黑白线条）的浅 / 深调色板，保留旧常量名以兼容既有调用
LIGHT, DARK = SCHEMES[ColorScheme.MONO]


def scheme_from_str(value: str) -> ColorScheme:
    """把配置里的方案名安全转为 ColorScheme，未知取值回退 mono。"""
    try:
        return ColorScheme(value)
    except ValueError:
        return ColorScheme.MONO


def scheme_choices() -> list[tuple[str, str]]:
    """供设置界面下拉框使用：[(值, 中文名)]。"""
    return [(s.value, SCHEME_LABELS[s]) for s in ColorScheme]


def palette_for(mode: ThemeMode, scheme: str | ColorScheme = ColorScheme.MONO) -> Palette:
    """取调色板：先定方案，再按深浅取对应版本。"""
    key = scheme if isinstance(scheme, ColorScheme) else scheme_from_str(str(scheme))
    light, dark = SCHEMES.get(key, SCHEMES[ColorScheme.MONO])
    return dark if mode is ThemeMode.DARK else light


def detect_system_mode() -> ThemeMode:
    """读取 Windows「应用深浅色」设置；非 Windows 或读取失败时回退浅色。"""
    if sys.platform != "win32":
        return ThemeMode.LIGHT
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return ThemeMode.LIGHT if value else ThemeMode.DARK
    except OSError:
        return ThemeMode.LIGHT


def mode_from_str(value: str) -> ThemeMode:
    """把配置里的字符串安全转为 ThemeMode，未知取值回退 SYSTEM。"""
    try:
        return ThemeMode(value)
    except ValueError:
        return ThemeMode.SYSTEM


def resolve_mode(mode: ThemeMode) -> ThemeMode:
    """把 SYSTEM 解析为实际模式。"""
    return detect_system_mode() if mode is ThemeMode.SYSTEM else mode


def build_qss(
    palette: Palette,
    *,
    radius: int = 10,
    font_family: str = "Microsoft YaHei UI",
    font_size: int = 13,
    line_width: int = 1,
) -> str:
    """生成全局 QSS（黑白线条高级风的基线样式）。"""
    lw = max(1, int(line_width))
    small = max(9, font_size - 2)
    return f"""
* {{
    font-family: "{font_family}";
    font-size: {font_size}px;
    color: {palette.text};
}}
QWidget#Root, QDialog#SettingsDialog {{
    background: transparent;
    border: none;
}}
QWidget#Card {{
    background: {palette.bg};
    border: {lw}px solid {palette.line};
    border-radius: {radius}px;
}}
QLabel#Title {{
    font-size: {font_size + 3}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#Muted, QLabel#Meta {{
    color: {palette.text_muted};
    font-size: {small}px;
}}
QWidget#PreviewPanel {{
    background: {palette.surface};
    border: {lw}px solid {palette.line};
    border-radius: {radius}px;
}}
QLabel#GroupHeader {{
    color: {palette.text_muted};
    font-size: {small}px;
    letter-spacing: 2px;
}}
QFrame#HLine {{
    background: {palette.line};
    border: none;
    max-height: {lw}px;
}}
QLineEdit {{
    background: transparent;
    border: none;
    border-bottom: {lw}px solid {palette.line};
    border-radius: 0px;
    padding: 8px 2px;
    selection-background-color: {palette.selected};
}}
QLineEdit:focus {{
    border-bottom: {lw}px solid {palette.line_strong};
}}
QTreeWidget, QListView {{
    background: {palette.surface};
    border: {lw}px solid {palette.line};
    border-radius: {radius}px;
    outline: none;
    padding: 4px;
}}
QTreeWidget::item, QListView::item {{
    padding: 8px 10px;
    border-radius: {max(0, radius - 3)}px;
}}
QTreeWidget::item:hover, QListView::item:hover {{
    background: {palette.hover};
}}
QTreeWidget::item:selected, QListView::item:selected {{
    background: {palette.selected};
    border-left: {lw + 1}px solid {palette.line_strong};
}}
QTreeWidget::branch {{
    background: transparent;
}}
QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: {lw}px solid {palette.line};
    padding: 6px 8px;
    color: {palette.text_muted};
}}
QPushButton {{
    background: transparent;
    border: {lw}px solid {palette.line};
    border-radius: {max(0, radius - 2)}px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    border: {lw}px solid {palette.line_strong};
    background: {palette.hover};
}}
QPushButton:pressed {{
    background: {palette.selected};
}}
QPushButton#Primary {{
    background: {palette.accent};
    color: {palette.accent_text};
    border: none;
}}
QPushButton#Primary:hover {{
    background: {palette.line_strong};
    color: {palette.accent_text};
}}
QPushButton#Ghost {{
    border: none;
    color: {palette.text_muted};
}}
QPushButton#Ghost:hover {{
    color: {palette.text};
    border-bottom: {lw}px solid {palette.line_strong};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {palette.line};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {palette.text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0px;
    background: transparent;
}}
QCheckBox, QRadioButton {{
    spacing: 8px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 8px 14px;
    color: {palette.text_muted};
    border-bottom: {lw}px solid transparent;
}}
QTabBar::tab:selected {{
    color: {palette.text};
    border-bottom: {lw}px solid {palette.line_strong};
}}
QToolTip {{
    background: {palette.surface};
    color: {palette.text};
    border: {lw}px solid {palette.line};
    padding: 4px 8px;
}}
"""


def bubble_qss(
    palette: Palette,
    *,
    radius: int = 12,
    font_family: str = "Microsoft YaHei UI",
    font_size: int = 13,
) -> str:
    """选词气泡样式。

    所有类型共用同一套「尺寸 / 圆角 / 内边距 / 行高」，只允许三处微差：
    左色条颜色、底纹、字体 —— 保证「略微不同但风格统一」。
    """
    common = f"""
    border: 1px solid {palette.line};
    border-radius: {radius}px;
    padding: 4px 12px;
    background: transparent;
    color: {palette.text};
    font-size: {font_size}px;
"""
    bar = f"border-left: 2px solid {palette.line_strong};"
    return f"""
QPushButton#Bubble, QPushButton#BubbleText {{
{common}}}
QPushButton#Bubble:hover, QPushButton#BubbleText:hover {{
    border: 1px solid {palette.line_strong};
    background: {palette.hover};
}}
QPushButton#Bubble:pressed, QPushButton#BubbleText:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleCode {{
{common}
    {bar}
    background: {palette.code_bg};
    border-left: 2px solid {palette.code_line};
    font-family: "{MONO_FONT}";
    font-size: {max(10, font_size - 1)}px;
}}
QPushButton#BubbleCode:hover {{
    border-left: 2px solid {palette.line_strong};
}}
QPushButton#BubbleCode:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleLink, QPushButton#BubbleEmail {{
{common}
    border-bottom: 1px dashed {palette.line_strong};
    color: {palette.text};
}}
QPushButton#BubbleLink:hover, QPushButton#BubbleEmail:hover {{
    background: {palette.hover};
    border-bottom: 1px solid {palette.line_strong};
}}
QPushButton#BubbleLink:pressed, QPushButton#BubbleEmail:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleImage {{
{common}
    background: {palette.code_bg};
    border-left: 2px solid {palette.image_line};
}}
QPushButton#BubbleImage:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleMedia {{
{common}
    border-left: 2px dashed {palette.image_line};
}}
QPushButton#BubbleMedia:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleArchive {{
{common}
    border-left: 2px dotted {palette.file_line};
}}
QPushButton#BubbleArchive:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleFile {{
{common}
    border-left: 2px solid {palette.file_line};
}}
QPushButton#BubbleFile:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
QPushButton#BubbleNumber {{
{common}
    font-family: "{MONO_FONT}";
    font-size: {max(10, font_size - 1)}px;
}}
QPushButton#BubbleNumber:pressed {{
    background: {palette.selected};
    padding-top: 4px;
    padding-bottom: 2px;
}}
"""


# 气泡类型 → QSS objectName（UI 层按此设置 objectName）
BUBBLE_OBJECT_NAMES: dict[str, str] = {
    "link": "BubbleLink",
    "email": "BubbleEmail",
    "image": "BubbleImage",
    "media": "BubbleMedia",
    "archive": "BubbleArchive",
    "path": "BubbleFile",
    "code": "BubbleCode",
    "number": "BubbleNumber",
    "text": "BubbleText",
}


def bubble_object_name(kind: str) -> str:
    """把气泡类型映射为 QSS objectName，未知类型回退普通文本气泡。"""
    return BUBBLE_OBJECT_NAMES.get(kind, "BubbleText")


def thumbnail_qss(palette: Palette, *, radius: int = 6, line_width: int = 1) -> str:
    """列表内缩略图样式（细边框，不加阴影，保持线条风）。"""
    return f"""
QLabel#Thumb {{
    border: {max(1, line_width)}px solid {palette.line};
    border-radius: {radius}px;
    padding: 0px;
    background: {palette.surface};
}}
QLabel#KindTag {{
    color: {palette.text_muted};
    border: 1px solid {palette.line};
    border-radius: {radius}px;
    padding: 1px 6px;
    font-size: 11px;
}}
QLabel#EmptyHint {{
    color: {palette.text_muted};
    padding: 24px 8px;
}}
"""
