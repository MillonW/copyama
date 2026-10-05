"""全局热键：字符串解析、合法性校验、冲突检测与注册。

实现：Win32 ``RegisterHotKey`` + ``WM_HOTKEY``。
其中「解析 / 规范化 / 冲突检测」为纯逻辑，可跨平台单测；只有 ``register`` 依赖 Win32。
"""

from __future__ import annotations

import sys

from copyama.utils.logger import get_logger

log = get_logger(__name__)

# 修饰键位（对应 Win32 MOD_* 常量）
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# 规范修饰键顺序（展示与比较都用它）
_ORDER = ("ctrl", "alt", "shift", "win")
_MOD_CANON = {
    "ctrl": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}
_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "win": "win", "super": "win", "cmd": "win", "meta": "win",
}
_DISPLAY = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

# 键名 → 虚拟键码（纯逻辑部分只做识别与展示，注册时再交给平台层）
_VK_LETTERS = {chr(c): c for c in range(ord("A"), ord("Z") + 1)}
_VK_DIGITS = {str(d): 0x30 + d for d in range(10)}
_VK_FKEYS = {f"F{i}": 0x6F + i for i in range(1, 25)}
_VK_SPECIAL = {
    "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D, "TAB": 0x09,
    "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08, "DELETE": 0x2E,
    "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21,
    "PAGEDOWN": 0x22, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27,
    "DOWN": 0x28, "`": 0xC0, "-": 0xBD, "=": 0xBB,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
VK_MAP: dict[str, int] = {**_VK_LETTERS, **_VK_DIGITS, **_VK_FKEYS, **_VK_SPECIAL}

# 系统 / 常见软件已占用的热键，用于给出可读的冲突提示
RESERVED: dict[str, str] = {
    "ctrl+alt+delete": "Windows 安全注意序列，系统保留，无法注册",
    "ctrl+shift+esc": "任务管理器",
    "win+l": "锁屏",
    "win+d": "显示桌面",
    "win+e": "打开资源管理器",
    "win+r": "运行",
    "alt+f4": "关闭当前窗口",
    "alt+tab": "切换窗口",
    "ctrl+alt+a": "微信 / QQ 截图",
    "ctrl+alt+s": "QQ 截图（旧版）或录屏工具",
    "ctrl+alt+v": "部分录屏 / 编辑器工具，可能重复",
    "ctrl+alt+z": "部分输入法",
    "ctrl+shift+v": "浏览器「无格式粘贴」",
    "ctrl+shift+a": "截图 / 输入法",
    "ctrl+shift+s": "浏览器「另存为」",
    "ctrl+shift+x": "部分编辑器插件",
}


def parse_hotkey(spec: str) -> tuple[int, str]:
    """把 ``"Ctrl+Alt+V"`` 解析为 ``(modifiers, key)``。key 为大写字符串。"""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("热键至少需要「修饰键 + 主键」，例如 Ctrl+Alt+V")
    *mods, key = parts
    modifiers = 0
    seen: set[str] = set()
    for mod in mods:
        canon = _MOD_ALIASES.get(mod.casefold())
        if canon is None:
            raise ValueError(f"未知修饰键：{mod}")
        if canon in seen:
            raise ValueError(f"修饰键重复：{mod}")
        seen.add(canon)
        modifiers |= _MOD_CANON[canon]
    return modifiers, key.upper()


def normalize(spec: str) -> str:
    """规范化热键写法：修饰键按 Ctrl+Alt+Shift+Win 排序，主键大写。"""
    modifiers, key = parse_hotkey(spec)
    names = [_DISPLAY[n] for n in _ORDER if modifiers & _MOD_CANON[n]]
    return "+".join([*names, key])


def validate(spec: str) -> list[str]:
    """校验热键可用性，返回问题列表（空列表表示可用）。"""
    problems: list[str] = []
    try:
        modifiers, key = parse_hotkey(spec)
    except ValueError as exc:
        return [str(exc)]

    if key not in VK_MAP:
        problems.append(f"无法识别的按键：{key}")
    if not modifiers:
        problems.append("至少需要一个修饰键（否则会拦截普通输入）")
    if modifiers == MOD_WIN:
        problems.append("仅 Win 修饰易与系统快捷键冲突，建议叠加 Ctrl 或 Alt")
    problems.extend(check_conflict(spec))
    return problems


def check_conflict(spec: str) -> list[str]:
    """检测与系统 / 常见软件已占用热键的冲突，返回可读提示。"""
    try:
        key = normalize(spec).casefold()
    except ValueError:
        return []
    hit = RESERVED.get(key)
    return [f"与「{hit}」冲突，建议更换"] if hit else []


def conflicts_with(a: str, b: str) -> bool:
    """判断两个热键是否等价（忽略大小写与修饰键顺序）。"""
    try:
        return normalize(a).casefold() == normalize(b).casefold()
    except ValueError:
        return False


# —— 真实占用探测（基于 RegisterHotKey 试注册）——

_PROBE_ID_BASE = 0xBABE00  # 探测用的临时热键 ID 区间


def probe_available(spec: str) -> bool:
    """**实时探测**热键是否真的未被占用。

    通过 ``RegisterHotKey`` 试注册再立刻注销来判断。
    比静态 ``check_conflict`` 更准——能测出任意程序实际占用的组合，
    但仅限 Windows 且有微小的系统调用开销（输入防抖后可忽略）。

    返回 True 表示当前可注册（没被占用），False 表示已被占用或格式非法。
    """
    if sys.platform != "win32":
        # 非 Windows 平台退化为静态冲突检测
        return not check_conflict(spec)
    try:
        modifiers, key = parse_hotkey(spec)
    except ValueError:
        return False
    vk = VK_MAP.get(key)
    if vk is None or not modifiers:
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    # 明确签名
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.UINT, ctypes.c_uint
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL

    # hwnd 传 NULL：热键关联到当前线程，这是最通用的探测方式
    probe_id = _PROBE_ID_BASE
    ok = bool(user32.RegisterHotKey(None, probe_id, modifiers, vk))
    if ok:
        user32.UnregisterHotKey(None, probe_id)
    return ok


# 推荐候选池：优先常见的唤起组合，按「离手近 → 远」排序
_RECOMMEND_POOL: tuple[str, ...] = (
    # Ctrl+Alt + 字母（最常见的工具唤起组合）
    "Ctrl+Alt+C", "Ctrl+Alt+V", "Ctrl+Alt+X", "Ctrl+Alt+Z",
    "Ctrl+Alt+A", "Ctrl+Alt+S", "Ctrl+Alt+D", "Ctrl+Alt+F",
    "Ctrl+Alt+Q", "Ctrl+Alt+W", "Ctrl+Alt+E", "Ctrl+Alt+R",
    "Ctrl+Alt+B", "Ctrl+Alt+N", "Ctrl+Alt+M",
    # Ctrl+Shift + 字母
    "Ctrl+Shift+C", "Ctrl+Shift+V", "Ctrl+Shift+A",
    "Ctrl+Shift+S", "Ctrl+Shift+F", "Ctrl+Shift+Z",
    # Win + 字母（不推荐但作为兜底）
    "Win+C", "Win+V", "Win+A", "Win+S",
    # Alt + 功能键
    "Alt+F1", "Alt+F2", "Alt+F3", "Ctrl+F1", "Ctrl+F2",
)


def suggest_hotkey(exclude: set[str] | None = None) -> str | None:
    """从候选池中找一个**实际未被占用**的热键并返回。

    ``exclude`` 可选：跳过这些已被自己占用的组合（比如已注册的当前热键）。
    找不到返回 None。
    """
    skip = set()
    if exclude:
        for s in exclude:
            try:
                skip.add(normalize(s).casefold())
            except ValueError:
                pass
    for spec in _RECOMMEND_POOL:
        try:
            canon = normalize(spec).casefold()
        except ValueError:
            continue
        if canon in skip:
            continue
        # 先快速过一遍静态黑名单，再真实探测（省系统调用）
        if check_conflict(spec):
            continue
        if probe_available(spec):
            return spec
    return None


class HotkeyManager:
    """注册 / 注销全局热键（Win32 RegisterHotKey）。"""

    def __init__(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self._registered: dict[int, str] = {}

    def register(self, hotkey_id: int, spec: str) -> bool:
        """注册热键；返回是否成功。

        失败最常见原因是热键被其它程序占用，此时应托盘提示并引导用户到
        设置界面换一个未冲突的组合（见 validate / check_conflict）。
        """
        problems = validate(spec)
        hard_errors = [p for p in problems if "无法识别" in p or "至少" in p]
        if hard_errors:
            log.warning("热键 %s 校验未通过：%s", spec, hard_errors)
            return False
        if sys.platform != "win32":
            log.warning("全局热键仅支持 Windows，当前平台 %s 无法注册 %s", sys.platform, spec)
            return False

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, ctypes.c_uint
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL

        modifiers, key = parse_hotkey(spec)
        vk = VK_MAP.get(key)
        if vk is None:
            log.warning("无法识别的按键：%s", key)
            return False
        if not ctypes.windll.user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, vk):
            log.warning("注册热键 %s 失败：可能已被其它程序占用", spec)
            return False
        self._registered[hotkey_id] = normalize(spec)
        log.info("已注册热键 %s（id=%d）", normalize(spec), hotkey_id)
        return True

    def unregister_all(self) -> None:
        """退出时注销全部热键。"""
        if not self._registered:
            return
        if sys.platform != "win32":
            self._registered.clear()
            return
        import ctypes

        for hotkey_id in list(self._registered):
            ctypes.windll.user32.UnregisterHotKey(self._hwnd, hotkey_id)
        log.info("已注销 %d 个热键", len(self._registered))
        self._registered.clear()

    def unregister(self, hotkey_id: int) -> bool:
        """注销单个热键；返回是否成功。"""
        if hotkey_id not in self._registered:
            return False
        if sys.platform != "win32":
            self._registered.pop(hotkey_id, None)
            return True
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL

        ok = bool(user32.UnregisterHotKey(self._hwnd, hotkey_id))
        if ok:
            spec = self._registered.pop(hotkey_id, "")
            log.debug("已注销热键 %s（id=%d）", spec, hotkey_id)
        return ok

    @property
    def registered(self) -> dict[int, str]:
        return dict(self._registered)
