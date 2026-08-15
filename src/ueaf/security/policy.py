"""PolicyDecisionPoint — the only owner of ``PolicyDecision`` (SEC-004/006/019).

Local rule snapshots must never become a second PDP; a runtime authorization
is only expressed by a signed, valid ``PolicyDecision``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ueaf.admission.objects import PrincipalContext
from ueaf.common.identifiers import new_object_id, sha256_hex, utcnow
from ueaf.common.meta import ContractMeta
from ueaf.tool.fingerprint import ActionFingerprint

PolicyOutcome = Literal["allow", "deny", "require_approval"]

_POLICY_OUTCOMES: frozenset[str] = frozenset({"allow", "deny", "require_approval"})


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Runtime principal-action-resource-environment authorization only."""

    meta: ContractMeta
    policy_decision_id: str
    principal_context_ref: str
    action: str
    resource: str
    environment: str
    outcome: PolicyOutcome
    constraints: Mapping[str, object] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    policy_versions: tuple[str, ...] = ()
    evaluated_at: datetime | None = None
    expires_at: datetime | None = None
    input_hash: str | None = None

    def __post_init__(self) -> None:
        if self.policy_decision_id != self.meta.object_id:
            raise ValueError("PolicyDecision.meta.object_id must equal policy_decision_id")
        if self.outcome not in _POLICY_OUTCOMES:
            raise ValueError(f"invalid PolicyDecision outcome {self.outcome!r}")
        if self.outcome == "deny" and not self.reason_codes:
            raise ValueError("deny PolicyDecision MUST set reason_codes")

    def is_valid_at(self, moment: datetime) -> bool:
        if self.evaluated_at is not None and moment < self.evaluated_at:
            return False
        if self.expires_at is not None and moment >= self.expires_at:
            return False
        return True


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Immutable declarative rule evaluated by the PDP."""

    rule_id: str
    action: str
    resource_pattern: str
    effect: PolicyOutcome
    required_roles: tuple[str, ...] = ()
    require_approval: bool = False
    version: str = "1.0.0"


class PolicyDecisionPoint:
    """Deny-by-default PDP; no allow without a matching rule."""

    def __init__(
        self, *, rules: tuple[PolicyRule, ...] = (), producer_version: str = "0.1.0"
    ) -> None:
        self._rules = list(rules)
        self._producer_version = producer_version

    def evaluate(
        self,
        principal: PrincipalContext,
        fingerprint: ActionFingerprint,
        *,
        environment: str = "prod",
        now: datetime | None = None,
    ) -> PolicyDecision:
        moment = now or utcnow()
        decision_id = new_object_id("policy")
        role_intersection = set(principal.roles).intersection(
            role for rule in self._rules for role in rule.required_roles
        )

        matched = [
            rule
            for rule in self._rules
            if rule.action == fingerprint.capability_ref
            and _resource_matches(rule.resource_pattern, fingerprint.resource)
        ]

        if not matched:
            return self._decision(
                decision_id, principal, fingerprint, "deny", ("no_matching_rule",),
                environment=environment, moment=moment,
            )
        if any(rule.require_approval for rule in matched):
            return self._decision(
                decision_id, principal, fingerprint, "require_approval", ("approval_required",),
                environment=environment, moment=moment,
            )
        allowed_rules = [rule for rule in matched if rule.effect == "allow"]
        if allowed_rules and role_intersection:
            return self._decision(
                decision_id, principal, fingerprint, "allow", ("rule_matched",),
                environment=environment, moment=moment,
            )
        return self._decision(
            decision_id, principal, fingerprint, "deny", ("missing_role",),
            environment=environment, moment=moment,
        )

    def _decision(
        self,
        decision_id: str,
        principal: PrincipalContext,
        fingerprint: ActionFingerprint,
        outcome: PolicyOutcome,
        reason_codes: tuple[str, ...],
        *,
        environment: str,
        moment: datetime,
    ) -> PolicyDecision:
        input_hash = sha256_hex(
            f"{fingerprint.action_fingerprint}|{environment}|{','.join(principal.roles)}"
        )
        return PolicyDecision(
            meta=ContractMeta(
                contract_name="PolicyDecision",
                contract_version="1.0.0",
                object_id=decision_id,
                tenant_id=principal.tenant_id,
                created_at=moment,
                producer="ueaf-pdp",
                producer_version=self._producer_version,
                trace_id=fingerprint.trace_id,
            ),
            policy_decision_id=decision_id,
            principal_context_ref=f"principal:{principal.principal_id}",
            action=fingerprint.capability_ref,
            resource=fingerprint.resource,
            environment=environment,
            outcome=outcome,
            reason_codes=reason_codes,
            policy_versions=tuple(sorted({rule.version for rule in self._rules})),
            evaluated_at=moment,
            expires_at=_expiry(moment, 300),
            input_hash=input_hash,
        )


def _resource_matches(pattern: str, resource: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(resource, pattern)


def _expiry(moment: datetime, seconds: int) -> datetime:
    from datetime import timedelta

    return moment + timedelta(seconds=seconds)
