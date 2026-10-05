"""黑名单与密码框过滤：决定「这条剪贴是否值得记录」。

两条防线：
1. 应用黑名单：来源进程名命中即跳过（用户显式配置）；
2. 密码框启发式：来源窗口是密码输入框时跳过（默认开启）。
"""

from __future__ import annotations

from copyama.utils.logger import get_logger

log = get_logger(__name__)


def is_blacklisted(source_app: str | None, blacklist: list[str]) -> bool:
    """判断来源进程是否在黑名单中（大小写不敏感，支持精确进程名或子串）。"""
    if not source_app:
        return False
    name = source_app.casefold()
    return any(item.casefold() in name for item in blacklist if item)


def looks_like_password_field(window_class: str | None, style: int | None) -> bool:
    """启发式判断当前焦点是否为密码框。

    依据：窗口类名含 "Edit" 且带 ES_PASSWORD(0x0020) 样式。
    局限：UWP / 自绘控件不适用，需靠应用黑名单兜底。
    """
    if not window_class or style is None:
        return False
    return "edit" in window_class.casefold() and bool(style & 0x0020)


def should_skip(
    source_app: str | None,
    blacklist: list[str],
    window_class: str | None = None,
    style: int | None = None,
    exclude_passwords: bool = True,
) -> bool:
    """综合判定是否跳过本次剪贴记录。"""
    if is_blacklisted(source_app, blacklist):
        log.debug("跳过：来源 %s 命中黑名单", source_app)
        return True
    if exclude_passwords and looks_like_password_field(window_class, style):
        log.debug("跳过：疑似密码框（class=%s, style=%s）", window_class, style)
        return True
    return False
