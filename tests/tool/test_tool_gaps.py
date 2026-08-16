"""Tool Gateway 缺口测试：ACT-006/010/012/014/017。

覆盖参考实现中缺失的 Tool 模块切片：拒绝权限时不自我提权（Tool Gateway）、
公开结果词汇表的一致性、租约期限约束、基于证明的失败重试，
以及凭据从 arguments/fingerprint/results 中的排除。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests import support
from ueaf.ports import (
    PortError,
    Rejected,
    Success,
    ToolIntent,
)
from ueaf.security.policy import PolicyDecisionPoint, PolicyRule
from ueaf.tool.action import ActionCoordinator, ActionReceipt, ActionStateError
from ueaf.tool.fingerprint import ActionFingerprint
from ueaf.tool.gateway import ToolGateway
from ueaf.tool.result import (
    DEFAULT_SECRET_KEYS,
    PUBLIC_STATUS_VALUES,
    ResultProjector,
    ToolResult,
)


def _pdp(*, approval: bool = False, deny: bool = False) -> PolicyDecisionPoint:
    rule = PolicyRule(
        rule_id="rule:create",
        action="cap:create_order",
        resource_pattern="orders/*",
        effect="deny" if deny else "allow",
        required_roles=("trader",),
        require_approval=approval,
    )
    return PolicyDecisionPoint(rules=(rule,))


def _intent(capability: str = "cap:create_order") -> ToolIntent:
    return ToolIntent(
        tool_intent_id="tool-intent:1",
        run_id="run:1",
        capability_ref=capability,
        input_schema_ref="schema://create-order-input/1.0.0",
        idempotency_key="idem:1",
    )


def _gateway(pdp: PolicyDecisionPoint | None = None) -> ToolGateway:
    return ToolGateway(ActionCoordinator(), pdp or _pdp(), tenant_id=support.TENANT)


@pytest.mark.test_id("ACT-006")
def test_permission_denied_forms_evidence_and_never_elevates() -> None:
    gateway = _gateway(_pdp(deny=True))
    result = gateway.submit(
        _intent(),
        principal=support.principal(roles=("trader",)),
        resource="orders/123",
        arguments={"amount": "10.00"},
    )
    assert isinstance(result, Rejected)
    assert result.error.certainty == "not_executed"
    assert result.error.code == "permission_denied"

    # 拒绝会形成携带在错误上的 Evidence 引用（ACT-006）。
    assert result.error.message_ref is not None
    assert result.error.message_ref.startswith("evidence:")
    evidence_ref = result.error.message_ref.removeprefix("evidence:")
    assert gateway.evidence_for(_denied_key(gateway)) is not None

    # 拒绝不得自我提权：action 是终态 `denied`，绝不会
    # reserved/executing，也不会引入被扩大的范围。
    action = gateway._coordinator.get(_denied_key(gateway))  # type: ignore[arg-type]
    assert action is None or action.phase in ("proposed", "terminal")
    if action is not None and action.phase == "terminal":
        assert action.disposition == "denied"
    assert evidence_ref


def _denied_key(gateway: ToolGateway) -> str:
    # 重建网关计算出的精确规范 key（参数已擦除）。
    from ueaf.tool.result import _scrub_secrets

    safe, _ = _scrub_secrets({"amount": "10.00"}, DEFAULT_SECRET_KEYS)
    fp = ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:create_order",
        capability_version="1.0.0",
        resource="orders/123",
        arguments=safe,
    )
    return fp.action_key


@pytest.mark.test_id("ACT-010")
def test_public_outcome_vocabulary_is_closed() -> None:
    # 只暴露公开词汇表（ACT-010）；诸如 "definite_not_executed" 之类的内部条件
    # 绝不得作为公开枚举值出现。
    assert PUBLIC_STATUS_VALUES == frozenset({"succeeded", "failed", "unknown"})
    with pytest.raises(ValueError):
        ToolResult(
            tool_result_id="t:1",
            action_key="k",
            status="definite_not_executed",  # type: ignore[arg-type]
            summary="s",
            content_schema_ref="schema://x/1.0.0",
        )

    # PortError 从封闭词汇表暴露 certainty/retryability。
    err = PortError(
        code="timeout",
        category="execution",
        retryability="after_reconciliation",
        certainty="unknown",
        message_ref="m:1",
        provider_error_ref=None,
        observed_at=support.now(),
        details_schema_ref=None,
    )
    assert err.certainty == "unknown"
    assert err.retryability == "after_reconciliation"

    # ActionReceipt.status 仅限于公开词汇表。
    with pytest.raises(ValueError):
        ActionReceipt(  # type: ignore[call-arg]
            action_receipt_id="r:1",
            action_key="k",
            action_fingerprint="fp",
            tool_intent_ref="t",
            capability_ref="c",
            executor_ref="e",
            status="definite_not_executed",  # type: ignore[arg-type]
        )


@pytest.mark.test_id("ACT-012")
def test_lease_renewal_bounded_by_absolute_deadline() -> None:
    coordinator = ActionCoordinator()
    action = coordinator.create_action(
        tool_intent_ref="tool-intent:1",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref="cap:create_order",
        fingerprint=_fingerprint(),
    )
    action = coordinator.validate(action, valid=True)
    decision = _pdp().evaluate(support.principal(roles=("trader",)), _fingerprint())
    action = coordinator.authorize(action, decision)  # -> reserved（allow）

    # 期限已过：过期的工作进程不得推进授权。
    coordinator.set_deadline(action, support.now() - timedelta(seconds=1))
    with pytest.raises(ActionStateError, match="deadline"):
        coordinator.begin_execution(action, fencing_token=1, now=support.now())
    with pytest.raises(ActionStateError, match="deadline"):
        coordinator.renew_lease(action, fencing_token=1, now=support.now())

    # 未来的期限允许继续执行。
    coordinator2 = ActionCoordinator()
    action2 = coordinator2.create_action(
        tool_intent_ref="tool-intent:1",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref="cap:create_order",
        fingerprint=_fingerprint(),
    )
    action2 = coordinator2.validate(action2, valid=True)
    action2 = coordinator2.authorize(action2, decision)
    coordinator2.set_deadline(action2, support.now() + timedelta(minutes=5))
    executing = coordinator2.begin_execution(action2, fencing_token=1, now=support.now())
    assert executing.phase == "executing"


@pytest.mark.test_id("ACT-014")
def test_failed_retry_requires_proof_and_preserves_action_key() -> None:
    coordinator = ActionCoordinator()
    decision = _pdp().evaluate(support.principal(roles=("trader",)), _fingerprint())
    action = coordinator.create_action(
        tool_intent_ref="tool-intent:1",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref="cap:create_order",
        fingerprint=_fingerprint(),
    )
    action = coordinator.validate(action, valid=True)
    action = coordinator.authorize(action, decision)
    action = coordinator.begin_execution(action, fencing_token=1)
    failed = coordinator.record_receipt(
        action,
        ActionReceipt(
            action_receipt_id="receipt:fail:1",
            action_key=action.action_key,
            action_fingerprint=action.action_fingerprint,
            tool_intent_ref="tool-intent:1",
            capability_ref="cap:create_order",
            executor_ref="executor:1",
            status="failed",
            attempt=1,
        ),
    )
    assert failed.phase == "terminal"
    assert failed.disposition == "failed"

    # 没有 retryability / 预算 / 证明时不进行重试。
    with pytest.raises(ActionStateError):
        coordinator.retry(failed, retryable=False, budget_remaining=1, evidence_ref="ev:1")
    with pytest.raises(ActionStateError):
        coordinator.retry(failed, retryable=True, budget_remaining=0, evidence_ref="ev:1")

    # 有证明且预算充足的重试以相同的 action_key 开始下一次尝试。
    next_attempt = coordinator.retry(
        failed, retryable=True, budget_remaining=2, evidence_ref="ev:1"
    )
    assert next_attempt.attempt == 2
    assert next_attempt.action_key == failed.action_key
    assert next_attempt.action_fingerprint == failed.action_fingerprint
    assert next_attempt.phase == "reserved"


@pytest.mark.test_id("ACT-017")
def test_credentials_never_enter_arguments_fingerprint_or_results() -> None:
    # 指纹的规范参数在哈希前会擦除秘密。
    fp = ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:create_order",
        capability_version="1.0.0",
        resource="orders/123",
        arguments={"amount": "10.00", "api_key": "super-secret-token-xyz"},
    )
    fingerprint_payload = fp.canonical_arguments
    assert "super-secret-token-xyz" not in str(fingerprint_payload)
    assert "api_key" in fingerprint_payload  # key 存在但值已脱敏

    # Tool Gateway 在创建 action 指纹前会擦除参数中的秘密。
    gateway = _gateway()
    result = gateway.submit(
        _intent(),
        principal=support.principal(roles=("trader",)),
        resource="orders/123",
        arguments={"amount": "10.00", "password": "p@ssw0rd"},
    )
    assert isinstance(result, Success)
    # 脱敏后的值永远不会出现在规范参数 / 指纹中。
    action = gateway._coordinator.get(result.value.action_id)  # type: ignore[union-attr]
    assert "p@ssw0rd" not in action.action_fingerprint
    assert "p@ssw0rd" not in str(action)

    # ResultProjector 永远不会将凭据泄露到 ToolResult 中。
    projector = ResultProjector()
    tool_result = projector.project(
        action_key="k",
        status="succeeded",
        raw={"data": "ok", "client_secret": "s3cret"},
        content_schema_ref="schema://result/1.0.0",
    )
    assert "s3cret" not in str(tool_result)
    assert "client_secret" in tool_result.excluded_secret_keys
    assert "client_secret" in DEFAULT_SECRET_KEYS


def _fingerprint() -> ActionFingerprint:
    return ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:create_order",
        capability_version="1.0.0",
        resource="orders/123",
        arguments={"amount": "10.00", "symbol": "IF"},
    )
