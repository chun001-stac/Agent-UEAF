"""Evolution gates: OBJ-002/003, REP-003, ETH-003.

OBJ-002 guardrail: quality gains never override cost/latency guardrails —
"not improved" is a legitimate objective outcome.
OBJ-003 evidence confidence: insufficient business-KPI evidence yields
"inconclusive", never a fabricated improvement.
REP-003 escalation requires evidence: a failure alone never auto-widens scope.
ETH-003 R4 supply chain: R4 generated code must pass static, secret, SBOM,
sandbox, integration and security checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ObjectiveOutcome = Literal["improved", "not_improved", "inconclusive"]


@dataclass(frozen=True, slots=True)
class ObjectiveDecision:
    outcome: ObjectiveOutcome
    reason_codes: tuple[str, ...] = ()


class ObjectiveEvaluator:
    """Hard constraints + guardrails + evidence confidence for an objective."""

    def evaluate(
        self,
        *,
        quality_improved: bool,
        cost_millis: int,
        latency_millis: int,
        cost_guardrail_millis: int,
        latency_guardrail_millis: int,
        evidence_confidence: float,
        confidence_threshold: float,
    ) -> ObjectiveDecision:
        # OBJ-003: insufficient business-KPI evidence -> inconclusive.
        if evidence_confidence < confidence_threshold:
            return ObjectiveDecision("inconclusive", ("insufficient_evidence_confidence",))
        # OBJ-002: quality gains never override cost/latency guardrails.
        if cost_millis > cost_guardrail_millis or latency_millis > latency_guardrail_millis:
            return ObjectiveDecision("not_improved", ("guardrail_exceeded",))
        if not quality_improved:
            return ObjectiveDecision("not_improved", ("no_quality_gain",))
        return ObjectiveDecision("improved", ("improved",))


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    escalated: bool
    scope: str
    reason_codes: tuple[str, ...] = ()


class EscalationPolicy:
    """Scope escalation requires evidence, never a bare failure (REP-003)."""

    def escalate(
        self, *, current_scope: str, failure: str, evidence_refs: tuple[str, ...]
    ) -> EscalationDecision:
        if not evidence_refs:
            return EscalationDecision(False, current_scope, ("escalation_requires_evidence",))
        return EscalationDecision(True, f"{current_scope}+", ("escalated_with_evidence",))


@dataclass(frozen=True, slots=True)
class SupplyChainDecision:
    passed: bool
    missing_checks: tuple[str, ...] = ()


_REQUIRED_R4_CHECKS: tuple[str, ...] = (
    "static",
    "secret",
    "sbom",
    "sandbox",
    "integration",
    "security",
)


class SupplyChainGate:
    """R4 generated code must pass all supply-chain checks (ETH-003)."""

    def evaluate(
        self,
        *,
        static_checked: bool,
        secret_checked: bool,
        sbom_checked: bool,
        sandbox_checked: bool,
        integration_checked: bool,
        security_checked: bool,
    ) -> SupplyChainDecision:
        passed = {
            "static": static_checked,
            "secret": secret_checked,
            "sbom": sbom_checked,
            "sandbox": sandbox_checked,
            "integration": integration_checked,
            "security": security_checked,
        }
        missing = tuple(name for name in _REQUIRED_R4_CHECKS if not passed[name])
        return SupplyChainDecision(not missing, missing)


__all__ = [
    "ObjectiveEvaluator",
    "ObjectiveDecision",
    "EscalationPolicy",
    "EscalationDecision",
    "SupplyChainGate",
    "SupplyChainDecision",
]
