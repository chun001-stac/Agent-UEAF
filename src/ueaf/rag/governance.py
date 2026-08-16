"""RAG 治理：触发守卫、预算闸门、撤销、基准评测。

RAG-002 单次 retrieval_empty != 触发：一次空检索本身绝不会成为 Trigger/Mutation。
RAG-003 上下文预算：上下文变更后，model/context/token/permission 约束仍然成立。
RAG-007 ACL 撤销传播：曾经可见随后失去访问权限的来源会在 SLO 内从检索/缓存中
移除；超过 SLO 后会被隔离或 fail-closed。
RAG-016 基准评测为质量门禁提供输入：固定检索基准比较 baseline/current 的召回率、
精确率、引用、时效、延迟、成本及关键分片。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class RetrievalTriggerGuard:
    """RAG-002：单次空检索本身绝不会成为触发条件。"""

    min_evidence_refs: int = 1

    def should_trigger(self, *, retrieval_empty: bool, evidence_refs: tuple[str, ...]) -> bool:
        if retrieval_empty:
            return False  # 单次空检索不是变更触发条件
        return len(evidence_refs) >= self.min_evidence_refs


@dataclass(frozen=True, slots=True)
class ContextBudget:
    model_tokens: int
    context_tokens: int
    permission_refs: int

    def allows(self, *, tokens: int, permission_refs: int) -> bool:
        return (
            tokens <= self.model_tokens
            and tokens <= self.context_tokens
            and permission_refs <= self.permission_refs
        )


@dataclass(slots=True)
class RevocationTracker:
    """跟踪“先可见后被撤销”的来源，并强制执行 SLO（RAG-007）。"""

    revocation_slo_seconds: int = 300
    _revoked_at: dict[str, float] = field(default_factory=dict)

    def revoke(self, source_ref: str, *, now: float) -> None:
        self._revoked_at[source_ref] = now

    def is_servable(self, source_ref: str, *, now: float) -> bool:
        revoked = self._revoked_at.get(source_ref)
        if revoked is None:
            return True
        if now - revoked <= self.revocation_slo_seconds:
            return False  # 在 SLO 内从检索/缓存中移除
        return False  # 超过 SLO：隔离或 fail closed

    def fail_closed(self, source_ref: str, *, now: float) -> bool:
        revoked = self._revoked_at.get(source_ref)
        return revoked is not None and now - revoked > self.revocation_slo_seconds


@dataclass(frozen=True, slots=True)
class RetrievalBenchmark:
    """为质量门禁提供输入的固定基准结果（RAG-016）。"""

    benchmark_id: str
    baseline_recall: float
    baseline_precision: float
    current_recall: float
    current_precision: float
    citation_valid: bool = True
    freshness_ok: bool = True
    latency_millis: int = 0
    cost_millis: int = 0

    @property
    def digest(self) -> str:
        return sha256_hex(
            f"{self.benchmark_id}|{self.baseline_recall}|{self.baseline_precision}|"
            f"{self.current_recall}|{self.current_precision}"
        )

    def improved(self, *, recall_gain: float, precision_gain: float) -> bool:
        return (
            self.current_recall - self.baseline_recall >= recall_gain
            and self.current_precision - self.baseline_precision >= precision_gain
        )


__all__ = [
    "RetrievalTriggerGuard",
    "ContextBudget",
    "RevocationTracker",
    "RetrievalBenchmark",
]
