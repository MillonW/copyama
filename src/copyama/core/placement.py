"""弹窗位置策略：决定唤起时窗口出现在哪儿，并保证不越出屏幕。

纯函数实现，输入全部为普通元组，便于跨平台单测。
坐标系约定：与 Win32 一致，原点在**主屏左上角**，右下为正。
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

Point = tuple[int, int]
Rect = tuple[int, int, int, int]  # (x, y, w, h)


class Placement(str, Enum):
    CURSOR = "cursor"                 # 光标附近（默认）
    ACTIVE_CENTER = "active_center"   # 活动屏幕居中
    PRIMARY_CENTER = "primary_center" # 主屏居中
    TRAY = "tray"                     # 托盘图标附近（右下）
    REMEMBER = "remember"             # 记住上次位置
    FIXED = "fixed"                   # 固定坐标


DEFAULT_MARGIN = 12


class PositionResult(NamedTuple):
    x: int
    y: int


def clamp_to_screen(x: int, y: int, size: tuple[int, int], screen: Rect) -> PositionResult:
    """把窗口矩形收敛到屏幕范围内；窗口大于屏幕时贴左上角。"""
    sx, sy, sw, sh = screen
    w, h = size
    if w >= sw:
        x = sx
    else:
        x = min(max(x, sx), sx + sw - w)
    if h >= sh:
        y = sy
    else:
        y = min(max(y, sy), sy + sh - h)
    return PositionResult(x, y)


def compute_position(
    strategy: Placement,
    size: tuple[int, int],
    *,
    cursor: Point | None = None,
    screen: Rect | None = None,
    tray: Point | None = None,
    last: Point | None = None,
    fixed: Point | None = None,
    margin: int = DEFAULT_MARGIN,
) -> PositionResult:
    """按策略计算窗口左上角坐标，并保证不越界。

    - CURSOR：出现在鼠标右下方 ``margin`` 处（越界时自动回收到左上）
    - TRAY：贴托盘图标上方（通常右下角）
    - 其余：见 Placement 枚举注释
    """
    screen = screen or (0, 0, 1920, 1080)

    if strategy is Placement.CURSOR and cursor is not None:
        x, y = cursor[0] + margin, cursor[1] + margin
    elif strategy is Placement.TRAY and tray is not None:
        x, y = tray[0] - size[0] + margin, tray[1] - size[1] - margin
    elif strategy is Placement.REMEMBER and last is not None:
        x, y = last
    elif strategy is Placement.FIXED and fixed is not None:
        x, y = fixed
    else:
        # ACTIVE_CENTER / PRIMARY_CENTER / 缺参回退：屏幕居中
        x = screen[0] + (screen[2] - size[0]) // 2
        y = screen[1] + (screen[3] - size[1]) // 2
    return clamp_to_screen(x, y, size, screen)


def screen_at_point(cursor_x: int, cursor_y: int, screens: list[Rect]) -> Rect:
    """返回包含指定点的屏幕；都不包含时回退到最近的屏幕（按中心距离）。"""
    for rect in screens:
        sx, sy, sw, sh = rect
        if sx <= cursor_x < sx + sw and sy <= cursor_y < sy + sh:
            return rect
    if not screens:
        return (0, 0, 1920, 1080)
    return min(
        screens,
        key=lambda r: (r[0] + r[2] / 2 - cursor_x) ** 2 + (r[1] + r[3] / 2 - cursor_y) ** 2,
    )
