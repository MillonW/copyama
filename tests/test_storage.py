"""存储层单测（纯 SQLite，可跨平台运行）。"""

from __future__ import annotations

import json

from copyama.core.models import Clip, ClipType
from copyama.data.storage import Storage, content_hash


def make(tmp_path, max_items: int = 100) -> Storage:
    return Storage(db_path=tmp_path / "copyama.db", max_items=max_items)


def test_content_hash_stable():
    assert content_hash(ClipType.TEXT, "abc") == content_hash(ClipType.TEXT, "abc")
    assert content_hash(ClipType.TEXT, "abc") != content_hash(ClipType.TEXT, "abd")


def test_add_and_dedupe_refreshes_instead_of_inserting(tmp_path):
    s = make(tmp_path)
    first = s.add(Clip(type=ClipType.TEXT, content="hello"))
    second = s.add(Clip(type=ClipType.TEXT, content="hello"))
    assert first.id == second.id
    assert s.count() == 1


def test_recent_orders_pinned_first(tmp_path):
    s = make(tmp_path)
    old = s.add(Clip(type=ClipType.TEXT, content="旧的"))
    s.add(Clip(type=ClipType.TEXT, content="新的"))
    s.set_pinned(old.id, True)
    assert s.recent()[0].content == "旧的"


def test_search_by_keyword(tmp_path):
    s = make(tmp_path)
    s.add(Clip(type=ClipType.TEXT, content="发票 2024 年 3 月"))
    s.add(Clip(type=ClipType.TEXT, content="会议纪要"))
    assert len(s.search("发票")) == 1
    assert len(s.search("")) == 2
    assert len(s.search("不存在的关键词")) == 0


def test_search_filter_by_kind(tmp_path):
    s = make(tmp_path)
    s.add(Clip(type=ClipType.FILE, content=json.dumps(["a.png"]), kind="image"))
    s.add(Clip(type=ClipType.FILE, content=json.dumps(["b.zip"]), kind="archive"))
    assert len(s.search(kinds=["image"])) == 1
    assert len(s.search(kinds=["image", "archive"])) == 2


def test_soft_delete_then_purge(tmp_path):
    s = make(tmp_path)
    c = s.add(Clip(type=ClipType.TEXT, content="删除我"))
    assert s.delete([c.id]) == 1
    assert s.count() == 0
    assert s.count(include_deleted=True) == 1
    # 软删后重新复制同一内容会复活原记录
    revived = s.add(Clip(type=ClipType.TEXT, content="删除我"))
    assert revived.id == c.id
    assert s.count() == 1


def test_hard_delete(tmp_path):
    s = make(tmp_path)
    c = s.add(Clip(type=ClipType.TEXT, content="彻底删除"))
    s.delete([c.id], hard=True)
    assert s.count(include_deleted=True) == 0


def test_evict_keeps_newest_and_pinned(tmp_path):
    s = make(tmp_path, max_items=3)
    pinned = s.add(Clip(type=ClipType.TEXT, content="固定的"))
    s.set_pinned(pinned.id, True)
    for i in range(5):
        s.add(Clip(type=ClipType.TEXT, content=f"t{i}"))
    assert s.count() == 3
    assert s.get(pinned.id) is not None, "固定项不应被淘汰"


def test_export_formats(tmp_path):
    s = make(tmp_path)
    c = s.add(Clip(type=ClipType.TEXT, content="导出内容"))
    txt = s.export([c.id], fmt="txt", dest=tmp_path / "o.txt")
    md = s.export([c.id], fmt="md", dest=tmp_path / "o.md")
    js = s.export([c.id], fmt="json", dest=tmp_path / "o.json")
    for path in (txt, md, js):
        assert path.exists()
        assert "导出内容" in path.read_text(encoding="utf-8")


def test_clip_file_paths_helper():
    clip = Clip(type=ClipType.FILE, content=json.dumps([r"C:\a.png", r"C:\b.zip"]))
    assert clip.file_paths == [r"C:\a.png", r"C:\b.zip"]
    assert Clip(type=ClipType.TEXT, content="hi").file_paths == []
    assert Clip(type=ClipType.FILE, content="坏数据").file_paths == []
