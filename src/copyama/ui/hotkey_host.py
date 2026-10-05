"""Win32 全局热键宿主：在独立线程创建隐藏窗口，负责注册/注销/探测。

所有热键操作（注册、注销、探测）都通过 ``SendMessageW`` 投递到
**同一个热键线程 + 同一个窗口** 里执行，确保探测结果和实际注册
100% 一致，不会出现「显示可用但保存失败」的情况。

非 Windows 平台 ``start()`` 返回 False（只记警告，不假装成功）。
"""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal

from copyama.utils.logger import get_logger

log = get_logger(__name__)

WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002
WM_QUIT = 0x0012

# 自定义消息：主线程 → 热键线程的同步请求（SendMessage 阻塞等待返回值）
WM_COPYAMA_REGISTER = 0x0401      # wParam=id, lParam=MAKELPARAM(modifiers, vk)
WM_COPYAMA_UNREGISTER = 0x0402    # wParam=id
WM_COPYAMA_PROBE = 0x0403         # lParam=MAKELPARAM(modifiers, vk)
WM_COPYAMA_UNREGISTER_ALL = 0x0404

CLASS_NAME = "CopyamaHotkeyWindow"


def _makelong(lo: int, hi: int) -> int:
    """模拟 Win32 MAKELPARAM 宏：把两个 16 位值塞进 32 位。"""
    return (lo & 0xFFFF) | ((hi & 0xFFFF) << 16)


def _loword(val: int) -> int:
    return val & 0xFFFF


def _hiword(val: int) -> int:
    return (val >> 16) & 0xFFFF


class _Bridge(QObject):
    """把子线程的热键事件排到主线程（QueuedConnection）。"""

    triggered = Signal(int)


class HotkeyHost:
    """全局热键宿主：线程安全的注册 / 注销 / 探测。"""

    def __init__(self, on_trigger) -> None:
        self._bridge = _Bridge()
        self._bridge.triggered.connect(on_trigger, Qt.ConnectionType.QueuedConnection)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._wndproc = None
        self._ready = threading.Event()
        self.hwnd: int | None = None
        self._registered: dict[int, tuple[int, int]] = {}  # id -> (modifiers, vk)

    def start(self, timeout: float = 3.0) -> bool:
        """启动热键线程，返回是否成功。"""
        if sys.platform != "win32":
            log.warning("全局热键仅支持 Windows，当前平台 %s 跳过", sys.platform)
            return False
        self._thread = threading.Thread(target=self._run, name="copyama-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.hwnd is not None

    def stop(self) -> None:
        """退出消息循环并回收线程。"""
        if sys.platform != "win32" or self._thread is None:
            return
        try:
            import ctypes

            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        except Exception:  # noqa: BLE001
            log.debug("发送热键线程退出消息失败", exc_info=True)
        self._thread.join(timeout=2.0)

    # —— 对外 API（线程安全，从主线程调用，阻塞等待结果）——

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        """注册热键。返回是否成功。"""
        if self.hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t  # LRESULT

        lparam = _makelong(modifiers, vk)
        result = user32.SendMessageW(self.hwnd, WM_COPYAMA_REGISTER, hotkey_id, lparam)
        ok = bool(result)
        if ok:
            self._registered[hotkey_id] = (modifiers, vk)
        return ok

    def unregister_hotkey(self, hotkey_id: int) -> bool:
        """注销单个热键。"""
        if self.hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        result = user32.SendMessageW(self.hwnd, WM_COPYAMA_UNREGISTER, hotkey_id, 0)
        if result:
            self._registered.pop(hotkey_id, None)
        return bool(result)

    def unregister_all(self) -> None:
        """注销全部热键。"""
        if self.hwnd is None:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        user32.SendMessageW(self.hwnd, WM_COPYAMA_UNREGISTER_ALL, 0, 0)
        self._registered.clear()

    def probe_available(self, modifiers: int, vk: int) -> bool:
        """**真实探测**某热键是否可注册（与实际注册同一线程、同一窗口）。"""
        if self.hwnd is None:
            return False
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        lparam = _makelong(modifiers, vk)
        result = user32.SendMessageW(self.hwnd, WM_COPYAMA_PROBE, 0, lparam)
        return bool(result)

    # —— 热键线程主循环 ——

    def _run(self) -> None:  # pragma: no cover - Windows 专属
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        LRESULT = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.DefWindowProcW.restype = LRESULT
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, ctypes.c_uint
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM
        )

        PROBE_ID = 0xBABE00

        def _proc(hwnd, msg, wparam, lparam):  # noqa: ANN001
            if msg == WM_HOTKEY:
                self._bridge.triggered.emit(int(wparam))
                return 0
            elif msg == WM_COPYAMA_REGISTER:
                hotkey_id = int(wparam)
                modifiers = _loword(lparam)
                vk = _hiword(lparam)
                ok = bool(user32.RegisterHotKey(hwnd, hotkey_id, modifiers, vk))
                return 1 if ok else 0
            elif msg == WM_COPYAMA_UNREGISTER:
                hotkey_id = int(wparam)
                ok = bool(user32.UnregisterHotKey(hwnd, hotkey_id))
                return 1 if ok else 0
            elif msg == WM_COPYAMA_UNREGISTER_ALL:
                for hid in list(self._registered.keys()):
                    user32.UnregisterHotKey(hwnd, hid)
                self._registered.clear()
                return 1
            elif msg == WM_COPYAMA_PROBE:
                modifiers = _loword(lparam)
                vk = _hiword(lparam)
                ok = bool(user32.RegisterHotKey(hwnd, PROBE_ID, modifiers, vk))
                if ok:
                    user32.UnregisterHotKey(hwnd, PROBE_ID)
                return 1 if ok else 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(_proc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))  # 重复注册忽略

        hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, wc.lpszClassName, 0, 0, 0, 0, 0,
            None, None, hinstance, None
        )
        if not hwnd:
            log.error("创建热键隐藏窗口失败")
            self._ready.set()
            return

        self.hwnd = int(hwnd)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # 退出前清理
        for hid in list(self._registered.keys()):
            user32.UnregisterHotKey(self.hwnd, hid)
        self._registered.clear()
        user32.DestroyWindow(self.hwnd)
