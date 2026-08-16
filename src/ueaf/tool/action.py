"""工具领域：ToolIntent、ActionRecord、ActionReceipt、ActionCoordinator。

ActionCoordinator 是动作的权威状态写入方（State Writer）。外部副作用仅在策略/审批/
预留之后发生（TX-A/TX-B/TX-C），未知结果进入对账而非盲目重试（ACT-003/013）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from ueaf.common.identifiers import new_object_id
from ueaf.common.meta import ContractMeta
from ueaf.security.policy import PolicyDecision
from ueaf.tool.fingerprint import ActionFingerprint

ActionPhase = Literal[
    "proposed", "validating", "authorizing", "waiting_approval", "reserved",
    "executing", "reconciling", "terminal",
]
ActionDisposition = Literal[
    "executed", "denied", "approval_rejected", "invalid", "failed", "unresolved", "cancelled",
]

_ACTION_PHASES: frozenset[str] = frozenset(
    {"proposed", "validating", "authorizing", "waiting_approval", "reserved",
     "executing", "reconciling", "terminal"}
)
_ACTION_DISPOSITIONS: frozenset[str] = frozenset(
    {"executed", "denied", "approval_rejected", "invalid", "failed", "unresolved", "cancelled"}
)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """动作的规范聚合（线上传输 + 持久化的权威对象）。"""

    meta: ContractMeta
    action_id: str
    action_key: str
    action_fingerprint: str
    tool_intent_ref: str
    run_id: str
    turn_id: str | None
    capability_ref: str
    phase: ActionPhase
    disposition: ActionDisposition | None = None
    policy_decision_ref: str | None = None
    approval_request_ref: str | None = None
    idempotency_reservation_ref: str | None = None
    receipt_refs: tuple[str, ...] = ()
    latest_receipt_ref: str | None = None
    reconciliation_state: Mapping[str, object] | None = None
    terminal_reason_codes: tuple[str, ...] = ()
    attempt: int = 1
    revision: int = 1
    sequence: int = 0
    lease_fencing_token: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.action_id != self.meta.object_id:
            raise ValueError("ActionRecord.meta.object_id must equal action_id")
        if self.phase not in _ACTION_PHASES:
            raise ValueError(f"invalid ActionPhase {self.phase!r}")
        if self.disposition is not None and self.phase != "terminal":
            raise ValueError("ActionRecord.disposition is only valid in terminal phase")
        if self.phase == "terminal" and self.disposition is None:
            raise ValueError("terminal ActionRecord MUST set disposition")
        if self.attempt < 1 or self.revision < 1:
            raise ValueError("ActionRecord attempt/revision must be >= 1")
        if self.lease_fencing_token is not None and self.lease_fencing_token < 1:
            raise ValueError("ActionRecord.lease_fencing_token must be a positive integer")


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """外部副作用回执；状态使用封闭的公共词表。"""

    action_receipt_id: str
    action_key: str
    action_fingerprint: str
    tool_intent_ref: str
    capability_ref: str
    executor_ref: str
    status: Literal["succeeded", "failed", "unknown"]
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    external_reference: str | None = None
    result_digest: str | None = None
    error: Mapping[str, object] | None = None
    reconciliation: Mapping[str, object] | None = None
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        # ACT-010：仅暴露公共结果词表。
        if self.status not in {"succeeded", "failed", "unknown"}:
            raise ValueError(f"invalid ActionReceipt.status {self.status!r}")
        if self.attempt < 1:
            raise ValueError("ActionReceipt.attempt must be >= 1")


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    attempt: int
    started_at: datetime
    finished_at: datetime | None = None
    receipt_ref: str | None = None
    outcome: Literal["succeeded", "failed", "unknown"] | None = None


class ActionStateError(RuntimeError):
    code = "invalid_action_transition"


def _validate_transition(from_phase: ActionPhase, to_phase: ActionPhase) -> None:
    allowed: dict[ActionPhase, frozenset[ActionPhase]] = {
        "proposed": frozenset({"validating", "terminal"}),
        "validating": frozenset({"authorizing", "terminal"}),
        "authorizing": frozenset({"waiting_approval", "reserved", "terminal"}),
        "waiting_approval": frozenset({"authorizing", "terminal"}),
        "reserved": frozenset({"executing", "terminal"}),
        "executing": frozenset({"reconciling", "terminal"}),
        "reconciling": frozenset({"terminal"}),
        "terminal": frozenset(),
    }
    if to_phase not in allowed.get(from_phase, frozenset()):
        raise ActionStateError(f"invalid_action_transition: {from_phase} -> {to_phase}")


class ActionCoordinator:
    """带 CAS/版本号与 fencing 检查的权威动作状态写入方。"""

    def __init__(self, *, producer_version: str = "0.1.0") -> None:
        self._records: dict[str, ActionRecord] = {}
        self._by_key: dict[str, str] = {}  # action_key -> action_id
        self._receipts: dict[str, ActionReceipt] = {}
        self._deadlines: dict[str, datetime] = {}  # action_id -> 绝对截止时间
        self._producer_version = producer_version

    # -- TX-A：策略判定前的稳定身份（ACT-001） ----------------------

    def create_action(
        self,
        *,
        tool_intent_ref: str,
        run_id: str,
        turn_id: str | None,
        capability_ref: str,
        fingerprint: ActionFingerprint,
        now: datetime | None = None,
    ) -> ActionRecord:
        existing = self._by_key.get(fingerprint.action_key)
        if existing is not None:
            return self._records[existing]  # 幂等（ACT-002）
        moment = now or _now()
        action_id = new_object_id("action")
        record = ActionRecord(
            meta=ContractMeta(
                contract_name="ActionRecord",
                contract_version="1.0.0",
                object_id=action_id,
                tenant_id=fingerprint.tenant_id,
                created_at=moment,
                producer="ueaf-tool-gateway",
                producer_version=self._producer_version,
                run_id=run_id,
                trace_id=fingerprint.trace_id,
            ),
            action_id=action_id,
            action_key=fingerprint.action_key,
            action_fingerprint=fingerprint.action_fingerprint,
            tool_intent_ref=tool_intent_ref,
            run_id=run_id,
            turn_id=turn_id,
            capability_ref=capability_ref,
            phase="proposed",
            created_at=moment,
            updated_at=moment,
        )
        self._records[action_id] = record
        self._by_key[record.action_key] = action_id
        return record

    def validate(self, action: ActionRecord, *, valid: bool) -> ActionRecord:
        self._require(action)
        if valid:
            return self._transition(action, "validating")
        return self._terminal(action, "invalid", ("schema_or_resource_invalid",))

    # -- 授权 -------------------------------------------------------

    def authorize(
        self,
        action: ActionRecord,
        decision: PolicyDecision,
        *,
        approval_request_ref: str | None = None,
    ) -> ActionRecord:
        self._require(action)
        _validate_transition(action.phase, "authorizing")
        authorizing = self._transition(
            action,
            "authorizing",
            policy_decision_ref=decision.policy_decision_id,
        )
        if decision.outcome == "deny":
            return self._terminal(authorizing, "denied", decision.reason_codes)
        if decision.outcome == "require_approval":
            if not approval_request_ref:
                raise ValueError("require_approval MUST provide an approval_request_ref")
            return self._transition(
                authorizing,
                "waiting_approval",
                approval_request_ref=approval_request_ref,
            )
        return self._transition(
            authorizing,
            "reserved",
            idempotency_reservation_ref=f"reservation:{action.action_key}",
        )

    # -- TX-B：预留 ---------------------------------------------------

    def reserve(
        self,
        action: ActionRecord,
        *,
        reservation_ref: str | None = None,
        fencing_token: int | None = None,
    ) -> ActionRecord:
        self._require(action)
        _validate_transition(action.phase, "reserved")
        updated = self._transition(
            action,
            "reserved",
            idempotency_reservation_ref=reservation_ref or f"reservation:{action.action_key}",
            lease_fencing_token=fencing_token,
        )
        return updated

    # -- 执行（在数据库事务之外） ------------------------------

    def begin_execution(
        self,
        action: ActionRecord,
        *,
        fencing_token: int | None = None,
        now: datetime | None = None,
    ) -> ActionRecord:
        self._require(action)
        self._check_fencing(action, fencing_token)
        self._check_deadline(action, now or _now())  # ACT-012
        _validate_transition(action.phase, "executing")
        return self._transition(action, "executing", lease_fencing_token=fencing_token)

    def renew_lease(
        self,
        action: ActionRecord,
        *,
        fencing_token: int,
        now: datetime | None = None,
    ) -> ActionRecord:
        """续租执行租约，绝不超过绝对截止时间（ACT-012）。"""
        self._require(action)
        self._check_fencing(action, fencing_token)
        moment = now or _now()
        self._check_deadline(action, moment)  # expired worker cannot advance
        return self._transition(
            action,
            "executing",
            lease_fencing_token=max(fencing_token, action.lease_fencing_token or 0),
        )

    def set_deadline(self, action: ActionRecord, deadline: datetime) -> None:
        """绑定绝对截止时间，此后任何工作进程都不得推进该动作。"""
        self._require(action)
        self._deadlines[action.action_id] = deadline

    # -- 重试（ACT-014） -----------------------------------------------------

    def retry(
        self,
        action: ActionRecord,
        *,
        retryable: bool,
        budget_remaining: int,
        evidence_ref: str,
        now: datetime | None = None,
    ) -> ActionRecord:
        """仅在已证实为 `failed` 的回执基础上启动下一次尝试。

        ACT-014：前一次尝试必须以回执/证据证明“未发生”或“确定失败”而终止；动作
        必须可重试、在预算内且在截止时间之内。``action_key`` 保持不变——下一次
        尝试仍是同一逻辑副作用。
        """
        self._require(action)
        moment = now or _now()
        if action.phase != "terminal" or action.disposition != "failed":
            raise ActionStateError(
                "retry requires a terminal ActionRecord with disposition 'failed'"
            )
        if not retryable:
            raise ActionStateError("retry not allowed: action is not retryable")
        if budget_remaining < 1:
            raise ActionStateError("retry not allowed: budget exhausted")
        self._check_deadline(action, moment)
        if not evidence_ref:
            raise ValueError("retry requires an evidence_ref proving the failed outcome")

        updated = replace(
            action,
            phase="reserved",
            disposition=None,
            reconciliation_state=None,
            terminal_reason_codes=(),
            receipt_refs=(),
            latest_receipt_ref=None,
            attempt=action.attempt + 1,
            revision=action.revision + 1,
            updated_at=moment,
        )
        self._records[action.action_id] = updated
        return updated

    # -- TX-C：记录观测结果 --------------------------------------------

    def record_receipt(
        self,
        action: ActionRecord,
        receipt: ActionReceipt,
        *,
        now: datetime | None = None,
    ) -> ActionRecord:
        self._require(action)
        if receipt.action_key != action.action_key:
            raise ValueError("receipt.action_key must match ActionRecord.action_key")
        self._receipts[receipt.action_receipt_id] = receipt
        receipt_refs = (*action.receipt_refs, receipt.action_receipt_id)
        base = replace(
            action,
            receipt_refs=receipt_refs,
            latest_receipt_ref=receipt.action_receipt_id,
            revision=action.revision + 1,
            updated_at=now or _now(),
        )
        if receipt.status == "unknown":
            _validate_transition(action.phase, "reconciling")
            return replace(
                base,
                phase="reconciling",
                reconciliation_state={
                    "status": "unknown",
                    "receipt_ref": receipt.action_receipt_id,
                },
            )
        _validate_transition(action.phase, "terminal")
        disposition: ActionDisposition = (
            "executed" if receipt.status == "succeeded" else "failed"
        )
        return replace(
            base,
            phase="terminal",
            disposition=disposition,
            terminal_reason_codes=(),
        )

    # -- 对账 ------------------------------------------------------

    def reconcile(
        self,
        action: ActionRecord,
        *,
        resolved_status: Literal["succeeded", "failed"],
        evidence_ref: str,
    ) -> ActionRecord:
        self._require(action)
        _validate_transition(action.phase, "terminal")
        disposition: ActionDisposition = (
            "executed" if resolved_status == "succeeded" else "failed"
        )
        return replace(
            action,
            phase="terminal",
            disposition=disposition,
            reconciliation_state={
                "resolved": resolved_status,
                "evidence_ref": evidence_ref,
            },
            revision=action.revision + 1,
            updated_at=_now(),
        )

    # -- 辅助方法 -------------------------------------------------------------

    def get(self, action_id: str) -> ActionRecord | None:
        return self._records.get(action_id)

    def _require(self, action: ActionRecord) -> None:
        if action.action_id not in self._records:
            raise KeyError(f"ActionRecord {action.action_id} not found")

    def _check_fencing(self, action: ActionRecord, fencing_token: int | None) -> None:
        if fencing_token is None:
            return
        if action.lease_fencing_token is not None and fencing_token < action.lease_fencing_token:
            raise ValueError(f"stale_fencing_token: {fencing_token}")

    def _check_deadline(self, action: ActionRecord, moment: datetime) -> None:
        """一旦超过绝对截止时间即拒绝推进（ACT-012）。"""
        deadline = self._deadlines.get(action.action_id)
        if deadline is not None and moment > deadline:
            raise ActionStateError(f"action deadline passed: {deadline.isoformat()}")

    def _transition(
        self,
        action: ActionRecord,
        to_phase: ActionPhase,
        **updates: object,
    ) -> ActionRecord:
        _validate_transition(action.phase, to_phase)
        updated = replace(
            action,
            phase=to_phase,
            revision=action.revision + 1,
            updated_at=_now(),
            **updates,  # type: ignore[arg-type]
        )
        self._records[action.action_id] = updated
        return updated

    def _terminal(
        self,
        action: ActionRecord,
        disposition: ActionDisposition,
        reason_codes: tuple[str, ...],
    ) -> ActionRecord:
        _validate_transition(action.phase, "terminal")
        updated = replace(
            action,
            phase="terminal",
            disposition=disposition,
            terminal_reason_codes=reason_codes,
            revision=action.revision + 1,
            updated_at=_now(),
        )
        self._records[action.action_id] = updated
        return updated


def _now() -> datetime:
    from ueaf.common.identifiers import utcnow

    return utcnow()
