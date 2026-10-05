"""pytest 全局配置：无显示器环境下强制 Qt 离屏渲染。"""

from __future__ import annotations

import os

# 必须在任何 Qt 模块导入前设置，否则 CI / 无 DISPLAY 环境会直接崩溃
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
