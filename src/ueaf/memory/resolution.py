"""候选治理结果：``MemoryResolution``（模块内部派生对象，非持久化规范对象）。

对应功能模块 04 §4.5：``MemoryResolution`` 返回 ``promoted/rejected/needs_review``
三态、理由码和生成的 record 引用。它不是 Run 终态决定——记忆晋升失败不会把已完成的
业务动作改为 Run failed，只形成可观察的治理决定（CTX-001 记忆语义 / CTX-007：
04 只在授权范围内重建投影，绝不把候选直接当作终态事实）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryOutcome = Literal["promoted", "rejected", "needs_review"]

REASON_CONSENT_REQUIRED = "consent_required"
REASON_DUPLICATE = "duplicate"
REASON_CONFLICT = "conflict_detected"
REASON_TEAM_TENANT_REVIEW = "team_tenant_requires_review"
REASON_NOT_APPROVED = "not_approved"
REASON_SESSION_NOT_PERSISTED = "session_memory_not_persisted"
REASON_SCOPE_REQUIRES_REVIEW = "scope_requires_review"


@dataclass(frozen=True, slots=True)
class MemoryResolution:
    """一次候选治理的决定结果（模块内部派生对象，非持久化规范对象）。

    ``outcome`` 为 ``promoted/rejected/needs_review`` 三态；``reason_codes`` 表达
    决定理由（如 ``consent_required``/``duplicate``/``conflict_detected``）；
    ``record_ref`` 在 promoted 时指向生成的 ``MemoryRecord``；``candidate_ref``
    溯源到产生它的候选。
    """

    outcome: MemoryOutcome
    reason_codes: tuple[str, ...] = ()
    record_ref: str | None = None
    candidate_ref: str | None = None


__all__ = [
    "MemoryOutcome",
    "MemoryResolution",
    "REASON_CONSENT_REQUIRED",
    "REASON_DUPLICATE",
    "REASON_CONFLICT",
    "REASON_TEAM_TENANT_REVIEW",
    "REASON_NOT_APPROVED",
    "REASON_SESSION_NOT_PERSISTED",
    "REASON_SCOPE_REQUIRES_REVIEW",
]
