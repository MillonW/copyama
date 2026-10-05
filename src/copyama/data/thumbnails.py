"""缩略图生成与缓存：原图落盘，展示用缩略图。

对应需求「图片存原图，展示时用缩略图」与「注意性能、大小、占用空间」：
- 原图：``blobs/<content_hash>``；
- 缩略图：``blobs/thumb/<content_hash>.webp``，最长边默认 256px；
- webp 体积通常只有 png 的 1/5～1/10，列表里只加载缩略图，内存友好；
- Pillow 缺失或解码失败时返回 None，UI 用占位图标，绝不阻断主流程。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from copyama.utils.logger import get_logger

log = get_logger(__name__)

THUMB_MAX_PX = 256
THUMB_QUALITY = 80
THUMB_FORMAT = "webp"
SUPPORTED_FORMATS = ("webp", "jpeg", "png")


@dataclass(frozen=True)
class ThumbResult:
    """缩略图生成结果。"""

    path: Path
    width: int
    height: int
    bytes_written: int

    @property
    def kb(self) -> float:
        """缩略图体积（KB），用于设置界面展示占用。"""
        return round(self.bytes_written / 1024, 1)


def is_available() -> bool:
    """Pillow 是否可用（可用才走缩略图路径，否则回退占位图）。"""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def target_size(width: int, height: int, max_px: int = THUMB_MAX_PX) -> tuple[int, int]:
    """等比缩放到最长边不超过 ``max_px``；小图不放大。"""
    if width <= 0 or height <= 0:
        return (0, 0)
    longest = max(width, height)
    if longest <= max_px:
        return (width, height)
    scale = max_px / longest
    return (max(1, round(width * scale)), max(1, round(height * scale)))


def thumb_dir(blob_dir: Path) -> Path:
    """缩略图目录（与 blob 同根，便于整体清理）。"""
    path = Path(blob_dir) / "thumb"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumb_path(blob_dir: Path, content_hash: str, fmt: str = THUMB_FORMAT) -> Path:
    """缩略图路径。content_hash 里的 ':' 替换为 '_' 以适配文件名。"""
    safe = content_hash.replace(":", "_").replace("/", "_")
    suffix = "jpg" if fmt == "jpeg" else fmt
    return thumb_dir(blob_dir) / f"{safe}.{suffix}"


def _prepare_mode(img, fmt: str):
    """保证像素模式与目标格式兼容。"""
    if fmt in ("jpeg", "jpg"):
        return img.convert("RGB")
    if img.mode in ("RGB", "RGBA"):
        return img
    return img.convert("RGBA")


def generate(
    data: bytes,
    dest: Path,
    *,
    max_px: int = THUMB_MAX_PX,
    fmt: str = THUMB_FORMAT,
    quality: int = THUMB_QUALITY,
) -> ThumbResult | None:
    """由图片字节流生成缩略图；任何失败都返回 None（不抛异常）。"""
    if fmt not in SUPPORTED_FORMATS:
        log.warning("不支持的缩略图格式：%s", fmt)
        return None
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - 依赖缺失时的降级路径
        log.warning("未安装 Pillow，跳过缩略图生成")
        return None

    try:
        with Image.open(BytesIO(data)) as img:
            size = target_size(img.width, img.height, max_px)
            prepared = _prepare_mode(img, fmt)
            resized = prepared.resize(size, Image.Resampling.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            save_kwargs: dict[str, object] = {}
            if fmt != "png":
                save_kwargs.update(quality=quality, method=4)
            resized.save(dest, fmt.upper() if fmt != "jpeg" else "JPEG", **save_kwargs)
    except Exception as exc:  # noqa: BLE001 - 图片千奇百怪，统一降级
        log.debug("缩略图生成失败：%s", exc)
        return None

    if not dest.exists():
        return None
    return ThumbResult(
        path=dest,
        width=size[0],
        height=size[1],
        bytes_written=dest.stat().st_size,
    )


def ensure(
    blob_dir: Path,
    content_hash: str,
    data: bytes,
    *,
    max_px: int = THUMB_MAX_PX,
    fmt: str = THUMB_FORMAT,
    force: bool = False,
) -> ThumbResult | None:
    """确保缩略图存在（命中缓存则直接返回，不重复解码）。"""
    dest = thumb_path(blob_dir, content_hash, fmt)
    if not force and dest.exists():
        return ThumbResult(
            path=dest,
            width=max_px,
            height=max_px,
            bytes_written=dest.stat().st_size,
        )
    return generate(data, dest, max_px=max_px, fmt=fmt)


def estimate_savings(original_bytes: int, thumb_bytes: int) -> float:
    """返回体积节省比例（0~1），用于「占用空间」提示。"""
    if original_bytes <= 0:
        return 0.0
    return max(0.0, 1 - thumb_bytes / original_bytes)
