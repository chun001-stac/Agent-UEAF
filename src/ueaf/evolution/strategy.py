"""llm_guided_sparse_mutation 策略（STR-*）。

V1 首个策略：单候选、稀疏、有界输入、在 CI 中确定。当没有新证据或 proposal
会重复已知失败时，不产生任何 proposal（STR-002/003）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ueaf.evolution.objects import (
    MutationPatch,
    MutationRepairLevel,
    StrategyProfile,
)


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    """轻量策略输出；kernel 负责物化规范 proposal。"""

    target_ref: str
    repair_level: MutationRepairLevel
    change_summary: str
    changes: tuple[MutationPatch, ...]


@dataclass(frozen=True, slots=True)
class StrategyInput:
    """有界只读工作集；绝不扫描完整历史（STR-001）。"""

    trigger_ref: str
    run_ref: str
    target_ref: str
    symptom_code: str
    working_set: Mapping[str, Any]
    known_failed_fingerprints: tuple[str, ...] = ()


class SparseMutationStrategy:
    """每次调用产出 0..1 个 proposal 的确定性稀疏策略。"""

    def __init__(self, *, profile: StrategyProfile) -> None:
        self._profile = profile

    def propose(self, inputs: StrategyInput) -> ProposalDraft | None:
        # STR-002：零候选是合法结果。
        candidate_field = inputs.working_set.get("repair_field")
        if not candidate_field or not isinstance(candidate_field, str):
            return None
        # STR-003：不重复无证据的已知失败 proposal。
        proposal_fingerprint = f"{inputs.target_ref}:{candidate_field}"
        if proposal_fingerprint in inputs.known_failed_fingerprints:
            return None
        if inputs.symptom_code.startswith("governance"):
            return None  # R5 治理绝不自动变更（REP-004）

        changes = (
            MutationPatch(
                target_ref=inputs.target_ref,
                path=candidate_field,
                operation="replace",
                before=inputs.working_set.get("before"),
                after=inputs.working_set.get("after"),
                constraint_profile_ref=inputs.working_set.get("constraint_profile_ref"),
            ),
        )
        return ProposalDraft(
            target_ref=inputs.target_ref,
            repair_level="r1",
            change_summary=f"sparse repair of {candidate_field}",
            changes=changes,
        )
