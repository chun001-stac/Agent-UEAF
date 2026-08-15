"""Read-only Eval vertical slice (Phase 4, implementation spec 08 §8.1).

EvalResult is only produced from a frozen ``EvaluationBundle`` by an isolated
runner — never by a production request. Quality/Security/Operational gates are
separate from ``ReleaseDecision`` authority (EVAL-018).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.common.meta import ContractMeta

GateOutcome = Literal["pass", "fail", "inconclusive"]
EvalOutcome = Literal["pass", "fail", "inconclusive"]

_GATE_OUTCOMES: frozenset[str] = frozenset({"pass", "fail", "inconclusive"})


@dataclass(frozen=True, slots=True)
class EvalCase:
    """A single evaluation case with provenance and sensitive status (EVAL-005)."""

    eval_case_id: str
    source_ref: str
    source_version: str
    scope: str
    sensitive: bool
    inputs: Mapping[str, object]
    rubric_ref: str | None = None
    holdout: bool = False
    contamination_status: Literal["clean", "suspected", "contaminated"] = "clean"


@dataclass(frozen=True, slots=True)
class EvalDataset:
    eval_dataset_id: str
    cases: tuple[EvalCase, ...] = ()
    version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class EvalConfig:
    eval_config_id: str
    judge_version: str
    judge_sampling_seed: int | None = None
    judge_schema_ref: str | None = None
    hard_fail_conditions: tuple[str, ...] = ()
    min_sample_size: int = 1
    judge_disagreement_threshold: float = 0.2
    cost_limit_millis: int | None = None
    latency_limit_millis: int | None = None


@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    """Frozen inputs for an isolated EvalRun (EVAL-004/006)."""

    bundle_id: str
    config: EvalConfig
    dataset: EvalDataset
    candidate_ref: str
    baseline_ref: str
    environment: str = "eval"
    integrity_ref: str | None = None

    @property
    def frozen_digest(self) -> str:
        return sha256_hex(
            f"{self.bundle_id}|{self.config.eval_config_id}|{self.dataset.eval_dataset_id}"
            f"|{self.candidate_ref}|{self.baseline_ref}|{self.environment}"
        )


@dataclass(frozen=True, slots=True)
class EvalRun:
    """Isolated evaluation run; source of EvalResult (EVAL-004)."""

    meta: ContractMeta
    eval_run_id: str
    bundle_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "completed", "invalid"] = "running"


@dataclass(frozen=True, slots=True)
class CaseVerdict:
    eval_case_id: str
    hard_fail: bool
    judge_score: float
    passed: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalResult:
    meta: ContractMeta
    eval_result_id: str
    eval_run_id: str
    bundle_id: str
    candidate_ref: str
    baseline_ref: str
    metric_summary: Mapping[str, object]
    verdicts: tuple[CaseVerdict, ...] = ()
    outcome: Literal["pass", "fail", "inconclusive"] = "inconclusive"
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QualityGateDecision:
    """Quality gate only — never a ReleaseDecision (EVAL-018)."""

    meta: ContractMeta
    quality_gate_decision_id: str
    outcome: GateOutcome
    scope: str
    eval_result_ref: str
    evidence_refs: tuple[str, ...] = ()
    expires_at: datetime | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in _GATE_OUTCOMES:
            raise ValueError(f"invalid QualityGateDecision outcome {self.outcome!r}")


@dataclass(frozen=True, slots=True)
class SecurityGateDecision:
    meta: ContractMeta
    security_gate_decision_id: str
    outcome: GateOutcome
    scope: str
    evidence_refs: tuple[str, ...] = ()
    expires_at: datetime | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in _GATE_OUTCOMES:
            raise ValueError(f"invalid SecurityGateDecision outcome {self.outcome!r}")


@dataclass(frozen=True, slots=True)
class OperationalReadinessDecision:
    meta: ContractMeta
    operational_readiness_decision_id: str
    outcome: GateOutcome
    scope: str
    evidence_refs: tuple[str, ...] = ()
    expires_at: datetime | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in _GATE_OUTCOMES:
            raise ValueError(f"invalid OperationalReadinessDecision outcome {self.outcome!r}")


@dataclass(frozen=True, slots=True)
class HardGraderResult:
    """Deterministic hard grader: structural/safety checks before any judge."""

    failed: bool
    reason_codes: tuple[str, ...] = ()


class DeterministicHardGrader:
    """Hard grader evaluated before judge scores (EVAL-002/007)."""

    def __init__(self, *, conditions: tuple[str, ...] = ()) -> None:
        self._conditions = conditions

    def evaluate(self, case: EvalCase, candidate_output: Mapping[str, object]) -> HardGraderResult:
        failed_conditions = []
        for condition in self._conditions:
            if (
                condition not in candidate_output
                or candidate_output[condition] in (None, "", False)
            ):
                failed_conditions.append(condition)
        return HardGraderResult(bool(failed_conditions), tuple(failed_conditions))


class DeterministicJudge:
    """Deterministic judge used in CI (frozen judge prompt/model/schema)."""

    def __init__(self, *, version: str, seed: int = 0) -> None:
        self._version = version
        self._seed = seed

    def score(self, case: EvalCase, candidate_output: Mapping[str, object]) -> float:
        # Deterministic score: rubric-compliant outputs score higher.
        base = 1.0 if candidate_output.get("complete") else 0.0
        return base


class EvalRunner:
    """Isolated runner: frozen bundle -> per-case verdicts -> EvalResult."""

    def __init__(self, *, hard_grader: DeterministicHardGrader, judge: DeterministicJudge) -> None:
        self._hard = hard_grader
        self._judge = judge

    def run(
        self,
        bundle: EvaluationBundle,
        candidate_outputs: Mapping[str, Mapping[str, object]],
    ) -> EvalResult:
        if len(bundle.dataset.cases) < bundle.config.min_sample_size:
            return self._result(
                bundle, [], outcome="inconclusive", metric={"low_sample": 1.0}
            )
        verdicts: list[CaseVerdict] = []
        hard_fails = 0
        passed = 0
        for case in bundle.dataset.cases:
            output = candidate_outputs.get(case.eval_case_id, {})
            hard = self._hard.evaluate(case, output)
            score = self._judge.score(case, output)
            ok = (not hard.failed) and score > 0
            if hard.failed:
                hard_fails += 1
            if ok:
                passed += 1
            verdicts.append(CaseVerdict(
                eval_case_id=case.eval_case_id,
                hard_fail=hard.failed,
                judge_score=score,
                passed=ok,
                reason_codes=hard.reason_codes,
            ))
        if hard_fails:
            return self._result(
                bundle, verdicts, outcome="fail", metric={"hard_fails": float(hard_fails)}
            )
        total = len(verdicts)
        pass_rate = passed / total if total else 0.0
        outcome: EvalOutcome
        if pass_rate >= 0.8:
            outcome = "pass"
        elif pass_rate >= 0.4:
            outcome = "inconclusive"
        else:
            outcome = "fail"
        return self._result(
            bundle, verdicts, outcome=outcome, metric={"pass_rate": pass_rate}
        )

    def _result(
        self,
        bundle: EvaluationBundle,
        verdicts: list[CaseVerdict],
        *,
        outcome: EvalOutcome,
        metric: Mapping[str, object],
    ) -> EvalResult:
        result_id = new_object_id("eval-result")
        return EvalResult(
            meta=ContractMeta(
                contract_name="EvalResult",
                contract_version="1.0.0",
                object_id=result_id,
                tenant_id="tenant-eval",
                created_at=datetime.now(UTC),
                producer="ueaf-eval",
                producer_version="0.1.0",
            ),
            eval_result_id=result_id,
            eval_run_id=f"eval-run:{bundle.bundle_id}",
            bundle_id=bundle.bundle_id,
            candidate_ref=bundle.candidate_ref,
            baseline_ref=bundle.baseline_ref,
            metric_summary=metric,
            verdicts=tuple(verdicts),
            outcome=outcome,
            evidence_refs=(bundle.integrity_ref,) if bundle.integrity_ref else (),
        )
