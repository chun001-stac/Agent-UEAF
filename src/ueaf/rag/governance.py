"""RAG governance: trigger guard, budget gate, revocation, benchmark.

RAG-002 single retrieval_empty != trigger: one empty retrieval never becomes a
Trigger/Mutation by itself.
RAG-003 context budget: after a context mutation, model/context/token/permission
constraints still hold.
RAG-007 ACL revocation propagation: a source that became visible then lost
access is removed from retrieval/cache within an SLO; past the SLO it is
isolated or fail-closed.
RAG-016 benchmark feeds the Quality Gate: a fixed retrieval benchmark compares
baseline/current recall, precision, citation, freshness, latency, cost and key
slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class RetrievalTriggerGuard:
    """RAG-002: a single empty retrieval is never itself a trigger."""

    min_evidence_refs: int = 1

    def should_trigger(self, *, retrieval_empty: bool, evidence_refs: tuple[str, ...]) -> bool:
        if retrieval_empty:
            return False  # single empty retrieval is not a mutation trigger
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
    """Tracks visible-then-revoked sources and enforces the SLO (RAG-007)."""

    revocation_slo_seconds: int = 300
    _revoked_at: dict[str, float] = field(default_factory=dict)

    def revoke(self, source_ref: str, *, now: float) -> None:
        self._revoked_at[source_ref] = now

    def is_servable(self, source_ref: str, *, now: float) -> bool:
        revoked = self._revoked_at.get(source_ref)
        if revoked is None:
            return True
        if now - revoked <= self.revocation_slo_seconds:
            return False  # removed from retrieval/cache within SLO
        return False  # past SLO: isolate or fail closed

    def fail_closed(self, source_ref: str, *, now: float) -> bool:
        revoked = self._revoked_at.get(source_ref)
        return revoked is not None and now - revoked > self.revocation_slo_seconds


@dataclass(frozen=True, slots=True)
class RetrievalBenchmark:
    """Fixed benchmark results feeding the Quality Gate (RAG-016)."""

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
