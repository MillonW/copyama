"""热键注册：非 Windows 的降级行为与状态管理。"""

from __future__ import annotations

import sys

import pytest

from copyama.ui.hotkey import HotkeyManager

non_windows = pytest.mark.skipif(sys.platform == "win32", reason="该断言只在非 Windows 成立")


@non_windows
def test_register_declines_without_windows():
    mgr = HotkeyManager(0)
    assert mgr.register(1, "Ctrl+Alt+V") is False
    assert mgr.registered == {}


def test_register_rejects_invalid_spec():
    mgr = HotkeyManager(0)
    assert mgr.register(1, "Ctrl+Alt") is False          # 缺主键
    assert mgr.register(1, "Ctrl+NoSuchKey") is False    # 未知按键
    assert mgr.registered == {}


def test_unregister_all_is_idempotent():
    mgr = HotkeyManager(0)
    mgr.unregister_all()  # 空表调用不应抛异常

    mgr._registered[7] = "Ctrl+Alt+V"  # 模拟已注册状态
    mgr.unregister_all()
    assert mgr.registered == {}


def test_registered_returns_copy():
    mgr = HotkeyManager(0)
    mgr._registered[3] = "Ctrl+Alt+C"
    snapshot = mgr.registered
    snapshot[99] = "fake"
    assert 99 not in mgr.registered
