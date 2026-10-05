"""保留策略（条数上限 + 七天过期）单测。"""

from __future__ import annotations

from copyama.core.models import Clip, ClipType
from copyama.core.retention import (
    DAY_MS,
    CleanupPlan,
    RetentionPolicy,
    cutoff_ms,
    plan_cleanup,
)

NOW = 1_800_000_000_000


def clip(cid: int, age_days: float = 0, *, pinned: bool = False, deleted: bool = False) -> Clip:
    return Clip(
        type=ClipType.TEXT,
        content=f"c{cid}",
        id=cid,
        created_at=NOW - int(age_days * DAY_MS),
        pinned=pinned,
        deleted=deleted,
    )


def test_cutoff():
    assert cutoff_ms(NOW, 7) == NOW - 7 * DAY_MS
    assert cutoff_ms(NOW, 0) < 0, "0 表示不过期"


def test_no_cleanup_when_under_limits():
    clips = [clip(i, age_days=0.1) for i in range(1, 11)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=200, max_age_days=7))
    assert plan.total == 0
    assert plan.keep_count == 10


def test_expired_removed_after_seven_days():
    clips = [clip(1, age_days=6.9), clip(2, age_days=7.1), clip(3, age_days=30)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=200, max_age_days=7))
    assert plan.expired_ids == (2, 3)
    assert plan.keep_count == 1


def test_age_zero_disables_time_cleanup():
    clips = [clip(1, age_days=999)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=200, max_age_days=0))
    assert plan.total == 0


def test_overflow_removes_oldest_unpinned():
    clips = [clip(i, age_days=i) for i in range(1, 11)]  # 1 最新 → 10 最旧
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=3, max_age_days=0))
    assert len(plan.overflow_ids) == 7
    assert 10 in plan.overflow_ids and 9 in plan.overflow_ids and 8 in plan.overflow_ids
    assert 1 not in plan.overflow_ids
    assert plan.keep_count == 3


def test_pinned_exempt_but_counted_in_quota():
    # 1 条固定 + 5 条普通，上限 3 → 固定项占名额但绝不被淘汰，只淘汰最旧的 3 条普通
    clips = [clip(1, age_days=100, pinned=True)] + [clip(i, age_days=i) for i in range(2, 7)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=3, max_age_days=0))
    assert 1 not in plan.all_ids()
    assert set(plan.overflow_ids) == {4, 5, 6}
    assert plan.keep_count == 3


def test_pinned_never_evicted_even_over_quota():
    clips = [clip(1, pinned=True), clip(2, pinned=True), clip(3)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_items=1, max_age_days=0))
    assert 1 not in plan.all_ids() and 2 not in plan.all_ids()
    assert plan.overflow_ids == (3,)


def test_pinned_still_expires_when_exemption_off():
    clips = [clip(1, age_days=100, pinned=True)]
    plan = plan_cleanup(clips, NOW, RetentionPolicy(max_age_days=7, keep_pinned=False))
    assert plan.expired_ids == (1,)


def test_deleted_clips_ignored():
    plan = plan_cleanup([clip(1, age_days=99, deleted=True)], NOW, RetentionPolicy(max_age_days=7))
    assert plan.total == 0


def test_plan_summary_and_ids():
    plan = CleanupPlan(expired_ids=(1, 2), overflow_ids=(3,), keep_count=5)
    assert plan.total == 3
    assert plan.all_ids() == (1, 2, 3)
    assert "3 条" in plan.summary()
    assert CleanupPlan().summary() == "无需清理"


def test_policy_describe():
    text = RetentionPolicy(max_items=200, max_age_days=7).describe()
    assert "200 条" in text and "7 天" in text
    assert "不限制条数" in RetentionPolicy(max_items=0).describe()
    assert "不按时间清理" in RetentionPolicy(max_age_days=0).describe()
