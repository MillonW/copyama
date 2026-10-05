"""统一日志配置。

日志写入 ``%APPDATA%\\Copyama\\logs\\copyama.log``，滚动保留 3 份、单份 1 MB，
避免日志本身成为磁盘负担。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from copyama.config import default_data_dir

_LOGGER_NAME = "copyama"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化日志（幂等，重复调用无副作用）。"""
    global _configured
    if _configured:
        return

    log_dir = default_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "copyama.log",
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带命名空间的 logger。"""
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
