"""阶段 3 action 生命周期验收测试（ACT-*）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests import support
from ueaf.security.policy import PolicyDecisionPoint, PolicyRule
from ueaf.tool.action import ActionCoordinator, ActionReceipt
from ueaf.tool.fingerprint import ActionFingerprint


def _fingerprint(*, args=None, resource="orders/123", **kwargs) -> ActionFingerprint:
    return ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref=kwargs.get("capability_ref", "cap:create_order"),
        capability_version="1.0.0",
        resource=resource,
        arguments=args if args is not None else {"amount": "10.00", "symbol": "IF"},
        trace_id="trace:1",
    )


def _coordinator(role_rule: bool = True) -> tuple[ActionCoordinator, PolicyDecisionPoint]:
    rules = []
    if role_rule:
        rules.append(
            PolicyRule(
                rule_id="rule:create",
                action="cap:create_order",
                resource_pattern="orders/*",
                effect="allow",
                required_roles=("trader",),
            )
        )
    pdp = PolicyDecisionPoint(rules=tuple(rules))
    return ActionCoordinator(), pdp


def _created_action(coordinator: ActionCoordinator, *, fingerprint=None, validate: bool = True):
    fp = fingerprint or _fingerprint()
    action = coordinator.create_action(
        tool_intent_ref=f"tool-intent:{fp.action_fingerprint[:12]}",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref=fp.capability_ref,
        fingerprint=fp,
    )
    if validate:
        if action.phase == "proposed":
            return coordinator.validate(action, valid=True)
        return action
    return action


def _allowed_decision(pdp, fingerprint=None, *, roles=("trader",)):
    principal = support.principal(roles=roles)
    return pdp.evaluate(principal, fingerprint or _fingerprint(), now=support.now())


@pytest.mark.test_id("ACT-001")
def test_action_identity_is_stable_before_policy() -> None:
    coordinator, pdp = _coordinator()
    fp = _fingerprint()
    action = _created_action(coordinator, fingerprint=fp, validate=False)
    # 身份在创建时即固定，早于任何策略评估。
    assert action.action_key == fp.action_key
    assert action.action_fingerprint == fp.action_fingerprint
    validated = coordinator.validate(action, valid=True)
    decision = _allowed_decision(pdp, fp)
    authorized = coordinator.authorize(validated, decision)
    assert authorized.action_key == action.action_key  # 不变


@pytest.mark.test_id("ACT-002")
def test_action_key_is_idempotent() -> None:
    coordinator, _ = _coordinator()
    fp = _fingerprint()
    first = _created_action(coordinator, fingerprint=fp)
    second = _created_action(coordinator, fingerprint=fp)  # 相同的逻辑 action
    assert first.action_id == second.action_id
    assert first.action_key == second.action_key


@pytest.mark.test_id("ACT-003")
def test_timeout_unknown_enters_reconciliation_not_blind_retry() -> None:
    coordinator, pdp = _coordinator()
    action = _created_action(coordinator)
    action = coordinator.authorize(action, _allowed_decision(pdp))
    action = coordinator.begin_execution(action, fencing_token=1)
    receipt = ActionReceipt(
        action_receipt_id="receipt:unknown:1",
        action_key=action.action_key,
        action_fingerprint=action.action_fingerprint,
        tool_intent_ref="tool-intent:1",
        capability_ref=action.capability_ref,
        executor_ref="executor:1",
        status="unknown",
        attempt=1,
    )
    reconciling = coordinator.record_receipt(action, receipt)
    assert reconciling.phase == "reconciling"
    assert reconciling.reconciliation_state["status"] == "unknown"
    # 没有调度第二次写入 —— action 不会被重新执行。
    assert reconciling.attempt == 1


@pytest.mark.test_id("ACT-004")
def test_certain_failure_allows_next_attempt() -> None:
    coordinator, pdp = _coordinator()
    action = _created_action(coordinator)
    action = coordinator.authorize(action, _allowed_decision(pdp))
    action = coordinator.begin_execution(action, fencing_token=1)
    failed = ActionReceipt(
        action_receipt_id="receipt:fail:1",
        action_key=action.action_key,
        action_fingerprint=action.action_fingerprint,
        tool_intent_ref="tool-intent:1",
        capability_ref=action.capability_ref,
        executor_ref="executor:1",
        status="failed",
        attempt=1,
    )
    terminal = coordinator.record_receipt(action, failed)
    assert terminal.phase == "terminal"
    assert terminal.disposition == "failed"


@pytest.mark.test_id("ACT-005")
def test_approval_fail_closed() -> None:
    coordinator, pdp = _coordinator()
    fp = _fingerprint(capability_ref="cap:high_risk_write")
    action = _created_action(coordinator, fingerprint=fp)
    rules = (PolicyRule("rule:hw", "cap:high_risk_write", "orders/*", "allow",
                        required_roles=("trader",), require_approval=True),)
    pdp_hw = PolicyDecisionPoint(rules=rules)
    decision = pdp_hw.evaluate(support.principal(roles=("trader",)), fp, now=support.now())
    assert decision.outcome == "require_approval"
    with pytest.raises(ValueError, match="approval_request_ref"):
        coordinator.authorize(action, decision)  # 审批基础设施缺失 -> fail closed


@pytest.mark.test_id("ACT-007")
def test_canonical_argument_identity_is_order_and_digit_stable() -> None:
    a = _fingerprint(args={"amount": Decimal("10.00"), "symbol": "IF"})
    # 重排 + 数字规范化的参数必须规范化到相同的身份。
    b = _fingerprint(args={"symbol": "IF", "amount": Decimal("10.0")})
    assert a.action_fingerprint == b.action_fingerprint


@pytest.mark.test_id("ACT-008")
def test_fingerprint_binds_only_canonical_fields() -> None:
    a = _fingerprint(args={"symbol": "IF"})
    b = _fingerprint(args={"symbol": "IF", "decorative": "x"})
    assert a.action_fingerprint != b.action_fingerprint
    # 更改 principal 身份会改变指纹。
    c = ActionFingerprint(
        tenant_id=support.TENANT, principal_id="principal-other",
        capability_ref="cap:create_order", capability_version="1.0.0",
        resource="orders/123", arguments={"symbol": "IF"},
    )
    assert a.action_fingerprint != c.action_fingerprint


@pytest.mark.test_id("ACT-009")
def test_policy_cannot_change_action_identity() -> None:
    coordinator, pdp = _coordinator()
    fp = _fingerprint()
    action = _created_action(coordinator, fingerprint=fp)
    before_key = action.action_key
    before_fp = action.action_fingerprint
    coordinator.authorize(action, _allowed_decision(pdp, fp))
    # 语义变更需要新的 action；策略永远不会重写身份。
    assert action.action_key == before_key
    assert action.action_fingerprint == before_fp


@pytest.mark.test_id("ACT-011")
def test_stale_fencing_result_cannot_commit_terminal() -> None:
    coordinator, pdp = _coordinator()
    action = _created_action(coordinator)
    action = coordinator.authorize(action, _allowed_decision(pdp))
    action = coordinator.begin_execution(action, fencing_token=2)
    # 持有较旧 fencing token 的过期工作进程无法推进授权。
    with pytest.raises(ValueError, match="stale_fencing_token"):
        coordinator.begin_execution(action, fencing_token=1)


@pytest.mark.test_id("ACT-013")
def test_unknown_reconciliation_no_second_business_write() -> None:
    coordinator, pdp = _coordinator()
    action = _created_action(coordinator)
    action = coordinator.authorize(action, _allowed_decision(pdp))
    action = coordinator.begin_execution(action, fencing_token=1)
    reconciling = coordinator.record_receipt(
        action,
        ActionReceipt(
            action_receipt_id="receipt:u:1", action_key=action.action_key,
            action_fingerprint=action.action_fingerprint,
            tool_intent_ref="t", capability_ref=action.capability_ref,
            executor_ref="e", status="unknown", attempt=1,
        ),
    )
    resolved = coordinator.reconcile(reconciling, resolved_status="succeeded", evidence_ref="ev:1")
    assert resolved.phase == "terminal"
    assert resolved.disposition == "executed"
    # 全程只有一条业务写入路径。
    assert resolved.latest_receipt_ref == "receipt:u:1"


@pytest.mark.test_id("ACT-015")
def test_valid_cached_policy_decision_only() -> None:
    coordinator, pdp = _coordinator()
    fp = _fingerprint()
    decision = _allowed_decision(pdp, fp)
    assert decision.is_valid_at(support.now())
    action = _created_action(coordinator, fingerprint=fp)
    authorized = coordinator.authorize(action, decision)
    assert authorized.phase == "reserved"


@pytest.mark.test_id("ACT-018")
def test_terminal_evidence_chain_preserved() -> None:
    coordinator, pdp = _coordinator()
    fp = _fingerprint()
    action = _created_action(coordinator, fingerprint=fp)
    decision = _allowed_decision(pdp, fp)
    action = coordinator.authorize(action, decision)
    action = coordinator.begin_execution(action, fencing_token=1)
    receipt = ActionReceipt(
        action_receipt_id="receipt:ok:1", action_key=action.action_key,
        action_fingerprint=action.action_fingerprint,
        tool_intent_ref=action.tool_intent_ref,
        capability_ref=action.capability_ref, executor_ref="executor:1",
        status="succeeded", attempt=1,
    )
    terminal = coordinator.record_receipt(action, receipt)
    assert terminal.policy_decision_ref == decision.policy_decision_id
    assert terminal.idempotency_reservation_ref is not None
    assert receipt.action_receipt_id in terminal.receipt_refs
    assert terminal.latest_receipt_ref == "receipt:ok:1"
