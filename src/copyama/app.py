"""应用装配与生命周期。

职责：把配置、存储、监听、热键、弹窗、托盘、设置界面串起来，并处理退出清理。
本模块是唯一允许触碰「系统级」能力（全局热键、开机自启）的地方。

启动顺序：单实例检查 → 启动维护 → 建 GUI → 托盘 → 剪贴板监听 → 热键 →
后台清理定时器 → 首次自启询问 → 事件循环。
"""

from __future__ import annotations

import sys

from copyama.config import Config
from copyama.core.autostart import AutostartManager, should_ask_on_first_run
from copyama.core.blacklist import should_skip
from copyama.core.clipboard import ClipboardWatcher
from copyama.core.models import Clip
from copyama.data.storage import Storage
from copyama.ui.hotkey import validate
from copyama.utils.logger import get_logger

log = get_logger(__name__)

HOTKEY_ID_TOGGLE = 1
SINGLE_INSTANCE_KEY = "copyama-single-instance-v1"


class CopyamaApp:
    """应用门面。"""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.argv = list(argv) if argv is not None else list(sys.argv)
        self.config = Config.load()
        self.storage = Storage(
            max_items=self.config.max_items,
            max_age_days=self.config.max_age_days,
            thumb_max_px=self.config.thumb_max_px,
            thumb_format=self.config.thumb_format,
            blob_quota_mb=self.config.blob_quota_mb,
        )
        self.watcher = ClipboardWatcher(self._on_clip, self.config)
        self.autostart = AutostartManager()
        self._window = None       # MainWindow（延迟创建，避免非 Windows 导入即失败）
        self._tray = None
        self._qapp = None
        self._hotkey_host = None
        self._timer = None
        self._shm = None
        self.maintenance: dict[str, int] = {}

    # —— 启动 ——
    def run(self) -> int:
        """启动应用主循环，返回进程退出码。"""
        if self.config.single_instance and not self._acquire_single_instance():
            log.warning("检测到已有实例在运行，本次启动直接退出")
            return 0

        from PySide6.QtWidgets import QApplication

        from copyama.ui.main_window import MainWindow
        from copyama.ui.tray import TrayIcon

        self.maintenance = self.startup_maintenance()
        problems = validate(self.config.hotkey)
        if problems:
            log.warning("热键 %s 有问题：%s", self.config.hotkey, problems)

        app = QApplication(self.argv)
        app.setApplicationName("Copyama")
        app.setQuitOnLastWindowClosed(False)  # 托盘常驻，关窗不等于退出
        self._qapp = app

        self._window = MainWindow(self.config, self.storage, self.watcher)
        self._window.request_settings.connect(self.open_settings)
        self._tray = TrayIcon(self.config)
        self._connect_tray()
        self._tray.show()

        self.watcher.start()
        self._setup_hotkey()
        self._start_maintenance_timer()
        self._ask_autostart_if_needed()

        if not self.config.first_run_done:
            self.config.first_run_done = True
            self._save_config()

        log.info("Copyama 已启动（热键 %s）", self.config.hotkey)
        # 首次启动显示主窗口，让用户知道程序已在运行
        self.toggle_popup()
        return app.exec()

    def startup_maintenance(self) -> dict[str, int]:
        """启动维护：回收数据库空洞 + 一次完整清理（过期 / 超限 / 配额 / 孤儿）。

        这是「别臃肿、别卡」的兜底动作：即使长时间不打开界面，磁盘也不会越堆越大。
        """
        if self.config.vacuum_on_start:
            try:
                self.storage.vacuum()
            except Exception:  # pragma: no cover - 数据库被占用等
                log.exception("启动回收空间失败")
        result = self.storage.run_cleanup()
        log.info("启动维护完成：%s", result)
        return result

    def _acquire_single_instance(self) -> bool:
        """基于共享内存的单实例互斥；已存在实例时返回 False。"""
        try:
            from PySide6.QtCore import QSharedMemory

            self._shm = QSharedMemory(SINGLE_INSTANCE_KEY)
            if not self._shm.create(1):
                return False
        except Exception:  # noqa: BLE001 - 拿不到互斥锁不应阻断启动
            log.exception("单实例检查失败，按允许多实例处理")
            return True
        return True

    def _setup_hotkey(self) -> None:
        """注册全局热键；失败时托盘提示并引导到设置界面改键。"""
        if sys.platform != "win32":
            log.warning("当前平台 %s 不支持全局热键，跳过注册", sys.platform)
            return
        try:
            from copyama.ui.hotkey_host import HotkeyHost
            from copyama.ui.hotkey import parse_hotkey, VK_MAP

            self._hotkey_host = HotkeyHost(self.on_hotkey)
            ok = self._hotkey_host.start()
            if not ok:
                log.error("热键消息窗口创建失败，全局热键不可用")
                return
            # 解析热键并注册（直接通过 HotkeyHost，不走中间层）
            modifiers, key = parse_hotkey(self.config.hotkey)
            vk = VK_MAP.get(key, 0)
            if vk == 0 or not self._hotkey_host.register_hotkey(HOTKEY_ID_TOGGLE, modifiers, vk):
                self._notify_hotkey_conflict()
        except Exception:  # noqa: BLE001 - 热键不是核心功能，失败不阻断启动
            log.exception("全局热键初始化失败")

    def _notify_hotkey_conflict(self) -> None:
        """热键被占用时提示用户去设置里换一个组合。"""
        log.warning("热键 %s 注册失败，可能被其它程序占用", self.config.hotkey)
        if self._tray is not None:
            self._tray.showMessage(
                "Copyama：快捷键被占用",
                f"{self.config.hotkey} 可能已被其它程序占用，请在「设置 → 热键」中更换。",
            )

    def on_hotkey(self, hotkey_id: int) -> None:
        """热键回调（已切回主线程）。"""
        if hotkey_id == HOTKEY_ID_TOGGLE:
            self.toggle_popup()

    # —— 后台清理 ——
    def _start_maintenance_timer(self) -> None:
        """按配置周期跑后台清理；0 表示只在启动时清理一次。"""
        interval_minutes = int(self.config.purge_interval_minutes or 0)
        if interval_minutes <= 0:
            log.debug("后台清理周期为 0，仅启动时清理")
            return
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setInterval(interval_minutes * 60_000)
        timer.timeout.connect(self.run_background_cleanup)
        timer.start()
        self._timer = timer

    def run_background_cleanup(self) -> dict[str, int]:
        """定时清理：过期 / 超限 / 配额 / 孤儿文件。"""
        try:
            result = self.storage.run_cleanup()
            log.debug("后台清理完成：%s", result)
            return result
        except Exception:  # pragma: no cover - 清理失败不应影响使用
            log.exception("后台清理失败")
            return {}

    # —— 托盘接线 ——
    def _connect_tray(self) -> None:
        tray = self._tray
        tray.act_show.triggered.connect(self.toggle_popup)
        tray.act_settings.triggered.connect(self.open_settings)
        tray.act_pause.toggled.connect(self._on_pause_toggled)
        tray.act_clear.triggered.connect(self.on_clear_requested)
        tray.act_quit.triggered.connect(self.on_quit)
        # 左键/双击托盘图标也能唤起主窗口
        from PySide6.QtWidgets import QSystemTrayIcon
        tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason) -> None:
        """托盘图标激活：左键单击或双击都唤起主窗口。"""
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,    # 左键单击
            QSystemTrayIcon.ActivationReason.DoubleClick, # 左键双击
        ):
            self.toggle_popup()

    def _on_pause_toggled(self, paused: bool) -> None:
        if paused:
            self.watcher.pause()
            log.info("已暂停捕获")
        else:
            self.watcher.resume()
            log.info("已恢复捕获")

    def on_clear_requested(self) -> None:
        """清空历史：先二次确认，再按是否勾选「彻底删除」决定软删 / 物理清除。

        ⚠️ 破坏性操作：未经确认绝不执行；默认软删（可恢复）。
        """
        if self._tray is None or not self._tray.confirm_clear():
            return
        hard = self._tray.hard_delete
        removed = self.clear_history(hard=hard)
        log.info("已清空历史 %d 条（%s）", removed, "彻底删除" if hard else "移入回收站")
        if self._window is not None:
            self._window.refresh()

    def on_quit(self) -> None:
        """托盘退出：隐藏托盘 → 清理 → 退出事件循环。"""
        if self._tray is not None:
            self._tray.hide()
        self.shutdown()
        if self._qapp is not None:
            self._qapp.quit()

    # —— 开机自启（首次询问）——
    def _ask_autostart_if_needed(self) -> bool | None:
        """首次使用时弹窗询问是否开机自启；无论选择如何都记录「已询问」。

        仅写 HKCU Run 键，且在用户明确选择「开启」后才写入。
        """
        if not should_ask_on_first_run(self.config):
            return None
        asker = getattr(self._window, "ask_autostart", None)
        choice = asker() if callable(asker) else None
        if choice is not None:
            self.set_autostart(choice, confirm=True)
        self.config.autostart_asked = True
        self._save_config()
        return choice

    def set_autostart(self, enabled: bool, *, confirm: bool = False) -> bool:
        """开关开机自启并落盘（系统启动项变更，开启需显式确认）。"""
        try:
            actual = self.autostart.sync(enabled, confirm=confirm)
        except NotImplementedError as exc:
            log.warning("当前平台不支持开机自启：%s", exc)
            actual = False
        self.config.autostart = actual
        self._save_config()
        return actual

    def _save_config(self) -> None:
        """保存配置；失败不阻断主流程。"""
        try:
            Config.save(self.config)
        except Exception:  # pragma: no cover - 磁盘只读等
            log.exception("配置保存失败")

    # —— 事件 ——
    def _on_clip(self, clip: Clip, blob: bytes | None = None) -> None:
        """新剪贴内容入库（去重、淘汰由 Storage 负责）。

        ``blob`` 仅在平台层能拿到图片原始字节时传入；图片会落原图 + 生成缩略图。
        """
        if self._should_skip_privacy():
            return
        saved = self.storage.add(clip, blob)
        log.debug("捕获 %s -> id=%s", saved.type.value, saved.id)
        if self._window is not None and self._window.isVisible():
            self._window.refresh()

    def _should_skip_privacy(self) -> bool:
        """隐私过滤：命中应用黑名单或密码框时丢弃本条。

        平台层拿不到前台窗口信息（非 Windows / 读取失败）时按「不拦截」处理，
        避免因为探测失败而丢失用户正常的复制内容。
        """
        if not (self.config.blacklist or self.config.exclude_passwords):
            return False
        try:
            from copyama.platform import win32_clipboard

            process, _title, class_name, style = win32_clipboard.get_foreground_info()
        except Exception:  # noqa: BLE001
            return False
        return should_skip(
            process, self.config.blacklist, class_name, style, self.config.exclude_passwords
        )

    def ingest_image(self, clip: Clip, data: bytes) -> None:
        """图片入库专用入口：原图落盘、缩略图供列表展示。"""
        if not self.config.store_images:
            log.debug("已关闭「保存图片原图」，跳过")
            return
        self._on_clip(clip, data)

    def clear_history(self, hard: bool = False) -> int:
        """清空历史：默认软删进回收站（可恢复），``hard=True`` 才物理清除。"""
        if hard:
            removed = self.storage.purge_deleted()
            self.storage.vacuum()
            return removed
        ids = [c.id for c in self.storage.active_clips() if c.id is not None]
        return self.storage.delete(ids)

    def toggle_popup(self) -> None:
        """热键回调：显示 / 隐藏弹窗。"""
        if self._window is None:
            return
        if self._window.isVisible():
            self._window.hide()
            return
        if self.config.popup_position == "tray":
            from PySide6.QtGui import QCursor

            point = QCursor.pos()
            self._window.set_tray_anchor((point.x(), point.y()))
        self._window.show_popup()

    def open_settings(self) -> None:
        """打开设置窗口，应用后热重载主题与热键。"""
        from copyama.ui.settings_window import SettingsWindow

        dialog = SettingsWindow(
            self.config,
            self._on_settings_applied,
            probe_hotkey=self._probe_hotkey_available,
        )
        dialog.exec()

    def _probe_hotkey_available(self, spec: str) -> bool:
        """通过热键宿主真实探测某热键是否可注册。

        与实际注册用同一线程、同一窗口，结果 100% 一致。
        非 Windows 平台返回 True。
        """
        if self._hotkey_host is None:
            return True
        try:
            from copyama.ui.hotkey import parse_hotkey, VK_MAP

            modifiers, key = parse_hotkey(spec)
            vk = VK_MAP.get(key, 0)
            if vk == 0:
                return False
            return self._hotkey_host.probe_available(modifiers, vk)
        except Exception:  # noqa: BLE001
            log.exception("探测热键 %s 可用性失败", spec)
            return False

    def _on_settings_applied(self, config: Config) -> None:
        """设置保存：落盘 → 热重载主题 → 必要时重注册热键。"""
        self._save_config()
        # 仅这两项支持热更新；缩略图尺寸 / 格式 / 配额属构造期参数，重启后生效
        self.storage.set_policy(max_items=config.max_items, max_age_days=config.max_age_days)
        if self._window is not None:
            self._window.apply_theme()
            self._window.refresh()
        self._reload_hotkey()
        self._start_maintenance_timer()

    def _reload_hotkey(self) -> None:
        """配置变更后重注册热键（先注销旧的，失败则提示）。"""
        if self._hotkey_host is None:
            return
        try:
            from copyama.ui.hotkey import parse_hotkey, VK_MAP

            self._hotkey_host.unregister_all()
            modifiers, key = parse_hotkey(self.config.hotkey)
            vk = VK_MAP.get(key, 0)
            if vk == 0 or not self._hotkey_host.register_hotkey(HOTKEY_ID_TOGGLE, modifiers, vk):
                self._notify_hotkey_conflict()
            else:
                log.info("热键已更新为 %s", self.config.hotkey)
        except Exception:  # noqa: BLE001
            log.exception("重注册热键失败")

    # —— 退出 ——
    def shutdown(self) -> None:
        """退出清理：停定时器、注销热键、停止监听、关闭数据库。"""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._hotkey_host is not None:
            self._hotkey_host.stop()
        self.watcher.stop()
        self.storage.close()
        if self._shm is not None:
            try:
                self._shm.detach()
            except Exception:  # noqa: BLE001
                log.debug("释放单实例锁失败", exc_info=True)
        log.info("Copyama 已退出")


def main(argv: list[str] | None = None) -> int:
    return CopyamaApp(argv if argv is not None else sys.argv).run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
