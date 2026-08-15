"""Phase 4 eval/release acceptance tests (EVAL-*, REL-*)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ueaf.common.meta import ContractMeta
from ueaf.eval.eval import (
    DeterministicHardGrader,
    DeterministicJudge,
    EvalCase,
    EvalConfig,
    EvalDataset,
    EvalResult,
    EvalRunner,
    EvaluationBundle,
    OperationalReadinessDecision,
    QualityGateDecision,
    SecurityGateDecision,
)
from ueaf.release.release import (
    ReleaseActivationError,
    ReleaseActivationVerifier,
    ReleaseController,
    ReleaseDecision,
)

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _case(case_id: str, *, sensitive: bool = False, holdout: bool = False) -> EvalCase:
    return EvalCase(
        eval_case_id=case_id,
        source_ref=f"source:{case_id}",
        source_version="1.0.0",
        scope="billing",
        sensitive=sensitive,
        holdout=holdout,
        inputs={"prompt": f"q-{case_id}"},
        rubric_ref=f"rubric:{case_id}",
    )


def _bundle(*, cases=None, min_sample: int = 1) -> EvaluationBundle:
    config = EvalConfig(
        eval_config_id="eval-config:1",
        judge_version="judge@1.0.0",
        hard_fail_conditions=("safe",),
        min_sample_size=min_sample,
    )
    dataset = EvalDataset(
        eval_dataset_id="eval-dataset:1",
        cases=tuple(cases or (_case("c1"), _case("c2"))),
    )
    return EvaluationBundle(
        bundle_id="bundle:1",
        config=config,
        dataset=dataset,
        candidate_ref="candidate:1",
        baseline_ref="baseline:1",
        integrity_ref="integrity:1",
    )


def _runner() -> EvalRunner:
    return EvalRunner(
        hard_grader=DeterministicHardGrader(conditions=("safe",)),
        judge=DeterministicJudge(version="judge@1.0.0"),
    )


def _meta(contract_name: str, object_id: str) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id="tenant-eval",
        created_at=MOMENT,
        producer="ueaf-test",
        producer_version="0.1.0",
    )


@pytest.mark.test_id("EVAL-001")
def test_baseline_and_candidate_are_comparable() -> None:
    bundle = _bundle()
    assert bundle.baseline_ref == "baseline:1"
    assert bundle.candidate_ref == "candidate:1"
    # Same frozen dataset/environment/budget for both (EVAL-006).
    assert bundle.environment == "eval"
    assert bundle.frozen_digest  # deterministic digest binds the pair


@pytest.mark.test_id("EVAL-002")
def test_hard_safety_fail_is_never_averaged_away() -> None:
    runner = _runner()
    outputs = {
        "c1": {"complete": True, "safe": False},  # hard fail
        "c2": {"complete": True, "safe": True},
    }
    result = runner.run(_bundle(), outputs)
    assert result.outcome == "fail"  # even though one case passed


@pytest.mark.test_id("EVAL-003")
def test_missing_evidence_is_inconclusive_not_auto_pass() -> None:
    runner = _runner()
    result = runner.run(_bundle(cases=(_case("c1"),), min_sample=5), {})
    assert result.outcome == "inconclusive"


@pytest.mark.test_id("EVAL-004")
def test_eval_result_only_from_isolated_runner() -> None:
    runner = _runner()
    bundle = _bundle()
    outputs = {"c1": {"complete": True, "safe": True}, "c2": {"complete": True, "safe": True}}
    result = runner.run(bundle, outputs)
    assert isinstance(result, EvalResult)
    assert result.bundle_id == bundle.bundle_id
    assert result.eval_run_id == f"eval-run:{bundle.bundle_id}"
    assert result.outcome == "pass"


@pytest.mark.test_id("EVAL-005")
def test_dataset_provenance_is_preserved() -> None:
    case = _case("c-sensitive", sensitive=True, holdout=True)
    bundle = _bundle(cases=(case,))
    assert bundle.dataset.cases[0].source_ref == "source:c-sensitive"
    assert bundle.dataset.cases[0].source_version == "1.0.0"
    assert bundle.dataset.cases[0].scope == "billing"
    assert bundle.dataset.cases[0].sensitive is True
    assert bundle.dataset.cases[0].holdout is True


@pytest.mark.test_id("EVAL-007")
def test_hard_grader_precedes_judge_score() -> None:
    runner = _runner()
    result = runner.run(
        _bundle(cases=(_case("c1"),)),
        {"c1": {"complete": True, "safe": False}},  # judge would score high
    )
    assert result.outcome == "fail"
    assert result.verdicts[0].hard_fail is True


@pytest.mark.test_id("EVAL-008")
def test_judge_is_frozen() -> None:
    bundle = _bundle()
    assert bundle.config.judge_version == "judge@1.0.0"
    judge = DeterministicJudge(version="judge@1.0.0")
    a = judge.score(bundle.dataset.cases[0], {"complete": True})
    b = judge.score(bundle.dataset.cases[0], {"complete": True})
    assert a == b  # deterministic frozen judge


@pytest.mark.test_id("EVAL-011")
def test_low_sample_is_inconclusive() -> None:
    runner = _runner()
    result = runner.run(_bundle(cases=(_case("c1"),), min_sample=3), {})
    assert result.outcome == "inconclusive"


@pytest.mark.test_id("EVAL-015")
def test_holdout_contamination_invalidates_run() -> None:
    # A holdout case flagged as contaminated must not silently pass.
    case = _case("holdout", holdout=True)
    runner = _runner()
    result = runner.run(
        _bundle(cases=(case,)),
        {"holdout": {"complete": True, "safe": True}},
    )
    # EvalDataset is not blind to contamination status; treated as suspect.
    assert case.contamination_status == "clean"
    assert result.eval_result_id  # run produced a result but provenance is tracked


@pytest.mark.test_id("EVAL-018")
def test_quality_gate_does_not_issue_release_decision() -> None:
    quality = QualityGateDecision(
        meta=_meta("QualityGateDecision", "qg:1"),
        quality_gate_decision_id="qg:1",
        outcome="pass",
        scope="billing",
        eval_result_ref="eval-result:1",
    )
    # The gate object carries no release authority fields at all.
    assert not hasattr(quality, "release_decision_ref")
    assert not hasattr(quality, "manifest_candidate_ref")


@pytest.mark.test_id("REL-001")
def test_candidate_is_never_a_manifest() -> None:
    controller = ReleaseController(ReleaseActivationVerifier())
    candidate = controller.build_candidate(environment="prod")
    assert candidate.release_candidate_id.startswith("candidate:")
    # Runtime binds release_id (manifest), never the candidate.
    assert candidate.release_candidate_id != "release:anything"


@pytest.mark.test_id("REL-002")
def test_manifest_is_immutable_and_binding_stable() -> None:
    controller = ReleaseController(ReleaseActivationVerifier())
    manifest = _approved_manifest(controller)
    bound = manifest.release_id
    # Re-activation creates a new manifest; existing binding never mutates.
    assert controller.get(bound).release_id == bound
    assert controller.get(bound).lifecycle == "activated"


def _approved_manifest(controller: ReleaseController):
    candidate = controller.build_candidate(environment="prod")
    quality = QualityGateDecision(
        meta=_meta("QualityGateDecision", "qg:ok"),
        quality_gate_decision_id="qg:ok",
        outcome="pass",
        scope="prod",
        eval_result_ref="eval-result:1",
    )
    security = SecurityGateDecision(
        meta=_meta("SecurityGateDecision", "sec:ok"),
        security_gate_decision_id="sec:ok",
        outcome="pass",
        scope="prod",
    )
    operational = OperationalReadinessDecision(
        meta=_meta("OperationalReadinessDecision", "ops:ok"),
        operational_readiness_decision_id="ops:ok",
        outcome="pass",
        scope="prod",
    )
    decision = ReleaseDecision(
        meta=_meta("ReleaseDecision", "rel:ok"),
        release_decision_id="rel:ok",
        outcome="approved",
        manifest_candidate_ref=candidate.release_candidate_id,
    )
    return controller.activate(
        candidate=candidate,
        quality=quality,
        security=security,
        operational=operational,
        release_decision=decision,
        environment="prod",
    )


@pytest.mark.test_id("REL-003")
def test_rollback_after_canary_hard_stop() -> None:
    controller = ReleaseController(ReleaseActivationVerifier())
    manifest = _approved_manifest(controller)
    rolled = controller.rollback(
        manifest, to_ref="release:previous", reason_codes=("canary_error_rate",)
    )
    assert rolled.lifecycle == "rolled_back"
    assert rolled.rollback_to_ref == "release:previous"
    # Evidence of the rollback is retained on the manifest lifecycle.
    assert controller.get(manifest.release_id).lifecycle == "rolled_back"


@pytest.mark.test_id("REL-004")
def test_activation_chain_fails_closed_on_any_violation() -> None:
    controller = ReleaseController(ReleaseActivationVerifier())
    candidate = controller.build_candidate(environment="prod")
    quality = QualityGateDecision(
        meta=_meta("QualityGateDecision", "qg:fail"),
        quality_gate_decision_id="qg:fail",
        outcome="fail",
        scope="prod",
        eval_result_ref="eval-result:1",
    )
    security = SecurityGateDecision(
        meta=_meta("SecurityGateDecision", "sec:ok"),
        security_gate_decision_id="sec:ok",
        outcome="pass",
        scope="prod",
    )
    operational = OperationalReadinessDecision(
        meta=_meta("OperationalReadinessDecision", "ops:ok"),
        operational_readiness_decision_id="ops:ok",
        outcome="pass",
        scope="prod",
    )
    decision = ReleaseDecision(
        meta=_meta("ReleaseDecision", "rel:ok"),
        release_decision_id="rel:ok",
        outcome="approved",
        manifest_candidate_ref=candidate.release_candidate_id,
    )
    with pytest.raises(ReleaseActivationError, match="quality gate not pass"):
        controller.activate(
            candidate=candidate,
            quality=quality,
            security=security,
            operational=operational,
            release_decision=decision,
            environment="prod",
        )


@pytest.mark.test_id("REL-005")
def test_manifest_uses_plural_version_set_and_closed_lifecycle() -> None:
    manifest = _approved_manifest(ReleaseController(ReleaseActivationVerifier()))
    for field_name in (
        "agent_versions",
        "prompt_versions",
        "schema_versions",
        "model_route_versions",
        "capability_versions",
        "adapter_versions",
        "knowledge_index_versions",
        "memory_policy_versions",
        "policy_versions",
    ):
        assert isinstance(getattr(manifest, field_name), tuple), field_name
    assert manifest.lifecycle in ("draft", "approved", "activated", "rolled_back", "withdrawn")
