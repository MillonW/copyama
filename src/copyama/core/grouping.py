"""按日期折叠分组。

对应需求「按日期折叠」：历史列表按自然日分组，组头可折叠。
纯逻辑，不依赖 Qt，可单测。
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from copyama.core.models import Clip

DAY_MS = 86_400_000
WEEKDAY_CN = "一二三四五六日"


class DateBucket(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    EARLIER = "earlier"


BUCKET_LABELS: dict[DateBucket, str] = {
    DateBucket.TODAY: "今天",
    DateBucket.YESTERDAY: "昨天",
    DateBucket.THIS_WEEK: "本周内",
    DateBucket.EARLIER: "更早",
}


@dataclass(frozen=True)
class DayGroup:
    """一天的分组。"""

    key: str          # YYYY-MM-DD
    label: str        # 展示用：今天 / 昨天 / 10月01日 周三
    clips: tuple[Clip, ...]

    @property
    def count(self) -> int:
        return len(self.clips)


def _dt(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000)


def day_key(ts_ms: int) -> str:
    """时间戳 → 本地自然日 key（YYYY-MM-DD）。"""
    return _dt(ts_ms).strftime("%Y-%m-%d")


def start_of_day(ts_ms: int) -> int:
    """当日零点（毫秒）。"""
    d = _dt(ts_ms)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def day_label(ts_ms: int, now_ms: int) -> str:
    """分组标签：今天 / 昨天 / 10月01日 周三 / 2025年12月31日。"""
    today = day_key(now_ms)
    key = day_key(ts_ms)
    if key == today:
        return "今天"
    if key == day_key(now_ms - DAY_MS):
        return "昨天"
    d = _dt(ts_ms)
    delta_days = (start_of_day(now_ms) - start_of_day(ts_ms)) // DAY_MS
    if delta_days < 7:
        return f"{d.month}月{d.day}日 周{WEEKDAY_CN[d.weekday()]}"
    if d.year == _dt(now_ms).year:
        return f"{d.month}月{d.day}日"
    return f"{d.year}年{d.month}月{d.day}日"


def bucket_of(ts_ms: int, now_ms: int) -> DateBucket:
    """粗粒度分桶（今天 / 昨天 / 本周内 / 更早）。"""
    today = day_key(now_ms)
    if day_key(ts_ms) == today:
        return DateBucket.TODAY
    if day_key(ts_ms) == day_key(now_ms - DAY_MS):
        return DateBucket.YESTERDAY
    if (start_of_day(now_ms) - start_of_day(ts_ms)) // DAY_MS < 7:
        return DateBucket.THIS_WEEK
    return DateBucket.EARLIER


def group_by_day(clips: Iterable[Clip], now_ms: int) -> list[DayGroup]:
    """按自然日分组，组间按日期倒序，组内按时间倒序。

    固定条目不再单独置顶到全列表，而是留在其所属日期里
    （分组语义下跨组置顶会破坏「按日期」的一致性，UI 用星标区分）。
    """
    buckets: OrderedDict[str, list[Clip]] = OrderedDict()
    for clip in clips:
        buckets.setdefault(day_key(clip.created_at), []).append(clip)

    groups: list[DayGroup] = []
    for key in sorted(buckets, reverse=True):
        items = sorted(buckets[key], key=lambda c: (c.created_at, c.id or 0), reverse=True)
        groups.append(
            DayGroup(key=key, label=day_label(items[0].created_at, now_ms), clips=tuple(items))
        )
    return groups


def group_by_bucket(clips: Iterable[Clip], now_ms: int) -> list[tuple[DateBucket, list[Clip]]]:
    """粗粒度分组（备用视图：今天 / 昨天 / 本周内 / 更早）。"""
    order = [DateBucket.TODAY, DateBucket.YESTERDAY, DateBucket.THIS_WEEK, DateBucket.EARLIER]
    table: dict[DateBucket, list[Clip]] = {b: [] for b in order}
    for clip in clips:
        table[bucket_of(clip.created_at, now_ms)].append(clip)
    for items in table.values():
        items.sort(key=lambda c: (c.created_at, c.id or 0), reverse=True)
    return [(b, table[b]) for b in order if table[b]]


def groups(clips: Iterable[Clip], now_ms: int, mode: str = "day") -> list[DayGroup]:
    """统一入口：mode=day 按自然日，mode=bucket 按粗粒度桶（key 用桶名）。"""
    if mode == "bucket":
        return [
            DayGroup(key=b.value, label=BUCKET_LABELS[b], clips=tuple(items))
            for b, items in group_by_bucket(clips, now_ms)
        ]
    return group_by_day(clips, now_ms)


def next_day_boundary(ts_ms: int) -> int:
    """下一个自然日零点（供「今天」分组的滚动刷新判断）。"""
    return start_of_day(ts_ms) + DAY_MS


def humanize_age(ts_ms: int, now_ms: int) -> str:
    """相对时间文案：刚刚 / N 分钟前 / N 小时前 / N 天前。"""
    delta = max(0, now_ms - ts_ms)
    if delta < 60_000:
        return "刚刚"
    if delta < 3_600_000:
        return f"{delta // 60_000} 分钟前"
    if delta < DAY_MS:
        return f"{delta // 3_600_000} 小时前"
    return f"{delta // DAY_MS} 天前"


def expires_at(clip: Clip, max_age_days: int) -> int | None:
    """记录到期时间；max_age_days<=0 时返回 None（永不过期）。"""
    if max_age_days <= 0 or clip.pinned:
        return None
    return clip.created_at + max_age_days * DAY_MS


def humanize_expiry(clip: Clip, now_ms: int, max_age_days: int) -> str:
    """剩余保留时间文案，如「3 天后清理」；已到期返回「即将清理」。"""
    deadline = expires_at(clip, max_age_days)
    if deadline is None:
        return "长期保留"
    remain = deadline - now_ms
    if remain <= 0:
        return "即将清理"
    if remain < 3_600_000:
        return f"{remain // 60_000} 分钟后清理"
    return f"{remain // 3_600_000} 小时后清理" if remain < DAY_MS else f"{remain // DAY_MS} 天后清理"
