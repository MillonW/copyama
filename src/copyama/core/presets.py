"""职业预设模板：一键把配置切到某类人群的常用组合。

「职业对口默认设置模板」的落地位置。模板只覆盖与工作流强相关的字段，
其余保留用户已有设置（见 apply_preset）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from copyama.config import Config
from copyama.core.placement import Placement


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    description: str
    overrides: dict[str, Any]


PRESETS: dict[str, Preset] = {
    "general": Preset(
        key="general",
        name="通用",
        description="默认配置，适合不明确的场景",
        overrides={},
    ),
    "programmer": Preset(
        key="programmer",
        name="程序员",
        description="深色主题、大容量、代码/JSON 友好、窗口贴在光标旁",
        overrides={
            "max_items": 800, "max_age_days": 7, "page_size": 80,
            "theme": "dark", "color_scheme": "graphite", "hotkey": "Ctrl+Shift+V",
            "popup_position": "cursor", "popup_width": 520, "popup_height": 620,
            "auto_hide_seconds": 0, "pin_on_click": True,
            "token_bubbles": True, "format_json": True, "code_highlight": True,
            "thumb_max_px": 192, "blob_quota_mb": 500,
        },
    ),
    "designer": Preset(
        key="designer",
        name="设计师",
        description="大预览、图片优先、浅色主题、常驻不自动消失",
        overrides={
            "max_items": 400, "max_age_days": 7, "page_size": 40,
            "theme": "light", "color_scheme": "fog", "hotkey": "Ctrl+Alt+V",
            "popup_position": "active_center", "popup_width": 640, "popup_height": 720,
            "auto_hide_seconds": 0, "pin_on_click": True, "show_preview": True,
            "token_bubbles": False, "thumb_max_px": 320, "blob_quota_mb": 800,
        },
    ),
    "writer": Preset(
        key="writer",
        name="文案 / 运营",
        description="大容量、自动清洗空白、选词气泡、浅色主题",
        overrides={
            "max_items": 600, "max_age_days": 7, "theme": "light",
            "color_scheme": "ink", "hotkey": "Ctrl+Alt+V",
            "popup_position": "cursor", "auto_hide_seconds": 30,
            "clean_whitespace_on_paste": True, "token_bubbles": True,
        },
    ),
    "student": Preset(
        key="student",
        name="学生",
        description="条目适中、自动消失快、居中弹出",
        overrides={
            "max_items": 200, "max_age_days": 7, "theme": "light",
            "color_scheme": "mono", "hotkey": "Ctrl+Shift+V",
            "popup_position": "active_center", "auto_hide_seconds": 15,
            "token_bubbles": True,
        },
    ),
    "finance": Preset(
        key="finance",
        name="财务",
        description="数字友好、常驻不消失、屏蔽网银类进程",
        overrides={
            "max_items": 500, "max_age_days": 30, "theme": "light",
            "color_scheme": "nord", "hotkey": "Ctrl+Alt+V",
            "popup_position": "cursor", "auto_hide_seconds": 0, "pin_on_click": True,
            "blacklist": ["icbc", "ccb", "abchina", "boc", "cmbchina", "alipay"],
            "token_bubbles": True,
        },
    ),
    "support": Preset(
        key="support",
        name="客服",
        description="话术片段多、托盘弹出、自动消失最快",
        overrides={
            "max_items": 400, "max_age_days": 3, "theme": "light",
            "color_scheme": "sakura", "hotkey": "Ctrl+Shift+C",
            "popup_position": "tray", "auto_hide_seconds": 10, "token_bubbles": True,
        },
    ),
    "hr": Preset(
        key="hr",
        name="行政 / HR",
        description="居中弹出、适中容量、便于批量整理",
        overrides={
            "max_items": 300, "max_age_days": 14, "theme": "light",
            "color_scheme": "mono", "hotkey": "Ctrl+Alt+V",
            "popup_position": "active_center", "auto_hide_seconds": 25,
        },
    ),
    "sales": Preset(
        key="sales",
        name="销售",
        description="名片/话术/链接高频，光标弹出",
        overrides={
            "max_items": 400, "max_age_days": 7, "theme": "light",
            "color_scheme": "nord", "hotkey": "Ctrl+Alt+V",
            "popup_position": "cursor", "auto_hide_seconds": 30, "token_bubbles": True,
        },
    ),
}


def list_presets() -> list[Preset]:
    """返回全部模板（UI 下拉框用）。"""
    return list(PRESETS.values())


def apply_preset(config: Config, key: str) -> Config:
    """在现有配置上套用模板，返回新 Config（不修改入参）。"""
    preset = PRESETS.get(key)
    if preset is None:
        return config
    unknown = set(preset.overrides) - {f for f in config.__dataclass_fields__}
    if unknown:  # 配置字段改名时尽早暴露，避免静默失效
        raise KeyError(f"模板 {key} 引用了未知配置字段：{sorted(unknown)}")
    return replace(config, **preset.overrides)
