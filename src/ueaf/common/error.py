"""跨进程错误契约。

按 core spec 03 与 implementation spec 02 §6，跨进程/API 错误使用
``ProblemDetail``；端口错误使用 ``PortResult<T> / PortError``（定义于
``ueaf.ports``）。有意不提供公开的 ``ErrorEnvelope``。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Retryability = Literal["never", "safe", "conditional", "after_reconciliation"]

_PROBLEM_CATEGORIES = (
    "validation",
    "authentication",
    "authorization",
    "policy",
    "not_found",
    "conflict",
    "transport",
    "provider",
    "timeout",
    "rate_limit",
    "capacity",
    "internal",
    "governance",
)


@dataclass(frozen=True, slots=True)
class ProblemDetail:
    """跨进程错误体；只含安全消息，诊断信息位于引用之后。"""

    code: str
    category: str
    message_safe: str
    retryability: Retryability
    source: str
    object_ref: str | None = None
    field_paths: tuple[str, ...] = ()
    correlation_refs: Mapping[str, str] = field(default_factory=dict)
    cause_ref: str | None = None
    observed_at: datetime | None = None
    details_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("ProblemDetail.code must not be empty")
        if self.category not in _PROBLEM_CATEGORIES:
            raise ValueError(f"unknown ProblemDetail.category {self.category!r}")
        if not self.message_safe:
            raise ValueError("ProblemDetail.message_safe must not be empty")
        if not self.source:
            raise ValueError("ProblemDetail.source must not be empty")


# V1 参考实现使用的稳定、机器可读的错误码。
ERROR_CODES = {
    "INVALID_STATE_TRANSITION": "invalid_state_transition",
    "STALE_FENCING": "stale_fencing_token",
    "REVISION_CONFLICT": "revision_conflict",
    "TERMINAL_CONFLICT": "terminal_conflict",
    "IDEMPOTENCY_CONFLICT": "idempotency_conflict",
    "NOT_ADMITTED": "run_not_admitted",
    "EXPIRED_RESULT": "expired_authority_result",
    "MISSING_POLICY_DECISION": "missing_policy_decision",
    "UNKNOWN_OUTCOME": "unknown_outcome",
    "UNSUPPORTED_CAPABILITY": "unsupported_capability",
    "INVALID_REPAIR_LEVEL": "invalid_repair_level",
    "MUTATION_OUT_OF_SCOPE": "mutation_out_of_scope",
}
