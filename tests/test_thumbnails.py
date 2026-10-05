"""缩略图模块单测（Pillow 已安装，走真实解码路径）。"""

from __future__ import annotations

from io import BytesIO

from copyama.data.thumbnails import (
    SUPPORTED_FORMATS,
    ensure,
    estimate_savings,
    generate,
    is_available,
    target_size,
    thumb_path,
)


def png_bytes(width: int, height: int, color=(120, 120, 120)) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def test_target_size_keeps_ratio_and_no_upscale():
    assert target_size(1000, 500, 256) == (256, 128)
    assert target_size(500, 1000, 256) == (128, 256)
    assert target_size(100, 50, 256) == (100, 50), "小图不放大"
    assert target_size(0, 10, 256) == (0, 0)


def test_generate_webp_thumbnail(tmp_path):
    data = png_bytes(1200, 600)
    dest = tmp_path / "t.webp"
    result = generate(data, dest, max_px=256)
    assert result is not None
    assert result.path.exists()
    assert result.width == 256 and result.height == 128
    assert result.bytes_written > 0
    assert result.kb >= 0


def test_thumbnail_is_smaller_than_original(tmp_path):
    data = png_bytes(2000, 2000, (10, 200, 30))
    result = generate(data, tmp_path / "big.webp", max_px=256)
    assert result is not None
    assert result.bytes_written < len(data)
    assert estimate_savings(len(data), result.bytes_written) > 0.5


def test_ensure_hits_cache(tmp_path):
    blob_dir = tmp_path / "blobs"
    data = png_bytes(600, 400)
    first = ensure(blob_dir, "text:abc", data, max_px=256)
    assert first is not None
    mtime = first.path.stat().st_mtime_ns
    second = ensure(blob_dir, "text:abc", data, max_px=256)
    assert second is not None
    assert second.path == first.path
    assert second.path.stat().st_mtime_ns == mtime, "命中缓存不应重新生成"


def test_thumb_path_sanitizes_hash(tmp_path):
    path = thumb_path(tmp_path, "image:dead/beef")
    assert ":" not in path.name and "/" not in path.name
    assert path.suffix == ".webp"


def test_bad_bytes_return_none(tmp_path):
    assert generate(b"not an image", tmp_path / "x.webp") is None


def test_format_guards():
    assert is_available() is True
    assert "webp" in SUPPORTED_FORMATS
