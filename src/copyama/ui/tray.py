"""系统托盘：图标、菜单与快捷入口。

菜单项：
- 显示剪贴历史（等价于按热键）
- 设置…
- 暂停 / 继续捕获
- 清空历史…（⚠️ 破坏性，需二次确认，默认仅软删）
- 退出

风险约定：清空历史属破坏性操作，``confirm_clear`` 弹出带「彻底删除」勾选框的
确认框；未勾选时只做软删除（进回收站、可恢复），勾选后才物理清除。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QMenu, QMessageBox, QSystemTrayIcon

from copyama.config import Config
from copyama.utils.logger import get_logger

log = get_logger(__name__)

# 指定拖拽力度
CLEAR_SOFT = "soft"
CLEAR_PURGE = "purge"


def clear_mode(hard_delete: bool) -> str:
    """把「是否彻底删除」翻译成后续动作标识（纯逻辑，便于单测）。"""
    return CLEAR_PURGE if hard_delete else CLEAR_SOFT


def _icon_search_paths() -> list[str]:
    """返回图标的搜索路径列表（按优先级排序）。

    支持三种运行方式：
    1. 源码开发：项目根目录/assets/app.ico
    2. PyInstaller 打包：_internal/assets/app.ico
    3. 兜底：和 tray.py 同目录的 assets/app.ico
    """
    import os
    import sys

    paths = []

    # 1) PyInstaller 打包后的资源目录
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS if hasattr(sys, "_MEIPASS") else os.path.dirname(sys.executable)
        paths.append(os.path.join(base, "assets", "app.ico"))
        paths.append(os.path.join(base, "_internal", "assets", "app.ico"))

    # 2) 源码模式：项目根目录/assets/app.ico
    # 向上找包含 src/ 的目录（即项目根）
    try:
        here = os.path.dirname(os.path.abspath(__file__))  # ui/
        src_dir = os.path.dirname(here)  # copyama/
        pkg_dir = os.path.dirname(src_dir)  # src/
        project_root = os.path.dirname(pkg_dir)  # 项目根
        paths.append(os.path.join(project_root, "assets", "app.ico"))
    except Exception:  # noqa: BLE001
        pass

    # 3) 当前工作目录的 assets
    paths.append(os.path.join(os.getcwd(), "assets", "app.ico"))

    return paths


def create_tray_icon() -> QIcon:
    """创建托盘图标：优先从 app.ico 文件加载，和 exe 图标统一。

    找不到文件时退回代码绘制的极简剪贴板图标（白底圆角 + 深色图案）。
    """
    # —— 优先从文件加载 ——
    for path in _icon_search_paths():
        import os
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon

    # —— 兜底：代码绘制（零依赖）——
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 白色圆角底板
    bg_rect = QRect(2, 2, size - 4, size - 4)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawRoundedRect(bg_rect, 12, 12)

    # 剪贴板图案（深灰近黑）
    fg = QColor(45, 45, 45)
    pen = QPen(fg)
    pen.setWidth(4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # 底板（圆角矩形）
    body = QRect(16, 20, 32, 34)
    painter.drawRoundedRect(body, 3, 3)

    # 顶部夹子
    clip_top = QRect(23, 10, 18, 14)
    painter.drawRoundedRect(clip_top, 3, 3)

    # 中间三条横线（代表文字内容）
    painter.setBrush(QBrush(fg))
    painter.setPen(Qt.PenStyle.NoPen)
    line_y = 30
    for i in range(3):
        painter.drawRoundedRect(22, line_y + i * 8, 20, 3, 1.5, 1.5)

    painter.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    """托盘图标与菜单。"""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(create_tray_icon(), parent)
        self._config = config
        self.hard_delete = False
        self.setToolTip("Copyama · 剪贴板管理")
        self._build_menu()

    def _build_menu(self) -> None:
        menu = QMenu()
        self.act_show = QAction("显示剪贴历史", menu)
        self.act_settings = QAction("设置…", menu)
        self.act_pause = QAction("暂停捕获", menu, checkable=True)
        self.act_clear = QAction("清空历史…", menu)
        self.act_quit = QAction("退出", menu)

        menu.addAction(self.act_show)
        menu.addAction(self.act_settings)
        menu.addSeparator()
        menu.addAction(self.act_pause)
        menu.addSeparator()
        menu.addAction(self.act_clear)
        menu.addAction(self.act_quit)
        self.setContextMenu(menu)

    def confirm_clear(self) -> bool:
        """清空历史前的二次确认。

        ⚠️ 风险定级：清空历史属破坏性操作，必须由用户显式确认；
        默认走软删除（可恢复），只有用户在确认框中勾选「彻底删除」才物理清除。
        结果落在 ``self.hard_delete``，并可用 ``clear_mode`` 转成动作标识。
        """
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("清空剪贴历史")
        box.setText("确定要清空全部剪贴历史吗？")
        box.setInformativeText(
            "默认仅移入回收站，可在「回收站」中恢复；\n勾选「彻底删除」后将永久清除，无法恢复。"
        )
        hard = QCheckBox("彻底删除（不可恢复）")
        box.setCheckBox(hard)
        confirm_btn = box.addButton("清空", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(confirm_btn)
        box.exec()

        self.hard_delete = hard.isChecked()
        if box.clickedButton() is confirm_btn:
            log.info("用户确认清空历史（%s）", clear_mode(self.hard_delete))
            return True
        log.debug("用户取消清空历史")
        return False
