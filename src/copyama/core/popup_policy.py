"""弹窗生命周期策略：何时自动消失、何时常驻。

对应需求「还要自动消失和点击常驻」。
纯逻辑，无 Qt 依赖，便于单测覆盖各种边界。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PopupState:
    """弹窗当前状态（由 UI 层每次定时器触发时更新）。"""

    pinned: bool = False       # 用户已把窗口固定（常驻）
    hovered: bool = False      # 鼠标悬停在窗口内 → 暂停倒计时
    interacted: bool = False   # 已点击过条目 / 输入过搜索词
    dragging: bool = False     # 正在拖动窗口


def should_auto_hide(
    state: PopupState,
    *,
    timeout_seconds: int,
    elapsed_ms: int,
    pin_on_click: bool = False,
) -> bool:
    """判断是否应自动消失。

    规则（按优先级）：
    1. 超时设置为 0 → 永不自动消失；
    2. 已固定 / 拖动中 / 鼠标悬停 → 暂停消失；
    3. 用户已交互且开启「点击常驻」→ 不再消失；
    4. 其余情况：超过设定时长即消失。
    """
    if timeout_seconds <= 0:
        return False
    if state.pinned or state.dragging or state.hovered:
        return False
    if state.interacted and pin_on_click:
        return False
    return elapsed_ms >= timeout_seconds * 1000


def remaining_ms(
    state: PopupState, *, timeout_seconds: int, elapsed_ms: int, pin_on_click: bool = False
) -> int:
    """剩余毫秒数；不会自动消失时返回 -1（UI 据此隐藏进度提示）。"""
    if state.pinned or state.dragging or state.hovered:
        return -1
    if state.interacted and pin_on_click:
        return -1
    if timeout_seconds <= 0:
        return -1
    return max(0, timeout_seconds * 1000 - elapsed_ms)
