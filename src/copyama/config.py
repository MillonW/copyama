"""配置加载与持久化。

配置文件：``%APPDATA%\\Copyama\\config.json``（非 Windows 回退 ``~/.config/Copyama``）
设计原则：字段少、可读、可手工编辑；缺字段用默认值补齐，不因配置损坏而启动失败。
新增字段务必给默认值，保证旧配置向后兼容。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

APP_NAME = "Copyama"


def default_data_dir() -> Path:
    """返回应用数据目录（Windows 用 %APPDATA%，其它平台回退用户主目录）。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


@dataclass
class Config:
    """用户配置。字段顺序即设置界面的分组顺序。"""

    # —— 通用 ——
    preset: str = "general"          # 当前套用的职业模板 key
    max_items: int = 200             # 历史条数上限，超出即淘汰最旧的未固定项
    max_age_days: int = 7            # 保留天数，更早的自动清理；0 = 不按时间清理
    date_grouping: bool = True       # 历史列表按日期折叠分组
    group_mode: str = "day"          # day（按自然日）| bucket（今天/昨天/本周内/更早）
    page_size: int = 60              # 分页加载步长，避免一次性渲染全量
    purge_interval_minutes: int = 30  # 后台清理周期（分钟）
    single_instance: bool = True     # 重复启动时唤起已有窗口
    autostart: bool = False          # 开机自启（写注册表 Run 键，需显式确认）
    autostart_asked: bool = False    # 是否已就开机自启询问过用户（首次启动弹窗）
    first_run_done: bool = False     # 首次运行引导是否完成

    # —— 外观 ——
    theme: str = "system"            # system | light | dark
    color_scheme: str = "mono"       # 配色方案：mono|ink|graphite|fog|nord|sakura
    accent_color: str = "#111111"    # 强调色（线条风下建议用深灰/纯黑）
    line_width: int = 1              # 线条宽度（1px 细线，ins 高级风关键）
    font_family: str = "Microsoft YaHei UI"
    font_size: int = 13
    corner_radius: int = 10
    list_density: str = "comfortable"  # compact | comfortable
    show_preview: bool = True
    animation: bool = True

    # —— 弹窗行为 ——
    hotkey: str = "Ctrl+Alt+V"       # 全局唤起快捷键
    popup_width: int = 460
    popup_height: int = 560
    popup_position: str = "cursor"   # cursor|active_center|primary_center|tray|remember|fixed
    fixed_position: list[int] = field(default_factory=lambda: [100, 100])
    auto_hide_seconds: int = 20      # 0 = 不自动消失
    pin_on_click: bool = False       # 点击条目后窗口常驻
    hide_on_blur: bool = True

    # —— 内容与选词 ——
    token_bubbles: bool = True       # 文本自动切气泡，支持选词粘贴
    token_min_length: int = 1
    cjk_segmenter: str = "builtin"   # builtin | jieba
    clean_whitespace_on_paste: bool = False
    format_json: bool = False
    code_highlight: bool = False
    ocr_enabled: bool = False

    # —— 捕获范围 ——
    capture_text: bool = True
    capture_image: bool = True
    capture_files: bool = True       # 图片/音视频/压缩包/文档等任意文件
    store_images: bool = True        # 保存图片原图（关掉则仅存缩略图，省空间）
    thumb_max_px: int = 256          # 缩略图最长边（列表只加载缩略图）
    thumb_format: str = "webp"       # 缩略图格式：webp 体积最小
    blob_quota_mb: int = 300         # 原图总占用上限(MB)，超出从最旧图片开始清
    max_image_mb: int = 10
    min_text_length: int = 1
    excluded_kinds: list[str] = field(default_factory=list)  # FileKind 值列表

    # —— 隐私 ——
    blacklist: list[str] = field(default_factory=list)
    exclude_passwords: bool = True
    encrypt_db: bool = False

    # —— 存储与备份 ——
    backup_enabled: bool = False
    backup_interval_hours: int = 24
    backup_keep: int = 7
    vacuum_on_start: bool = True     # 启动时回收数据库空洞，控制体积

    @property
    def config_path(self) -> Path:
        return default_data_dir() / "config.json"

    def with_updates(self, **kwargs: Any) -> "Config":
        """返回覆盖若干字段后的新配置（不修改自身，便于撤销）。"""
        unknown = set(kwargs) - {f.name for f in fields(self)}
        if unknown:
            raise KeyError(f"未知配置字段：{sorted(unknown)}")
        return replace(self, **kwargs)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """读取配置；文件缺失或损坏时回退到默认配置。"""
        target = path or cls().config_path
        if not target.exists():
            return cls()
        try:
            raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        """原子写回配置：先写临时文件再替换，避免中途崩溃损坏配置。"""
        target = path or self.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, target)
