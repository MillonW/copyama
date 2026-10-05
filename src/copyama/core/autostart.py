"""开机自启（Windows）。

⚠️ 安全说明：本模块会写入注册表启动项
``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``，属于**系统启动项变更**。
因此：
- 默认**关闭**，只有用户在设置界面显式打开开关、或在首次使用的询问弹窗里选择
  「开启」时才调用 ``enable()``；
- ``enable()`` 强制要求 ``confirm=True``，防止被静默调用；
- 仅写 HKCU（当前用户），不触碰 HKLM，无需管理员权限，随时可关闭。

非 Windows 平台一律抛 NotImplementedError / 返回 False，不静默失败、不假装成功。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from copyama.utils.logger import get_logger

log = get_logger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE = "Copyama"


@dataclass(frozen=True)
class AutostartState:
    """自启状态：是否已开启、命令行长什么样、是否需要首次询问。"""

    supported: bool
    enabled: bool
    command: str
    needs_first_ask: bool


def should_ask_on_first_run(config) -> bool:
    """首次使用时是否应弹窗询问开机自启（仅在 Windows 且从未问过时）。"""
    return sys.platform == "win32" and not getattr(config, "autostart_asked", False)


class AutostartManager:
    """开机自启开关（HKCU Run 键）。"""

    def __init__(self, exe_path: str | None = None) -> None:
        # 打包后 sys.executable 即 exe；源码运行时为 python.exe，需带上 -m 参数
        self.exe_path = exe_path or sys.executable

    def is_supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def command(self) -> str:
        """写入注册表的命令行。"""
        if getattr(sys, "frozen", False):
            return f'"{self.exe_path}"'
        return f'"{self.exe_path}" -m copyama'

    def is_enabled(self) -> bool:
        """读取注册表判断是否已开启；非 Windows 或读取失败一律返回 False。"""
        if not self.is_supported():
            return False
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, APP_VALUE)
            return bool(value)
        except FileNotFoundError:
            return False
        except OSError as exc:  # pragma: no cover - 权限异常等
            log.debug("读取自启项失败：%s", exc)
            return False

    def state(self, config=None) -> AutostartState:
        """汇总自启状态，供设置界面与首次引导展示。"""
        return AutostartState(
            supported=self.is_supported(),
            enabled=self.is_enabled(),
            command=self.command,
            needs_first_ask=should_ask_on_first_run(config) if config is not None else False,
        )

    def enable(self, confirm: bool = False) -> None:
        """写入启动项。``confirm`` 必须为 True，强制调用方显式确认。"""
        if not confirm:
            raise PermissionError("开机自启属系统启动项变更，需用户显式确认后执行")
        if not self.is_supported():
            raise NotImplementedError("开机自启仅支持 Windows")
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_VALUE, 0, winreg.REG_SZ, self.command)
        log.info("已写入开机自启项：%s", self.command)

    def disable(self) -> None:
        """移除启动项（低风险，无需额外确认）。"""
        if not self.is_supported():
            return
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, APP_VALUE)
            log.info("已移除开机自启项")
        except FileNotFoundError:
            return
        except OSError as exc:  # pragma: no cover
            log.debug("移除自启项失败：%s", exc)

    def sync(self, enabled: bool, *, confirm: bool = False) -> bool:
        """按目标状态开关自启，返回实际生效状态。"""
        if enabled:
            self.enable(confirm=confirm)
        else:
            self.disable()
        return self.is_enabled()
