"""CON/OBJ/MUT/REP/ETH 缺口测试：CON-010/012、OBJ-002/003、MUT-003、REP-003、ETH-003。

覆盖其余治理切片：复数版本集合的 ReleaseManifest、实现细节不可成为权威的
一致性、护栏目标结果、证据置信度不足判定不确定、越界修改拒绝、基于证据的
升级，以及 R4 供应链门禁。
"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.common.meta import ContractMeta
from ueaf.evolution.gates import (
    EscalationPolicy,
    ObjectiveEvaluator,
    SupplyChainGate,
)
from ueaf.evolution.objects import (
    EvolutionAuthorityPolicy,
    MutationPatch,
    MutationProposal,
    SubjectProfile,
)
from ueaf.evolution.validator import MutationValidator
from ueaf.release.release import ReleaseManifest


def _meta(contract: str, object_id: str) -> ContractMeta:
    return ContractMeta(
        contract_name=contract,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=support.TENANT,
        created_at=support.now(),
        producer="ueaf-test",
        producer_version="0.1.0",
    )


@pytest.mark.test_id("CON-010")
def test_release_manifest_uses_plural_version_sets() -> None:
    manifest = ReleaseManifest(
        meta=_meta("ReleaseManifest", "release:1"),
        release_id="release:1",
        environment="prod",
        lifecycle="approved",
        agent_versions=("agent@1.0.0",),
        prompt_versions=("prompt@2.0.0",),
        schema_versions=("schema@3.0.0",),
        model_route_versions=("route@1.0.0",),
        capability_versions=("cap@1.0.0",),
        adapter_versions=("adapter@1.0.0",),
    )
    # 机器 schema 使用复数版本集合字段，而非单一版本字段。
    for field_name in (
        "agent_versions",
        "prompt_versions",
        "schema_versions",
        "model_route_versions",
        "capability_versions",
        "adapter_versions",
    ):
        assert isinstance(getattr(manifest, field_name), tuple)
    # 没有任何单一的 `version` 字段取代版本集合。
    assert not hasattr(manifest, "version")


@pytest.mark.test_id("CON-012")
def test_implementation_detail_never_becomes_authority() -> None:
    # 内部算法层级 / 判定措辞不得作为权威
    # 对象字段或公开测试 ID 出现。
    authority_field_names = {
        "tier",
        "algorithm_step",
        "internal_judgement",
        "definite_not_executed",
        "not_improved",
    }
    from ueaf.eval.eval import QualityGateDecision
    from ueaf.release.release import ReleaseDecision, ReleaseManifest

    objects = [
        ReleaseDecision,
        ReleaseManifest,
        QualityGateDecision,
    ]
    for cls in objects:
        field_names = {name for name in dir(cls) if not name.startswith("_")}
        assert authority_field_names.isdisjoint(field_names)


@pytest.mark.test_id("OBJ-002")
def test_guardrail_overrides_quality_gain() -> None:
    evaluator = ObjectiveEvaluator()
    # 质量提升但延迟超过护栏 -> 判定为未改进。
    decision = evaluator.evaluate(
        quality_improved=True,
        cost_millis=50,
        latency_millis=250,
        cost_guardrail_millis=100,
        latency_guardrail_millis=100,
        evidence_confidence=0.95,
        confidence_threshold=0.8,
    )
    assert decision.outcome == "not_improved"
    assert "guardrail_exceeded" in decision.reason_codes
    # 在护栏内且质量提升 -> 判定为已改进。
    ok = evaluator.evaluate(
        quality_improved=True,
        cost_millis=50,
        latency_millis=60,
        cost_guardrail_millis=100,
        latency_guardrail_millis=100,
        evidence_confidence=0.95,
        confidence_threshold=0.8,
    )
    assert ok.outcome == "improved"


@pytest.mark.test_id("OBJ-003")
def test_insufficient_evidence_is_inconclusive() -> None:
    evaluator = ObjectiveEvaluator()
    decision = evaluator.evaluate(
        quality_improved=True,
        cost_millis=50,
        latency_millis=60,
        cost_guardrail_millis=100,
        latency_guardrail_millis=100,
        evidence_confidence=0.4,
        confidence_threshold=0.8,
    )
    assert decision.outcome == "inconclusive"
    assert "insufficient_evidence_confidence" in decision.reason_codes


@pytest.mark.test_id("MUT-003")
def test_out_of_range_values_are_rejected() -> None:
    subject = SubjectProfile(
        meta=_meta("SubjectProfile", "subject:1"),
        profile_id="subject:1",
        subject_type="model",
        mutable_fields=("learning_rate",),
        field_ranges={"learning_rate": (0.0, 1.0)},
    )
    authority = EvolutionAuthorityPolicy(
        meta=_meta("EvolutionAuthorityPolicy", "authority:1"),
        evolution_authority_policy_id="authority:1",
    )
    validator = MutationValidator(subject=subject, authority=authority)
    in_range = MutationProposal(
        meta=_meta("MutationProposal", "p:1"),
        mutation_proposal_id="p:1",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="subject:1",
        repair_level="r2",
        change_summary="tune",
        changes=(
            MutationPatch(
                target_ref="subject:1",
                path="learning_rate",
                operation="replace",
                before=0.5,
                after=0.8,
            ),
        ),
    )
    assert validator.validate(in_range).valid
    out_of_range = MutationProposal(
        meta=_meta("MutationProposal", "p:2"),
        mutation_proposal_id="p:2",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="subject:1",
        repair_level="r2",
        change_summary="tune",
        changes=(
            MutationPatch(
                target_ref="subject:1",
                path="learning_rate",
                operation="replace",
                before=0.5,
                after=2.5,
            ),
        ),
    )
    result = validator.validate(out_of_range)
    assert result.status == "rejected"
    assert "out_of_range:learning_rate" in result.reason_codes


@pytest.mark.test_id("REP-003")
def test_escalation_requires_evidence() -> None:
    policy = EscalationPolicy()
    # 仅凭失败绝不会自动扩大范围。
    bare = policy.escalate(current_scope="r1", failure="runtime_error", evidence_refs=())
    assert bare.escalated is False
    assert "escalation_requires_evidence" in bare.reason_codes
    # 有证据时范围可以升级。
    with_evidence = policy.escalate(
        current_scope="r1", failure="runtime_error", evidence_refs=("evidence:1",)
    )
    assert with_evidence.escalated is True
    assert with_evidence.scope == "r1+"


@pytest.mark.test_id("ETH-003")
def test_r4_supply_chain_gate_requires_all_checks() -> None:
    gate = SupplyChainGate()
    complete = gate.evaluate(
        static_checked=True,
        secret_checked=True,
        sbom_checked=True,
        sandbox_checked=True,
        integration_checked=True,
        security_checked=True,
    )
    assert complete.passed
    # 任何缺失的检查都会使门禁失败，并指明缺失的检查项。
    missing = gate.evaluate(
        static_checked=True,
        secret_checked=False,
        sbom_checked=True,
        sandbox_checked=True,
        integration_checked=True,
        security_checked=False,
    )
    assert not missing.passed
    assert set(missing.missing_checks) == {"secret", "security"}
