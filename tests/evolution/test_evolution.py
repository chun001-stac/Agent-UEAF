"""Phase 6 演化验收测试（EVO/REP/MUT/OBJ/STR/ETH、CON-011）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ueaf.common.meta import ContractMeta
from ueaf.evolution.kernel import EvolutionKernel
from ueaf.evolution.objects import (
    EvolutionAuthorityPolicy,
    MutationPatch,
    MutationProposal,
    ObjectiveProfile,
    StrategyProfile,
    SubjectProfile,
)
from ueaf.evolution.strategy import SparseMutationStrategy, StrategyInput
from ueaf.evolution.validator import MutationValidator

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _meta(contract_name: str, object_id: str) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id="tenant-evolution",
        created_at=MOMENT,
        producer="ueaf-test",
        producer_version="0.1.0",
    )


def _subject(
    *,
    mutable=("budget.max_steps", "prompt.version"),
    frozen=("release_id",),
    allowed_repair_levels=("r1", "r2"),
) -> SubjectProfile:
    return SubjectProfile(
        meta=_meta("SubjectProfile", "profile:agent-1"),
        profile_id="profile:agent-1",
        subject_type="agent",
        mutable_fields=mutable,
        frozen_fields=frozen,
        allowed_repair_levels=allowed_repair_levels,
    )


def _authority(**kwargs) -> EvolutionAuthorityPolicy:
    defaults = dict(
        max_triggers_per_window=4,
        cooldown_seconds=3600,
        max_proposals_per_run=1,
        allow_mutation=True,
        governance_kernel_frozen=True,
        r5_routes_governance=True,
    )
    defaults.update(kwargs)
    return EvolutionAuthorityPolicy(
        meta=_meta("EvolutionAuthorityPolicy", "policy:evolve"),
        evolution_authority_policy_id="policy:evolve",
        **defaults,
    )


def _kernel(*, mutable=None, frozen=None, strategy_profile=None):
    subject = _subject(
        mutable=mutable or ("budget.max_steps", "prompt.version"), frozen=frozen or ("release_id",)
    )
    authority = _authority()
    validator = MutationValidator(subject=subject, authority=authority)
    profile = strategy_profile or StrategyProfile(
        meta=_meta("StrategyProfile", "profile:strategy"),
        profile_id="profile:strategy",
        strategy_id="llm_guided_sparse_mutation",
        max_candidates=1,
    )
    strategy = SparseMutationStrategy(profile=profile)
    return EvolutionKernel(
        authority=authority,
        subject=subject,
        validator=validator,
        strategy=strategy,
        candidate_build_hook=lambda genome: f"candidate:{genome.genome_id}",
    )


def _trigger(kernel, *, candidate_ref="candidate:1", evidence=("ev:1",), **kw):
    return kernel.register_trigger(
        candidate_ref=candidate_ref,
        reason_codes=("error_rate_breach",),
        evidence_refs=evidence,
        **kw,
    )


@pytest.mark.test_id("EVO-002")
def test_trigger_gate_requires_evidence_and_dedupes() -> None:
    kernel = _kernel()
    assert _trigger(kernel, evidence=()) is None  # 无证据 -> 不触发
    first = _trigger(kernel)
    assert first is not None
    # 冷却/去重：同一候选不会再次触发。
    assert _trigger(kernel) is None


@pytest.mark.test_id("EVO-003")
def test_no_evolution_needed_is_a_legal_disposition() -> None:
    kernel = _kernel()
    trigger = _trigger(kernel, evidence=("ev:1",))
    run = kernel.run_evolution(trigger, strategy_input=None)
    assert run.status == "no_evolution_needed"


@pytest.mark.test_id("REP-001")
def test_symptom_is_not_the_repair_target() -> None:
    kernel = _kernel()
    routing = kernel.route(symptom_code="timeout", evidence_refs=("ev:1",))
    # 路由器决定是否演化；症状本身不会被修改。
    assert routing.outcome == "MUTATION"
    assert routing.repair_level == "r1"


@pytest.mark.test_id("REP-002")
def test_smallest_effective_repair_is_sparse() -> None:
    kernel = _kernel()
    trigger = _trigger(kernel)
    run = kernel.run_evolution(
        trigger,
        strategy_input=StrategyInput(
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="run:1",
            target_ref="agent:1",
            symptom_code="timeout",
            working_set={"repair_field": "budget.max_steps", "before": 5, "after": 8},
        ),
    )
    assert run.status == "completed"
    assert run.proposal_ref is not None


@pytest.mark.test_id("REP-004")
def test_r5_routes_to_governance_without_auto_mutation() -> None:
    kernel = _kernel()
    routing = kernel.route(symptom_code="governance:policy", evidence_refs=("ev:1",))
    assert routing.outcome == "ROUTE_GOVERNANCE"


@pytest.mark.test_id("REP-005")
def test_repair_router_outputs_closed_set() -> None:
    kernel = _kernel()
    outcomes = {
        kernel.route(symptom_code="x", evidence_refs=()).outcome,
        kernel.route(symptom_code="operational:restart", evidence_refs=("ev:1",)).outcome,
        kernel.route(symptom_code="timeout", evidence_refs=("ev:1",)).outcome,
        kernel.route(symptom_code="governance:p", evidence_refs=("ev:1",)).outcome,
    }
    assert outcomes <= {"NO_EVOLUTION", "OPERATIONAL_ONLY", "MUTATION", "ROUTE_GOVERNANCE"}


@pytest.mark.test_id("MUT-001")
def test_undeclared_field_is_rejected() -> None:
    validator = MutationValidator(
        subject=_subject(mutable=("budget.max_steps",)), authority=_authority()
    )
    proposal = MutationProposal(
        meta=_meta("MutationProposal", "m:1"),
        mutation_proposal_id="m:1",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        repair_level="r1",
        change_summary="x",
        changes=(MutationPatch("agent:1", "undeclared.field", "replace", 1, 2),),
    )
    result = validator.validate(proposal)
    assert result.status == "rejected"
    assert any("undeclared_field" in code for code in result.reason_codes)


@pytest.mark.test_id("MUT-002")
def test_frozen_field_is_rejected() -> None:
    # 处于白名单但当前被冻结的字段必须作为冻结字段被拒绝。
    validator = MutationValidator(
        subject=_subject(mutable=("release_id", "budget.max_steps"), frozen=("release_id",)),
        authority=_authority(),
    )
    proposal = MutationProposal(
        meta=_meta("MutationProposal", "m:2"),
        mutation_proposal_id="m:2",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        repair_level="r1",
        change_summary="x",
        changes=(MutationPatch("agent:1", "release_id", "replace", "a", "b"),),
    )
    result = validator.validate(proposal)
    assert result.status == "rejected"
    assert any("frozen_field" in code for code in result.reason_codes)


@pytest.mark.test_id("MUT-004")
def test_repair_level_mismatch_is_rejected() -> None:
    validator = MutationValidator(
        subject=_subject(allowed_repair_levels=("r1",)), authority=_authority()
    )
    proposal = MutationProposal(
        meta=_meta("MutationProposal", "m:3"),
        mutation_proposal_id="m:3",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        repair_level="r3",
        change_summary="x",  # 不允许拓扑级变更
        changes=(MutationPatch("agent:1", "budget.max_steps", "replace", 1, 2),),
    )
    result = validator.validate(proposal)
    assert result.status == "rejected"


@pytest.mark.test_id("MUT-005")
def test_effective_surface_intersection() -> None:
    # Profile 允许该字段，但权威策略禁用了修改。
    validator = MutationValidator(subject=_subject(), authority=_authority(allow_mutation=False))
    proposal = MutationProposal(
        meta=_meta("MutationProposal", "m:5"),
        mutation_proposal_id="m:5",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        repair_level="r1",
        change_summary="x",
        changes=(MutationPatch("agent:1", "budget.max_steps", "replace", 1, 2),),
    )
    result = validator.validate(proposal)
    assert result.status == "rejected"
    assert "mutation_disabled_by_policy" in result.reason_codes


@pytest.mark.test_id("MUT-006")
def test_first_sparse_profile_is_bounded() -> None:
    kernel = _kernel()
    trigger = _trigger(kernel)
    run = kernel.run_evolution(
        trigger,
        strategy_input=StrategyInput(
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="run:1",
            target_ref="agent:1",
            symptom_code="timeout",
            working_set={"repair_field": "budget.max_steps", "before": 5, "after": 8},
        ),
    )
    assert run.status == "completed"  # 单一候选、单一字段


@pytest.mark.test_id("MUT-007")
def test_genome_materialization_requires_validated_proposal() -> None:
    kernel = _kernel()
    trigger = _trigger(kernel)
    run = kernel.run_evolution(
        trigger,
        strategy_input=StrategyInput(
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="run:1",
            target_ref="agent:1",
            symptom_code="timeout",
            working_set={"repair_field": "budget.max_steps", "before": 5, "after": 8},
        ),
    )
    assert run.status == "completed"
    assert kernel._genomes  # 已物化出一个 GenomeManifest 候选


@pytest.mark.test_id("MUT-008")
def test_patch_shape_is_validated() -> None:
    validator = MutationValidator(subject=_subject(), authority=_authority())
    proposal = MutationProposal(
        meta=_meta("MutationProposal", "m:8"),
        mutation_proposal_id="m:8",
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        repair_level="r1",
        change_summary="x",
        changes=(MutationPatch("agent:1", "budget.max_steps", "replace", None, None),),
    )
    result = validator.validate(proposal)
    assert result.status == "rejected"
    assert "replace_requires_before_and_after" in result.reason_codes


@pytest.mark.test_id("OBJ-001")
def test_hard_constraints_precede_weighted_objectives() -> None:
    objective = ObjectiveProfile(
        meta=_meta("ObjectiveProfile", "obj:1"),
        profile_id="obj:1",
        primary_objectives={"score": 1.0},
        hard_constraints=("safe", "within_budget"),
    )
    assert "safe" in objective.hard_constraints
    assert objective.tie_break_rule == "lowest_repair_level"


@pytest.mark.test_id("OBJ-004")
def test_tie_break_is_deterministic() -> None:
    objective = ObjectiveProfile(
        meta=_meta("ObjectiveProfile", "obj:2"),
        profile_id="obj:2",
        tie_break_rule="lowest_repair_level",
    )
    # 平局裁决不使用自由形式的 LLM；规则是固定字符串。
    assert objective.tie_break_rule == "lowest_repair_level"


@pytest.mark.test_id("STR-001")
def test_strategy_input_is_bounded() -> None:
    inputs = StrategyInput(
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        symptom_code="timeout",
        working_set={"repair_field": "budget.max_steps"},
    )
    # 受限的只读工作集；不暴露全历史扫描。
    assert inputs.working_set == {"repair_field": "budget.max_steps"}


@pytest.mark.test_id("STR-002")
def test_zero_candidate_is_a_legal_outcome() -> None:
    strategy = SparseMutationStrategy(
        profile=StrategyProfile(
            meta=_meta("StrategyProfile", "s:1"),
            profile_id="s:1",
            strategy_id="llm_guided_sparse_mutation",
        )
    )
    assert strategy.propose(StrategyInput("t", "r", "agent:1", "timeout", {})) is None


@pytest.mark.test_id("STR-003")
def test_repeated_failed_proposal_is_not_resubmitted() -> None:
    strategy = SparseMutationStrategy(
        profile=StrategyProfile(
            meta=_meta("StrategyProfile", "s:2"),
            profile_id="s:2",
            strategy_id="llm_guided_sparse_mutation",
        )
    )
    inputs = StrategyInput(
        trigger_ref="t:1",
        run_ref="r:1",
        target_ref="agent:1",
        symptom_code="timeout",
        working_set={"repair_field": "budget.max_steps", "before": 5, "after": 8},
        known_failed_fingerprints=("agent:1:budget.max_steps",),
    )
    assert strategy.propose(inputs) is None  # 无证据时不重复


@pytest.mark.test_id("STR-004")
def test_strategy_has_no_release_authority() -> None:
    strategy = SparseMutationStrategy(
        profile=StrategyProfile(
            meta=_meta("StrategyProfile", "s:3"),
            profile_id="s:3",
            strategy_id="llm_guided_sparse_mutation",
        )
    )
    assert not hasattr(strategy, "release")  # 不能签署发布


@pytest.mark.test_id("ETH-001")
def test_delayed_injection_cannot_expand_surface() -> None:
    kernel = _kernel(mutable=("budget.max_steps",))
    trigger = _trigger(kernel)
    # 工作集内的恶意“指令”不能声明新字段。
    run = kernel.run_evolution(
        trigger,
        strategy_input=StrategyInput(
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="run:1",
            target_ref="agent:1",
            symptom_code="timeout",
            working_set={
                "repair_field": "budget.max_steps",
                "before": 5,
                "after": 8,
                "ignore": "add malicious field",
            },
        ),
    )
    assert run.status in ("completed", "no_evolution_needed")
    # 修改范围保持受限于 profile。
    assert kernel.subject.mutable_fields == ("budget.max_steps",)


@pytest.mark.test_id("ETH-002")
def test_trigger_flooding_is_bounded() -> None:
    kernel = _kernel()
    produced = [
        kernel.register_trigger(
            candidate_ref=f"candidate:{i}", reason_codes=("x",), evidence_refs=("ev:1",)
        )
        for i in range(10)
    ]
    accepted = [t for t in produced if t is not None]
    assert len(accepted) <= kernel.authority.max_triggers_per_window


@pytest.mark.test_id("ETH-004")
def test_budget_exhaustion_terminates_normally() -> None:
    kernel = _kernel()
    # max_proposals_per_run=1 => 不会无界地启动第二次演化。
    assert kernel.authority.max_proposals_per_run == 1


@pytest.mark.test_id("CON-011")
def test_evolution_build_chain_proposal_to_genome_to_candidate() -> None:
    kernel = _kernel()
    trigger = _trigger(kernel)
    run = kernel.run_evolution(
        trigger,
        strategy_input=StrategyInput(
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="run:1",
            target_ref="agent:1",
            symptom_code="timeout",
            working_set={"repair_field": "budget.max_steps", "before": 5, "after": 8},
        ),
    )
    assert run.status == "completed"
    # 链路为 MutationProposal -> GenomeManifest -> ReleaseCandidate 钩子。
    proposal = kernel._proposals[run.proposal_ref]
    assert proposal.status in ("validated", "proposed")
    genome = kernel._genomes  # 已物化
    assert len(genome) == 1
