"""边缘预校验（功能模块 01，规范 02 §4.1）。

边缘预校验与 Run 准入相互独立。此处的拒绝绝不能创建 ``RunRecord`` 或
``RunAdmissionResult``（RUN-005）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ueaf.admission.objects import RequestEnvelope
from ueaf.common.error import ProblemDetail


@dataclass(frozen=True, slots=True)
class EdgeValidationResult:
    accepted: bool
    reason_codes: tuple[str, ...] = ()
    problem: ProblemDetail | None = None


class EdgePreValidator:
    """在任何运行/任务对象存在之前进行的确定性、只读预检。"""

    def __init__(
        self,
        *,
        max_request_bytes: int = 1_000_000,
        allow_channels: frozenset[str] = frozenset({"http", "websocket", "queue"}),
    ) -> None:
        self._max_bytes = max_request_bytes
        self._channels = allow_channels

    def validate(
        self,
        envelope: RequestEnvelope,
        *,
        observed_at: datetime,
    ) -> EdgeValidationResult:
        if envelope.channel not in self._channels:
            return EdgeValidationResult(
                accepted=False,
                reason_codes=(f"channel_not_allowed:{envelope.channel}",),
                problem=ProblemDetail(
                    code="channel_not_allowed",
                    category="validation",
                    message_safe="Request channel is not allowed",
                    retryability="never",
                    source="ueaf-edge",
                    object_ref=envelope.request_id,
                    observed_at=observed_at,
                ),
            )
        if envelope.deadline_at is not None and observed_at >= envelope.deadline_at:
            return EdgeValidationResult(
                accepted=False,
                reason_codes=("deadline_passed",),
                problem=ProblemDetail(
                    code="deadline_passed",
                    category="validation",
                    message_safe="Request deadline has passed",
                    retryability="never",
                    source="ueaf-edge",
                    object_ref=envelope.request_id,
                    observed_at=observed_at,
                ),
            )
        if envelope.validation_status == "rejected":
            return EdgeValidationResult(
                accepted=False,
                reason_codes=envelope.reason_codes or ("edge_pre_validation_rejected",),
                problem=ProblemDetail(
                    code="edge_pre_validation_rejected",
                    category="validation",
                    message_safe="Request failed edge pre-validation",
                    retryability="never",
                    source="ueaf-edge",
                    object_ref=envelope.request_id,
                    observed_at=observed_at,
                ),
            )
        return EdgeValidationResult(accepted=True, reason_codes=("edge_accepted",))
