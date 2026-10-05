"""保留策略：条数上限 + 时间上限，控制历史规模与磁盘占用。

对应需求：
- 「默认 200 条」——超出上限就删除最旧的**未固定**记录；
- 「七天前的就删除」——早于 ``max_age_days`` 的记录到期清理；
- 「超出设置的条数的东西就删除记录」——与设置界面联动。

设计：判定是纯函数（``plan_cleanup``），执行交给 ``Storage``，
两者解耦，便于在不碰数据库的情况下覆盖各种边界。
固定（pinned）记录默认豁免清理——那是用户显式保留的东西。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from copyama.core.models import Clip

DAY_MS = 86_400_000


@dataclass(frozen=True)
class RetentionPolicy:
    """清理策略。"""

    max_items: int = 200      # 0 表示不按条数上限清理
    max_age_days: int = 7     # 0 表示不按时间清理
    keep_pinned: bool = True  # 固定条目豁免

    @property
    def max_age_ms(self) -> int:
        return max(0, self.max_age_days) * DAY_MS

    def describe(self) -> str:
        parts: list[str] = []
        parts.append(f"最多保留 {self.max_items} 条" if self.max_items > 0 else "不限制条数")
        parts.append(
            f"{self.max_age_days} 天前的自动清理" if self.max_age_days > 0 else "不按时间清理"
        )
        if self.keep_pinned:
            parts.append("固定的条目不清理")
        return "，".join(parts)


@dataclass(frozen=True)
class CleanupPlan:
    """一次清理的规划结果（只有 id，不持有数据）。"""

    expired_ids: tuple[int, ...] = ()
    overflow_ids: tuple[int, ...] = ()
    keep_count: int = 0

    @property
    def total(self) -> int:
        return len(self.expired_ids) + len(self.overflow_ids)

    def all_ids(self) -> tuple[int, ...]:
        return self.expired_ids + self.overflow_ids

    def summary(self) -> str:
        if not self.total:
            return "无需清理"
        return f"清理 {self.total} 条（超期 {len(self.expired_ids)}，超限 {len(self.overflow_ids)}）"


def cutoff_ms(now_ms: int, days: int) -> int:
    """返回过期判定阈值（毫秒）。days<=0 时返回最小值，表示不过期。"""
    if days <= 0:
        return -(2**63)
    return now_ms - days * DAY_MS


def is_expired(clip: Clip, cutoff: int) -> bool:
    """记录是否已过保留期（pinned 由调用方先行过滤）。"""
    return clip.created_at < cutoff


def plan_cleanup(
    clips: Iterable[Clip], now_ms: int, policy: RetentionPolicy
) -> CleanupPlan:
    """规划要清理的 id 列表。

    规则（按优先级）：
    1. 已软删的记录不参与（由回收站策略另行处理）；
    2. ``keep_pinned`` 时固定条目永不清理，且不占用条数名额；
    3. 超过 ``max_age_days`` 的先清理；
    4. 剩余记录按时间倒序保留前 ``max_items`` 条，更旧的一律清理。
    """
    active = [c for c in clips if not c.deleted]
    pinned = [c for c in active if c.pinned] if policy.keep_pinned else []
    movable = [c for c in active if not (policy.keep_pinned and c.pinned)]

    cutoff = cutoff_ms(now_ms, policy.max_age_days)
    expired: list[Clip] = []
    alive: list[Clip] = []
    for clip in movable:
        (expired if is_expired(clip, cutoff) else alive).append(clip)

    expired_ids = [c.id for c in expired if c.id is not None]

    # 剩余容量 = 上限 - 固定条目数（固定项不淘汰，也不占名额）
    capacity = max(0, policy.max_items - len(pinned)) if policy.max_items > 0 else len(alive)
    overflow_ids: list[int] = []
    if len(alive) > capacity:
        ordered = sorted(alive, key=lambda c: (c.created_at, c.id or 0))
        for clip in ordered[: len(alive) - capacity]:
            if clip.id is not None:
                overflow_ids.append(clip.id)

    keep_count = len(pinned) + max(0, len(alive) - len(overflow_ids))
    return CleanupPlan(
        expired_ids=tuple(expired_ids),
        overflow_ids=tuple(overflow_ids),
        keep_count=keep_count,
    )


def plan_for_storage(storage, policy: RetentionPolicy, now_ms: int) -> CleanupPlan:
    """直接对存储层规划（内部会取出全部未删记录）。"""
    return plan_cleanup(storage.active_clips(), now_ms, policy)


def apply_plan(storage, plan: CleanupPlan) -> int:
    """执行清理计划，返回删除条数。"""
    ids: Sequence[int] = plan.all_ids()
    if not ids:
        return 0
    return storage.purge(ids)
