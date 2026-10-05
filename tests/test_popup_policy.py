"""弹窗自动消失 / 常驻策略单测。"""

from __future__ import annotations

from copyama.core.popup_policy import PopupState, remaining_ms, should_auto_hide

BASE = dict(timeout_seconds=20, elapsed_ms=0)


def test_timeout_zero_never_hides():
    assert should_auto_hide(PopupState(), timeout_seconds=0, elapsed_ms=999_999) is False


def test_hides_after_timeout():
    assert should_auto_hide(PopupState(), timeout_seconds=20, elapsed_ms=19_999) is False
    assert should_auto_hide(PopupState(), timeout_seconds=20, elapsed_ms=20_000) is True


def test_pinned_never_hides():
    assert should_auto_hide(PopupState(pinned=True), timeout_seconds=5, elapsed_ms=99_999) is False


def test_hover_pauses_countdown():
    state = PopupState(hovered=True)
    assert should_auto_hide(state, timeout_seconds=5, elapsed_ms=99_999) is False


def test_dragging_pauses_countdown():
    state = PopupState(dragging=True)
    assert should_auto_hide(state, timeout_seconds=5, elapsed_ms=99_999) is False


def test_pin_on_click_keeps_after_interaction():
    state = PopupState(interacted=True)
    assert should_auto_hide(state, timeout_seconds=5, elapsed_ms=99_999, pin_on_click=True) is False
    # 未开启「点击常驻」时仍会消失
    assert should_auto_hide(state, timeout_seconds=5, elapsed_ms=99_999) is True


def test_remaining_ms():
    state = PopupState()
    assert remaining_ms(state, timeout_seconds=20, elapsed_ms=5_000) == 15_000
    assert remaining_ms(state, timeout_seconds=20, elapsed_ms=25_000) == 0
    assert remaining_ms(PopupState(pinned=True), timeout_seconds=20, elapsed_ms=0) == -1
    assert remaining_ms(state, timeout_seconds=0, elapsed_ms=0) == -1
