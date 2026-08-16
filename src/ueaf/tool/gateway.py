"""工具网关 — ToolIntentPort 参考实现（模块 05）。

将模型的 ``ToolIntent`` 桥接到权威的 ``ActionCoordinator``：先计算规范指纹
（ACT-001/007），再进行校验与 PDP 授权。``deny`` 会形成 Evidence 引用并返回
``Rejected`` 结果——绝不自行提权或扩大主体权限范围（ACT-006）。
``require_approval`` 判定则变成等待审批的受控中断。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ueaf.admission.objects import PrincipalContext
from ueaf.common.identifiers import new_object_id, utcnow
from ueaf.ports import (
    ActionRecordRef,
    ControlledInterruption,
    PortError,
    PortResult,
    Rejected,
    Success,
    ToolIntent,
)
from ueaf.security.policy import PolicyDecisionPoint
from ueaf.tool.action import ActionCoordinator
from ueaf.tool.fingerprint import ActionFingerprint
from ueaf.tool.result import DEFAULT_SECRET_KEYS, _scrub_secrets


@dataclass(frozen=True, slots=True)
class PermissionDenied:
    """形成证据的拒绝结果；绝不是权限范围的提升（ACT-006）。"""

    action_ref: ActionRecordRef
    evidence_ref: str
    reason_codes: tuple[str, ...]


class ToolGateway:
    """基于 ActionCoordinator + PDP 的 ToolIntentPort 参考实现。"""

    def __init__(
        self,
        coordinator: ActionCoordinator,
        pdp: PolicyDecisionPoint,
        *,
        tenant_id: str = "tenant-demo",
        producer_version: str = "0.1.0",
    ) -> None:
        self._coordinator = coordinator
        self._pdp = pdp
        self._tenant_id = tenant_id
        self._producer_version = producer_version
        self._evidence_refs: dict[str, str] = {}  # action_key -> evidence_ref

    def submit(
        self,
        intent: ToolIntent,
        *,
        principal: PrincipalContext,
        resource: str,
        arguments: Mapping[str, Any],
        purpose: str = "execution",
        now: datetime | None = None,
    ) -> PortResult[ActionRecordRef | ControlledInterruption | PermissionDenied]:
        """规范化、创建 ActionRecord、校验并授权。"""
        moment = now or utcnow()
        # 凭据绝不进入参数/指纹（ACT-017）。
        safe_arguments, _ = _scrub_secrets(dict(arguments), DEFAULT_SECRET_KEYS)
        fingerprint = ActionFingerprint(
            tenant_id=self._tenant_id,
            principal_id=principal.principal_id,
            capability_ref=intent.capability_ref,
            capability_version="1.0.0",
            resource=resource,
            arguments=safe_arguments,
            purpose=purpose,
            trace_id=f"trace:{intent.run_id}",
        )
        action = self._coordinator.create_action(
            tool_intent_ref=intent.tool_intent_id,
            run_id=intent.run_id,
            turn_id=None,
            capability_ref=intent.capability_ref,
            fingerprint=fingerprint,
            now=moment,
        )
        action = self._coordinator.validate(action, valid=True)

        decision = self._pdp.evaluate(
            principal, fingerprint, environment="prod", now=moment
        )
        if decision.outcome == "deny":
            # ACT-006：形成 Evidence 引用，绝不自行提权。
            evidence_ref = new_object_id("evidence")
            self._evidence_refs[action.action_key] = evidence_ref
            self._coordinator.authorize(action, decision)  # terminal denied
            return Rejected(
                PortError(
                    code="permission_denied",
                    category="policy",
                    retryability="never",
                    certainty="not_executed",
                    message_ref=f"evidence:{evidence_ref}",
                    provider_error_ref=None,
                    observed_at=moment,
                    details_schema_ref="schema://permission-denied/1.0.0",
                )
            )

        if decision.outcome == "require_approval":
            approval_ref = new_object_id("approval_request")
            self._coordinator.authorize(
                action, decision, approval_request_ref=approval_ref
            )
            return Success(
                ControlledInterruption(
                    wait_reason="approval",
                    resume_condition_ref=f"approval:{approval_ref}",
                    expires_at=None,
                )
            )

        reserved = self._coordinator.authorize(action, decision)
        return Success(ActionRecordRef(action_id=reserved.action_id, revision=reserved.revision))

    def evidence_for(self, action_key: str) -> str | None:
        return self._evidence_refs.get(action_key)


__all__ = ["ToolGateway", "PermissionDenied"]
