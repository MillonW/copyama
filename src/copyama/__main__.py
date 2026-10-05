"""应用入口：``python -m copyama`` 或安装后的 ``copyama`` 命令。"""

from __future__ import annotations

import sys


def main() -> int:
    """启动 Copyama，返回进程退出码。"""
    # 延迟导入：避免仅执行 --version 等轻量操作时加载 GUI 依赖。
    from copyama.app import CopyamaApp

    return CopyamaApp().run()


if __name__ == "__main__":
    sys.exit(main())
