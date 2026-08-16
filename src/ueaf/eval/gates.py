"""评测门控切片：EVAL-006/009/010/012/013/014/016/017。

每个门控都基于确定性输入产生判定；它们都不创建新的公共结果状态（例如 ``not_improved``），
而是复用 ``pass|fail|inconclusive``（EVAL-013）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GateLikeOutcome = Literal["pass", "fail", "inconclusive"]


# ---- EVAL-006 基线等价性 ---------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineEquivalenceDecision:
    equivalent: bool
    reason_codes: tuple[str, ...] = ()


class BaselineEquivalenceCheck:
    """Baseline/Candidate 必须共享数据集/环境/预算/能力/工具夹具。"""

    def evaluate(
        self,
        *,
        candidate_dataset: str,
        baseline_dataset: str,
        candidate_environment: str,
        baseline_environment: str,
        candidate_budget: str,
        baseline_budget: str,
        candidate_capability: str,
        baseline_capability: str,
        candidate_tool_fixture: str,
        baseline_tool_fixture: str,
    ) -> BaselineEquivalenceDecision:
        reasons: list[str] = []
        if candidate_dataset != baseline_dataset:
            reasons.append("dataset_differs")
        if candidate_environment != baseline_environment:
            reasons.append("environment_differs")
        if candidate_budget != baseline_budget:
            reasons.append("budget_differs")
        if candidate_capability != baseline_capability:
            reasons.append("capability_differs")
        if candidate_tool_fixture != baseline_tool_fixture:
            reasons.append("tool_fixture_differs")
        return BaselineEquivalenceDecision(not reasons, tuple(reasons))


# ---- EVAL-009 评测分歧 -----------------------------------------


@dataclass(frozen=True, slots=True)
class DisagreementDecision:
    outcome: GateLikeOutcome
    spread: float
    reason_codes: tuple[str, ...] = ()


class JudgeDisagreementGate:
    """多次/多个评测器得分差超过阈值时需要复核（EVAL-009）。"""

    def evaluate(self, scores: tuple[float, ...], threshold: float) -> DisagreementDecision:
        if not scores:
            return DisagreementDecision("inconclusive", 0.0, ("no_judge_scores",))
        spread = max(scores) - min(scores)
        if spread > threshold:
            return DisagreementDecision(
                "inconclusive", spread, ("judge_disagreement_above_threshold",)
            )
        return DisagreementDecision("pass", spread, ("agreement",))


# ---- EVAL-010 评测校准 -------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibrationDecision:
    reliable: bool
    agreement_rate: float
    reason_codes: tuple[str, ...] = ()


class JudgeCalibration:
    """低于一致率阈值的评测器不能作为质量门控的唯一依据。"""

    def evaluate(self, agreement_rate: float, threshold: float) -> CalibrationDecision:
        if agreement_rate < threshold:
            return CalibrationDecision(False, agreement_rate, ("calibration_below_threshold",))
        return CalibrationDecision(True, agreement_rate, ("calibrated",))


# ---- EVAL-012 关键切片回归 -----------------------------------


@dataclass(frozen=True, slots=True)
class SliceRegressionDecision:
    outcome: GateLikeOutcome
    reason_codes: tuple[str, ...] = ()


class SliceRegressionGate:
    """关键切片回归超过硬阈值时门控失败。"""

    def evaluate(
        self,
        *,
        overall_improved: bool,
        slice_regressions: tuple[tuple[str, float], ...],
        hard_threshold: float,
    ) -> SliceRegressionDecision:
        bad_slices = [name for name, delta in slice_regressions if delta > hard_threshold]
        if bad_slices:
            return SliceRegressionDecision(
                "fail", (f"critical_slice_regression:{','.join(bad_slices)}",)
            )
        return SliceRegressionDecision("pass", ("no_critical_slice_regression",))


# ---- EVAL-013 成本/延迟护栏 ------------------------------------


@dataclass(frozen=True, slots=True)
class CostLatencyDecision:
    outcome: GateLikeOutcome
    reason_codes: tuple[str, ...] = ()


class CostLatencyGuardrail:
    """质量提升绝不能覆盖成本/延迟护栏（EVAL-013）。"""

    def evaluate(
        self,
        *,
        quality_improved: bool,
        cost_millis: int,
        latency_millis: int,
        cost_limit_millis: int | None,
        latency_limit_millis: int | None,
    ) -> CostLatencyDecision:
        reasons: list[str] = []
        if cost_limit_millis is not None and cost_millis > cost_limit_millis:
            reasons.append("cost_guardrail_exceeded")
        if latency_limit_millis is not None and latency_millis > latency_limit_millis:
            reasons.append("latency_guardrail_exceeded")
        if reasons:
            # 复用 fail/conditional；绝不发明新的结果状态。
            return CostLatencyDecision("fail", tuple(reasons))
        return CostLatencyDecision("pass", ("within_guardrails",))


# ---- EVAL-014 授权参考访问 ---------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceAccessDecision:
    authorized: bool
    reason_codes: tuple[str, ...] = ()


class ReferenceAccessPolicy:
    """只有冻结的 Grader/Judge 合约才能读取评分标准/参考答案。"""

    def __init__(self, *, frozen_contract_refs: tuple[str, ...]) -> None:
        self._frozen = frozenset(frozen_contract_refs)

    def authorize(self, actor_contract_ref: str, reference_ref: str) -> ReferenceAccessDecision:
        if actor_contract_ref not in self._frozen:
            return ReferenceAccessDecision(False, ("contract_not_frozen",))
        return ReferenceAccessDecision(True, ("authorized",))

    def assert_no_reflow(
        self, candidate_content: str, reference_ref: str
    ) -> ReferenceAccessDecision:
        # 参考内容不得回流到候选输出中。
        if reference_ref in candidate_content:
            return ReferenceAccessDecision(False, ("reference_reflowed_to_candidate",))
        return ReferenceAccessDecision(True, ("no_reflow",))


# ---- EVAL-016 侧信道污染 -----------------------------------


@dataclass(frozen=True, slots=True)
class ContaminationDecision:
    contaminated: bool
    reason_codes: tuple[str, ...] = ()


class SideChannelDetector:
    """通过未冻结的侧信道提供的评测输入会使结果失效。"""

    ALLOWED_CHANNELS: frozenset[str] = frozenset(
        {"case_inputs", "rubric", "frozen_reference", "judge_prompt"}
    )

    def detect(self, observed_channels: tuple[str, ...]) -> ContaminationDecision:
        bad = [channel for channel in observed_channels if channel not in self.ALLOWED_CHANNELS]
        if bad:
            return ContaminationDecision(True, tuple(f"side_channel:{channel}" for channel in bad))
        return ContaminationDecision(False, ("clean",))


# ---- EVAL-017 尝试历史保留 ---------------------------------


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    eval_case_id: str
    outcome: str
    score: float


class AttemptHistory:
    """所有尝试都会被保留以供证据聚合（EVAL-017）。"""

    def __init__(self) -> None:
        self._attempts: dict[str, AttemptRecord] = {}

    def record(self, attempt: AttemptRecord) -> AttemptRecord:
        self._attempts[attempt.attempt_id] = attempt
        return attempt

    def attempts(self) -> tuple[AttemptRecord, ...]:
        return tuple(self._attempts.values())

    def delete(self, attempt_id: str) -> None:
        # 选择性删除不利尝试会被拒绝（EVAL-017）。
        raise ValueError(f"attempt {attempt_id} is preserved; selective deletion is forbidden")


__all__ = [
    "BaselineEquivalenceCheck",
    "BaselineEquivalenceDecision",
    "JudgeDisagreementGate",
    "DisagreementDecision",
    "JudgeCalibration",
    "CalibrationDecision",
    "SliceRegressionGate",
    "SliceRegressionDecision",
    "CostLatencyGuardrail",
    "CostLatencyDecision",
    "ReferenceAccessPolicy",
    "ReferenceAccessDecision",
    "SideChannelDetector",
    "ContaminationDecision",
    "AttemptHistory",
    "AttemptRecord",
]
