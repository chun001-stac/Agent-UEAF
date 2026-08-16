"""记忆使用审计与指标（功能模块 04 §9，RAG-005）。

每次召回记录（subject/scope/purpose/时刻/命中数/记录引用）并维护指标计数器；内存实现
供 ``TelemetryPort`` 采集（§9 观测指标）。正文、查询秘密和不可见资源标识绝不成为指标
标签（§9）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

METRIC_CANDIDATE_PROMOTED = "candidate_promoted"
METRIC_CANDIDATE_REJECTED = "candidate_rejected"
METRIC_REVIEW_TOTAL = "review_total"
METRIC_RECALL_USE_TOTAL = "recall_use_total"
METRIC_CONFLICT_TOTAL = "conflict_total"
METRIC_EXPIRY_LAG_SECONDS = "expiry_lag_seconds"
METRIC_DELETION_SLO_BREACH = "deletion_slo_breach"

_DEFAULT_COUNTERS = {
    METRIC_CANDIDATE_PROMOTED: 0,
    METRIC_CANDIDATE_REJECTED: 0,
    METRIC_REVIEW_TOTAL: 0,
    METRIC_RECALL_USE_TOTAL: 0,
    METRIC_CONFLICT_TOTAL: 0,
    METRIC_DELETION_SLO_BREACH: 0,
}


@dataclass(frozen=True, slots=True)
class RecallUsage:
    """一次召回使用记录（模块内部派生对象，非持久化规范对象）。"""

    subject_ref: str
    scope: str | None
    purpose: str | None
    recorded_at: datetime
    hit_count: int
    record_refs: tuple[str, ...] = ()


@dataclass(slots=True)
class MemoryAudit:
    """使用审计与指标计数器；供 TelemetryPort 采集（§9）。"""

    _usages: list[RecallUsage] = field(default_factory=list)
    _counters: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_COUNTERS))
    _expiry_lag_seconds: float = 0.0

    def record_recall(
        self,
        subject_ref: str,
        *,
        scope: str | None,
        purpose: str | None,
        moment: datetime,
        hit_count: int,
        record_refs: tuple[str, ...] = (),
    ) -> None:
        """记录一次召回（§9：memory_recall_use_total）。"""
        self._usages.append(
            RecallUsage(
                subject_ref=subject_ref,
                scope=scope,
                purpose=purpose,
                recorded_at=moment,
                hit_count=hit_count,
                record_refs=tuple(record_refs),
            )
        )
        self._counters[METRIC_RECALL_USE_TOTAL] += 1

    def increment(self, counter: str, value: int = 1) -> None:
        """对已登记的计数器累加；未知计数器直接拒绝（防漂移）。"""
        if counter not in self._counters:
            raise KeyError(f"unknown metric counter {counter!r}")
        self._counters[counter] += value

    def observe_expiry_lag(self, seconds: float) -> None:
        """记录过期滞后（memory_expiry_lag_seconds，取观测最大值）。"""
        self._expiry_lag_seconds = max(self._expiry_lag_seconds, seconds)

    def observe_deletion(self, propagation_seconds: float, slo_seconds: float) -> None:
        """删除传播超过 SLO 时计数（memory_deletion_slo_breach_total）。"""
        if slo_seconds > 0 and propagation_seconds > slo_seconds:
            self._counters[METRIC_DELETION_SLO_BREACH] += 1

    def metrics(self) -> dict[str, int | float]:
        """指标快照：供 TelemetryPort 采集（§9）。"""
        snapshot: dict[str, int | float] = dict(self._counters)
        snapshot[METRIC_EXPIRY_LAG_SECONDS] = self._expiry_lag_seconds
        return snapshot

    def usages(self) -> tuple[RecallUsage, ...]:
        return tuple(self._usages)


__all__ = [
    "METRIC_CANDIDATE_PROMOTED",
    "METRIC_CANDIDATE_REJECTED",
    "METRIC_REVIEW_TOTAL",
    "METRIC_RECALL_USE_TOTAL",
    "METRIC_CONFLICT_TOTAL",
    "METRIC_EXPIRY_LAG_SECONDS",
    "METRIC_DELETION_SLO_BREACH",
    "MemoryAudit",
    "RecallUsage",
]
