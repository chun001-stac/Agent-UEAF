"""Phase 3 security / policy tests (SEC-*, ACT-015)."""

from __future__ import annotations

import pytest

from tests import support
from ueaf.security.policy import PolicyDecisionPoint, PolicyRule
from ueaf.tool.fingerprint import ActionFingerprint


def _fp(resource: str = "orders/123") -> ActionFingerprint:
    return ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:read_report",
        capability_version="1.0.0",
        resource=resource,
        arguments={},
    )


@pytest.mark.test_id("SEC-006")
def test_deny_by_default_with_no_matching_rule() -> None:
    pdp = PolicyDecisionPoint(rules=())
    decision = pdp.evaluate(support.principal(), _fp(), now=support.now())
    assert decision.outcome == "deny"
    assert "no_matching_rule" in decision.reason_codes


@pytest.mark.test_id("SEC-007")
def test_action_vocabulary_is_controlled() -> None:
    pdp = PolicyDecisionPoint(
        rules=(PolicyRule("r1", "cap:read_report", "orders/*", "allow", ("analyst",)),)
    )
    allowed = pdp.evaluate(
        support.principal(roles=("analyst",)), _fp(), now=support.now()
    )
    assert allowed.outcome == "allow"
    # A different (unmatched) action is denied.
    other = ActionFingerprint(
        tenant_id=support.TENANT, principal_id="principal-user-1",
        capability_ref="cap:delete_all", capability_version="1.0.0",
        resource="orders/123", arguments={},
    )
    denied = pdp.evaluate(support.principal(roles=("analyst",)), other, now=support.now())
    assert denied.outcome == "deny"


@pytest.mark.test_id("SEC-008")
def test_resource_canonicalization() -> None:
    pdp = PolicyDecisionPoint(
        rules=(PolicyRule("r1", "cap:read_report", "orders/*", "allow", ("analyst",)),)
    )
    # fnmatch-style resource pattern applies consistently to both spellings.
    a = pdp.evaluate(support.principal(roles=("analyst",)), _fp("orders/1"), now=support.now())
    b = pdp.evaluate(support.principal(roles=("analyst",)), _fp("orders/2"), now=support.now())
    assert a.outcome == "allow"
    assert b.outcome == "allow"


@pytest.mark.test_id("SEC-019")
def test_cached_decision_is_not_a_local_pdp() -> None:
    pdp = PolicyDecisionPoint(
        rules=(PolicyRule("r1", "cap:read_report", "orders/*", "allow", ("analyst",)),)
    )
    decision = pdp.evaluate(support.principal(roles=("analyst",)), _fp(), now=support.now())
    assert decision.outcome == "allow"
    # Expired decisions must not be reused as if freshly authorized.
    expired = pdp.evaluate(
        support.principal(roles=("analyst",)), _fp(),
        now=datetime(2020, 1, 1, tzinfo=UTC),
    )
    assert expired.is_valid_at(support.now()) is False


from datetime import UTC, datetime  # noqa: E402
