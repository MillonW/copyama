"""持久化：存储、缩略图、blob 管理。"""

from copyama.data.storage import Storage, now_ms
from copyama.data.thumbnails import generate, thumb_path

__all__ = ["Storage", "now_ms", "generate", "thumb_path"]
