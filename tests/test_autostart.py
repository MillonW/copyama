"""开机自启：首次询问判定、非 Windows 行为、命令形状。"""

import sys

import pytest

from copyama.config import Config
from copyama.core.autostart import AutostartManager, AutostartState, should_ask_on_first_run


def test_command_shape_for_source_run():
    mgr = AutostartManager(exe_path=r"C:\Python\python.exe")
    assert mgr.command.startswith('"C:\\Python\\python.exe"')
    assert mgr.command.endswith("-m copyama")


def test_enable_requires_explicit_confirm():
    # 无论平台如何，未确认一律拒绝（系统启动项变更）
    with pytest.raises(PermissionError):
        AutostartManager().enable()


def test_behavior_off_windows():
    mgr = AutostartManager(exe_path="/usr/bin/python3")
    if sys.platform != "win32":
        assert mgr.is_supported() is False
        assert mgr.is_enabled() is False
        mgr.disable()          # 幂等：非 Windows 下静默返回
        with pytest.raises(NotImplementedError):
            mgr.enable(confirm=True)


def test_first_run_ask_rule():
    cfg = Config()
    cfg.autostart_asked = False
    assert should_ask_on_first_run(cfg) is (sys.platform == "win32")
    cfg.autostart_asked = True
    assert should_ask_on_first_run(cfg) is False


def test_state_dataclass_reports_fields():
    mgr = AutostartManager(exe_path="/usr/bin/python3")
    state = mgr.state(Config())
    assert isinstance(state, AutostartState)
    assert state.supported is (sys.platform == "win32")
    assert isinstance(state.command, str)
    assert state.needs_first_ask is (sys.platform == "win32")
