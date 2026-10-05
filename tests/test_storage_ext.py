"""存储层扩展能力单测：分页、去重、七天过期、超限淘汰、原图/缩略图、配额、孤儿清理。"""

from __future__ import annotations

from io import BytesIO

import pytest

from copyama.core.models import Clip, ClipType
from copyama.core.retention import DAY_MS, RetentionPolicy
from copyama.data.storage import Storage, content_hash


@pytest.fixture()
def store(tmp_path) -> Storage:
    return Storage(tmp_path / "copyama.db", max_items=200, max_age_days=7)


def png(w: int = 64, h: int = 64, color=(10, 20, 30)) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def backdate(store: Storage, clip_id: int, days: float) -> None:
    """把记录时间改成 N 天前（模拟历史数据）。"""
    store._conn.execute(
        "UPDATE clips SET created_at = created_at - ? WHERE id = ?",
        (int(days * DAY_MS), clip_id),
    )
    store._conn.commit()


# —— 默认值与策略 ——
def test_default_is_200_items_and_7_days(store):
    assert store.max_items == 200
    assert store.max_age_days == 7
    policy = store.policy
    assert policy.max_items == 200 and policy.max_age_days == 7
    store.set_policy(max_items=50, max_age_days=3)
    assert store.policy.max_items == 50 and store.policy.max_age_days == 3


# —— 去重：反复 Ctrl+C 只留一条 ——
def test_repeated_copy_keeps_single_row(store):
    for _ in range(5):
        store.store_text("重复内容")
    assert store.count() == 1
    first = store.recent()[0]
    store.store_text("重复内容")
    refreshed = store.recent()[0]
    assert refreshed.id == first.id, "重复复制只置顶，不新增行"
    assert refreshed.created_at >= first.created_at


def test_different_content_creates_new_rows(store):
    store.store_text("a")
    store.store_text("b")
    assert store.count() == 2


# —— 分页 ——
def test_pagination_offset_walk(store):
    for i in range(25):
        store.store_text(f"text-{i}")
    page1 = store.page(0, 10)
    page2 = store.page(10, 10)
    page3 = store.page(20, 10)
    assert [len(p) for p in (page1, page2, page3)] == [10, 10, 5]
    assert store.count_filtered() == 25
    ids = [c.id for c in page1 + page2 + page3]
    assert len(set(ids)) == 25, "分页不应重复"


def test_keyset_pagination_matches_offset(store):
    for i in range(15):
        store.store_text(f"k-{i}")
    offset_ids = [c.id for c in store.page(0, 6) + store.page(6, 6)]
    first = store.page_after(None, 6)
    second = store.page_after(store.cursor_of(first[-1]), 6)
    assert [c.id for c in first + second] == offset_ids


def test_keyset_pagination_survives_same_millisecond(store):
    """快速连续复制（同一毫秒多条）时，键集游标不得漏记录。"""
    for i in range(9):
        store.store_text(f"same-{i}")
    with store._lock:  # noqa: SLF001 - 测试内直接对齐时间戳
        store._conn.execute("UPDATE clips SET created_at = 1700000000000")
        store._conn.commit()
    pages = []
    cursor = None
    while True:
        rows = store.page_after(cursor, 4)
        if not rows:
            break
        pages.extend(rows)
        cursor = store.cursor_of(rows[-1])
    ids = [c.id for c in pages]
    assert len(ids) == 9, ids
    assert len(set(ids)) == 9, "同毫秒下出现了重复或遗漏"


def test_search_and_kind_filter(store):
    store.store_text("项目周报：本周完成 A 模块")
    store.store_text("购物清单：牛奶 鸡蛋")
    store.store_files([r"C:\a\report.pdf"], kind="document")
    assert len(store.search("周报")) == 1
    assert store.count_filtered("周报") == 1
    assert len(store.search(kinds=["document"])) == 1
    assert store.count_filtered(keyword="清单", kinds=["document"]) == 0


# —— 清理 ——
def test_seven_day_expiry(store):
    old = store.store_text("七天前的旧内容")
    fresh = store.store_text("刚复制的内容")
    backdate(store, old.id, 7.5)
    result = store.run_cleanup()
    assert result["expired"] == 1
    ids = [c.id for c in store.recent()]
    assert old.id not in ids and fresh.id in ids


def test_age_limit_zero_keeps_everything(store):
    old = store.store_text("很久以前")
    backdate(store, old.id, 365)
    store.set_policy(max_age_days=0)
    assert store.run_cleanup()["expired"] == 0
    assert store.count() == 1


def test_overflow_evicts_oldest(store):
    store.set_policy(max_items=5)
    ids = [store.store_text(f"n-{i}").id for i in range(10)]
    assert store.count() == 5
    remaining = {c.id for c in store.recent(limit=99)}
    assert ids[0] not in remaining and ids[-1] in remaining


def test_pinned_survives_cleanup_and_expiry(store):
    pinned = store.store_text("重要内容")
    store.set_pinned(pinned.id, True)
    backdate(store, pinned.id, 30)
    for i in range(8):
        store.store_text(f"x-{i}")
    store.set_policy(max_items=3)
    store.run_cleanup()
    assert store.get(pinned.id) is not None
    assert not store.get(pinned.id).deleted


# —— 删除与回收站 ——
def test_soft_delete_then_restore(store):
    clip = store.store_text("待删除")
    assert store.delete([clip.id]) == 1
    assert store.count() == 0
    assert len(store.recycle_bin()) == 1
    store.restore([clip.id])
    assert store.count() == 1


def test_purge_deleted_clears_recycle_bin(store):
    for i in range(3):
        c = store.store_text(f"d-{i}")
        store.delete([c.id])
    assert store.purge_deleted() == 3
    assert store.count(include_deleted=True) == 0


# —— 图片：原图 + 缩略图 ——
def test_image_stores_original_and_thumbnail(store):
    data = png(800, 400)
    clip = store.store_image(data)
    assert clip.blob_hash and clip.blob_hash.startswith("img_")
    assert store.blob_path(clip.blob_hash).read_bytes() == data, "原图必须完整落盘"
    thumb = store.thumb_file(clip)
    assert thumb is not None and thumb.exists()
    assert clip.preview == thumb.name
    assert clip.size_bytes == len(data)
    assert store.image_bytes(clip) == data


def test_image_dedup_reuses_blob(store):
    data = png()
    a = store.store_image(data)
    b = store.store_image(data)
    assert a.id == b.id, "同一张图重复复制只留一条"
    assert len(list(store.blob_dir.glob("img_*"))) == 1


def test_hard_delete_removes_blob_and_thumb(store):
    clip = store.store_image(png())
    blob = store.blob_path(clip.blob_hash)
    thumb = store.thumb_file(clip)
    store.delete([clip.id], hard=True)
    assert not blob.exists() and not thumb.exists()


def test_sweep_orphans_removes_unreferenced(store):
    clip = store.store_image(png())
    keep = store.blob_path(clip.blob_hash)
    orphan = store.blob_dir / "orphan_img.jpg"
    orphan.write_bytes(b"junk")
    orphan_thumb = store.thumb_path("img_ghost")
    orphan_thumb.parent.mkdir(parents=True, exist_ok=True)
    orphan_thumb.write_bytes(b"junk")
    removed = store.sweep_orphans()
    assert removed == 2
    assert keep.exists() and not orphan.exists() and not orphan_thumb.exists()


def test_blob_quota_evicts_oldest_image(store):
    a = store.store_image(png(64, 64, (1, 2, 3)))
    b = store.store_image(png(64, 64, (4, 5, 6)))
    total = a.size_bytes + b.size_bytes
    quota_mb = (total * 0.6) / (1024 * 1024)  # 只够存一张
    removed = store.enforce_blob_quota(quota_mb)
    assert removed == 1
    assert store.get(a.id) is None, "最旧的图片先被清理"
    assert store.get(b.id) is not None
    assert store.blob_quota_mb is not None


def test_quota_zero_means_unlimited(store):
    store.store_image(png())
    assert store.enforce_blob_quota(0) == 0


# —— 统计与维护 ——
def test_disk_usage_reports_breakdown(store):
    store.store_image(png(200, 200))
    store.store_text("some text")
    usage = store.disk_usage()
    assert usage["total_bytes"] > 0
    assert usage["blob_bytes"] > 0 and usage["thumb_bytes"] > 0
    assert usage["db_bytes"] > 0
    assert usage["thumb_count"] >= 1


def test_vacuum_returns_size(store):
    for i in range(20):
        store.store_text(f"v-{i}")
    store.purge([c.id for c in store.recent(limit=20)])
    assert store.vacuum() > 0


def test_content_hash_stable():
    assert content_hash(ClipType.TEXT, "x") == content_hash(ClipType.TEXT, "x")
    assert content_hash(ClipType.TEXT, "x") != content_hash(ClipType.IMAGE, "x")
