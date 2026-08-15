"""Eval gate gap tests: EVAL-006/009/010/012/013/014/016/017.

Covers the eval slices missing from the reference implementation: baseline
equivalence, judge disagreement, judge calibration degradation, critical-slice
regression, cost/latency guardrails, authorized reference access, judge
side-channel contamination, and attempt-history preservation.
"""

from __future__ import annotations

import pytest

from ueaf.eval.gates import (
    AttemptHistory,
    AttemptRecord,
    BaselineEquivalenceCheck,
    CostLatencyGuardrail,
    JudgeCalibration,
    JudgeDisagreementGate,
    ReferenceAccessPolicy,
    SideChannelDetector,
    SliceRegressionGate,
)


@pytest.mark.test_id("EVAL-006")
def test_baseline_equivalence_requires_same_fixtures() -> None:
    check = BaselineEquivalenceCheck()
    same = check.evaluate(
        candidate_dataset="d:1",
        baseline_dataset="d:1",
        candidate_environment="eval",
        baseline_environment="eval",
        candidate_budget="b:1",
        baseline_budget="b:1",
        candidate_capability="c:1",
        baseline_capability="c:1",
        candidate_tool_fixture="t:1",
        baseline_tool_fixture="t:1",
    )
    assert same.equivalent
    # Any differing fixture is explicitly recorded (never a silent candidate delta).
    diff = check.evaluate(
        candidate_dataset="d:2",
        baseline_dataset="d:1",
        candidate_environment="eval",
        baseline_environment="eval",
        candidate_budget="b:1",
        baseline_budget="b:1",
        candidate_capability="c:1",
        baseline_capability="c:1",
        candidate_tool_fixture="t:1",
        baseline_tool_fixture="t:1",
    )
    assert not diff.equivalent
    assert "dataset_differs" in diff.reason_codes


@pytest.mark.test_id("EVAL-009")
def test_judge_disagreement_requires_review_not_average_pass() -> None:
    gate = JudgeDisagreementGate()
    agreed = gate.evaluate((0.9, 0.92, 0.88), threshold=0.2)
    assert agreed.outcome == "pass"
    # Judges diverge beyond threshold: inconclusive, never averaged to pass.
    disputed = gate.evaluate((0.95, 0.4, 0.9), threshold=0.2)
    assert disputed.outcome == "inconclusive"
    assert "judge_disagreement_above_threshold" in disputed.reason_codes
    assert disputed.spread == pytest.approx(0.55)


@pytest.mark.test_id("EVAL-010")
def test_calibration_degradation_disables_judge_as_sole_gate() -> None:
    calibration = JudgeCalibration()
    reliable = calibration.evaluate(agreement_rate=0.92, threshold=0.85)
    assert reliable.reliable
    degraded = calibration.evaluate(agreement_rate=0.6, threshold=0.85)
    assert not degraded.reliable
    assert "calibration_below_threshold" in degraded.reason_codes


@pytest.mark.test_id("EVAL-012")
def test_critical_slice_regression_is_not_averaged_away() -> None:
    gate = SliceRegressionGate()
    # Overall improvement cannot offset a critical-slice regression.
    decision = gate.evaluate(
        overall_improved=True,
        slice_regressions=(("fraud_detection", 0.35),),
        hard_threshold=0.2,
    )
    assert decision.outcome == "fail"
    assert "critical_slice_regression:fraud_detection" in decision.reason_codes
    # Small deltas within threshold pass.
    ok = gate.evaluate(
        overall_improved=True,
        slice_regressions=(("latency", 0.05),),
        hard_threshold=0.2,
    )
    assert ok.outcome == "pass"


@pytest.mark.test_id("EVAL-013")
def test_cost_latency_guardrail_not_overridden_by_quality() -> None:
    guardrail = CostLatencyGuardrail()
    within = guardrail.evaluate(
        quality_improved=True,
        cost_millis=50,
        latency_millis=80,
        cost_limit_millis=100,
        latency_limit_millis=100,
    )
    assert within.outcome == "pass"
    # Quality improved but cost exceeds guardrail -> fail; no new state invented.
    over = guardrail.evaluate(
        quality_improved=True,
        cost_millis=250,
        latency_millis=80,
        cost_limit_millis=100,
        latency_limit_millis=100,
    )
    assert over.outcome == "fail"
    assert "cost_guardrail_exceeded" in over.reason_codes
    assert over.outcome in ("pass", "fail", "inconclusive")


@pytest.mark.test_id("EVAL-014")
def test_reference_access_is_frozen_contract_only() -> None:
    policy = ReferenceAccessPolicy(frozen_contract_refs=("grader:1",))
    assert policy.authorize("grader:1", "reference:rubric").authorized
    denied = policy.authorize("grader:unfrozen", "reference:rubric")
    assert not denied.authorized
    assert "contract_not_frozen" in denied.reason_codes
    # Reference content must not reflow into the candidate.
    reflow = policy.assert_no_reflow("the reference:rubric answer is 42", "reference:rubric")
    assert not reflow.authorized
    assert policy.assert_no_reflow("independent answer", "reference:rubric").authorized


@pytest.mark.test_id("EVAL-016")
def test_judge_side_channel_contamination_invalidates_result() -> None:
    detector = SideChannelDetector()
    assert not detector.detect(("case_inputs", "rubric")).contaminated
    contaminated = detector.detect(("case_inputs", "hidden_labels", "policy_snapshot"))
    assert contaminated.contaminated
    assert "side_channel:hidden_labels" in contaminated.reason_codes
    assert "side_channel:policy_snapshot" in contaminated.reason_codes


@pytest.mark.test_id("EVAL-017")
def test_attempt_history_preserves_all_attempts() -> None:
    history = AttemptHistory()
    history.record(AttemptRecord(attempt_id="a:1", eval_case_id="c:1", outcome="fail", score=0.2))
    history.record(AttemptRecord(attempt_id="a:2", eval_case_id="c:1", outcome="pass", score=0.9))
    attempts = history.attempts()
    assert [a.attempt_id for a in attempts] == ["a:1", "a:2"]
    # Selective deletion of an unfavorable attempt is forbidden (EVAL-017).
    with pytest.raises(ValueError, match="selective deletion"):
        history.delete("a:1")
    assert len(history.attempts()) == 2
