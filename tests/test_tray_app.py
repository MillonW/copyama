"""托盘交互语义 + 应用装配层（离屏运行，注入临时存储目录）。"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from copyama.config import Config
from copyama.core.models import Clip, ClipType
from copyama.ui.tray import CLEAR_PURGE, CLEAR_SOFT, TrayIcon, clear_mode


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_app(monkeypatch, tmp_path):
    """构造一个把数据库落到 tmp_path 的应用实例（不启动事件循环）。"""
    import copyama.app as app_mod

    real_storage = app_mod.Storage
    monkeypatch.setattr(
        app_mod,
        "Storage",
        lambda **kw: real_storage(db_path=tmp_path / "copyama.db", **kw),
    )
    monkeypatch.setattr(app_mod.Config, "load", classmethod(lambda cls, path=None: cls()))
    app = app_mod.CopyamaApp([])
    app.config.purge_interval_minutes = 0
    return app


class TestClearMode:
    def test_default_is_soft_delete(self):
        assert clear_mode(False) == CLEAR_SOFT

    def test_checked_means_hard_delete(self):
        assert clear_mode(True) == CLEAR_PURGE


class TestTray:
    def test_menu_actions_present(self, qapp):
        tray = TrayIcon(Config())
        for name in ("act_show", "act_settings", "act_pause", "act_clear", "act_quit"):
            assert hasattr(tray, name)

    def test_pause_is_checkable_and_defaults_off(self, qapp):
        tray = TrayIcon(Config())
        assert tray.act_pause.isCheckable()
        assert tray.act_pause.isChecked() is False

    def test_hard_delete_defaults_false(self, qapp):
        """默认必须是软删——绝不能在用户没勾选时物理清除。"""
        tray = TrayIcon(Config())
        assert tray.hard_delete is False


class TestAppWiring:
    def test_startup_maintenance_returns_report(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        report = app.startup_maintenance()
        assert isinstance(report, dict)
        app.storage.close()

    def test_capture_then_soft_clear(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        for i in range(3):
            app._on_clip(Clip(type=ClipType.TEXT, content=f"hello-{i}"), None)
        assert app.storage.count() == 3

        assert app.clear_history() == 3          # 软删
        assert app.storage.count() == 0
        assert app.storage.count(include_deleted=True) == 3  # 仍可恢复
        app.storage.close()

    def test_hard_clear_is_permanent(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        app.storage.store_text("keep me")
        assert app.clear_history() == 1
        assert app.clear_history(hard=True) == 1
        assert app.storage.count(include_deleted=True) == 0
        app.storage.close()

    def test_privacy_filter_is_noop_without_platform(self, monkeypatch, tmp_path):
        """拿不到前台窗口信息时不拦截，避免误丢用户正常复制的内容。"""
        app = _make_app(monkeypatch, tmp_path)
        app.config.blacklist = ["KeePass.exe"]
        assert app._should_skip_privacy() is False
        app.storage.close()

    def test_skipped_clip_never_reaches_storage(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        monkeypatch.setattr(app, "_should_skip_privacy", lambda: True)
        app._on_clip(Clip(type=ClipType.TEXT, content="super-secret"), None)
        assert app.storage.count() == 0
        app.storage.close()

    def test_settings_apply_syncs_policy(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        new_cfg = app.config.with_updates(max_items=42, max_age_days=3)
        app._on_settings_applied(new_cfg)
        assert app.storage.policy.max_items == 42
        assert app.storage.policy.max_age_days == 3
        app.storage.close()

    def test_shutdown_is_safe_without_gui(self, monkeypatch, tmp_path):
        app = _make_app(monkeypatch, tmp_path)
        app.shutdown()  # 未建 GUI / 未起监听时也必须安全
        app.shutdown()  # 重复调用同样安全
