"""日期折叠分组单测。"""

from __future__ import annotations

from datetime import datetime

from copyama.core.grouping import (
    DAY_MS,
    DateBucket,
    bucket_of,
    day_key,
    day_label,
    expires_at,
    group_by_bucket,
    group_by_day,
    humanize_age,
    humanize_expiry,
    next_day_boundary,
)
from copyama.core.models import Clip, ClipType

NOW = int(datetime(2026, 10, 3, 12, 0).timestamp() * 1000)


def clip(cid: int, offset_ms: int = 0) -> Clip:
    return Clip(type=ClipType.TEXT, content=f"c{cid}", id=cid, created_at=NOW - offset_ms)


def test_day_key_and_bucket():
    assert bucket_of(NOW - 3_600_000, NOW) is DateBucket.TODAY
    assert bucket_of(NOW - DAY_MS, NOW) is DateBucket.YESTERDAY
    assert bucket_of(NOW - 3 * DAY_MS, NOW) is DateBucket.THIS_WEEK
    assert bucket_of(NOW - 30 * DAY_MS, NOW) is DateBucket.EARLIER


def test_day_labels():
    assert day_label(NOW, NOW) == "今天"
    assert day_label(NOW - DAY_MS, NOW) == "昨天"
    assert day_label(NOW - 3 * DAY_MS, NOW).startswith("9月30日")
    assert day_key(NOW) == "2026-10-03"


def test_group_by_day_orders_desc_and_counts():
    clips = [
        clip(1, 0),
        clip(2, 2 * 3_600_000),
        clip(3, DAY_MS),
        clip(4, 5 * DAY_MS),
    ]
    groups = group_by_day(clips, NOW)
    assert [g.label for g in groups] == ["今天", "昨天", "9月28日 周一"]
    assert groups[0].count == 2
    assert [c.id for c in groups[0].clips] == [1, 2], "组内应时间倒序"
    assert groups[0].key == "2026-10-03"


def test_group_by_bucket_skips_empty():
    clips = [clip(1, 0), clip(2, 10 * DAY_MS)]
    pairs = group_by_bucket(clips, NOW)
    assert [b for b, _ in pairs] == [DateBucket.TODAY, DateBucket.EARLIER]


def test_empty_input():
    assert group_by_day([], NOW) == []
    assert group_by_bucket([], NOW) == []


def test_humanize_age():
    assert humanize_age(NOW - 10_000, NOW) == "刚刚"
    assert humanize_age(NOW - 5 * 60_000, NOW) == "5 分钟前"
    assert humanize_age(NOW - 3 * 3_600_000, NOW) == "3 小时前"
    assert humanize_age(NOW - 2 * DAY_MS, NOW) == "2 天前"


def test_expiry_helpers():
    fresh = clip(1, 1 * DAY_MS)
    old_pinned = Clip(type=ClipType.TEXT, content="p", id=9, created_at=NOW - 100 * DAY_MS, pinned=True)
    assert expires_at(fresh, 7) == fresh.created_at + 7 * DAY_MS
    assert expires_at(old_pinned, 7) is None, "固定条目不过期"
    assert expires_at(fresh, 0) is None
    assert humanize_expiry(fresh, NOW, 7).endswith("天后清理")
    assert humanize_expiry(fresh, NOW, 0) == "长期保留"
    assert humanize_expiry(clip(2, 9 * DAY_MS), NOW, 7) == "即将清理"


def test_next_day_boundary():
    assert next_day_boundary(NOW) - NOW <= DAY_MS
    assert next_day_boundary(NOW) > NOW
