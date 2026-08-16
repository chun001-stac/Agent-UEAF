"""Evolution 门：OBJ-002/003、REP-003、ETH-003。

OBJ-002 护栏：质量提升绝不覆盖成本/延迟护栏——“未改善”是合法的目标结果。
OBJ-003 证据置信度：业务 KPI 证据不足时产生“inconclusive”，绝不虚构改善。
REP-003 升级需要证据：仅凭失败绝不自动扩大范围。
ETH-003 R4 供应链：R4 生成的代码必须通过静态、密钥、SBOM、沙箱、
集成与安全检查。
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
    """针对目标的硬约束 + 护栏 + 证据置信度。"""

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
        # OBJ-003：业务 KPI 证据不足 -> inconclusive。
        if evidence_confidence < confidence_threshold:
            return ObjectiveDecision("inconclusive", ("insufficient_evidence_confidence",))
        # OBJ-002：质量提升绝不覆盖成本/延迟护栏。
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
    """范围升级需要证据，绝不仅凭失败（REP-003）。"""

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
    """R4 生成的代码必须通过全部供应链检查（ETH-003）。"""

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
