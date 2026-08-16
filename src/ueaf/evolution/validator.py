"""MutationValidator —— 任何 Genome 物化之前的机器校验。

拒绝未声明/冻结/越界变更，并强制有效变更表面的交集（MUT-001..008）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ueaf.evolution.objects import (
    EvolutionAuthorityPolicy,
    MutationPatch,
    MutationProposal,
    SubjectProfile,
)

ValidationResult = Literal["valid", "rejected"]


@dataclass(frozen=True, slots=True)
class MutationValidation:
    status: ValidationResult
    reason_codes: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status == "valid"


class MutationValidator:
    """依据 Subject Profile + Authority Policy 校验 proposal。"""

    def __init__(self, *, subject: SubjectProfile, authority: EvolutionAuthorityPolicy) -> None:
        self._subject = subject
        self._authority = authority

    def validate(self, proposal: MutationProposal) -> MutationValidation:
        if not self._authority.allow_mutation:
            return MutationValidation("rejected", ("mutation_disabled_by_policy",))

        # MUT-006 稀疏 profile：单一修复目标与有界 patch 字段。
        targets = {patch.target_ref for patch in proposal.changes}
        if len(targets) != 1:
            return MutationValidation("rejected", ("multiple_repair_targets",))
        if proposal.target_ref not in targets:
            return MutationValidation("rejected", ("patch_target_mismatch",))

        # MUT-004 repair-level 不匹配。
        if proposal.repair_level not in self._subject.allowed_repair_levels:
            return MutationValidation(
                "rejected", (f"repair_level_not_allowed:{proposal.repair_level}",)
            )

        declared = set(self._subject.mutable_fields)
        frozen = set(self._subject.frozen_fields)
        if len(proposal.changes) > self._subject.max_patch_fields:
            return MutationValidation("rejected", ("patch_too_wide",))

        for patch in proposal.changes:
            # MUT-002 冻结/治理拒绝优先于 MUT-001。
            if patch.path in frozen:
                return MutationValidation("rejected", (f"frozen_field:{patch.path}",))
            if self._authority.governance_kernel_frozen and patch.target_ref.startswith(
                "governance"
            ):
                return MutationValidation("rejected", ("governance_kernel_frozen",))
            # MUT-001 未声明字段拒绝。
            if patch.path not in declared:
                return MutationValidation("rejected", (f"undeclared_field:{patch.path}",))
            # MUT-003 范围拒绝：越界值会被拒绝。
            range_error = self._range_error(patch)
            if range_error:
                return MutationValidation("rejected", (range_error,))
            # MUT-008 patch 形状。
            shape = self._shape_error(patch)
            if shape:
                return MutationValidation("rejected", (shape,))
        return MutationValidation("valid", ("sparse_and_in_scope",))

    def _range_error(self, patch: MutationPatch) -> str | None:
        bounds = self._subject.field_ranges.get(patch.path)
        if bounds is None or patch.after is None or not isinstance(patch.after, (int, float)):
            return None
        low, high = bounds
        if isinstance(patch.after, bool) or patch.after < low or patch.after > high:
            return f"out_of_range:{patch.path}"
        return None

    @staticmethod
    def _shape_error(patch: MutationPatch) -> str | None:
        if patch.operation not in ("add", "remove", "replace"):
            return "invalid_operation"
        if patch.operation == "replace" and (patch.before is None and patch.after is None):
            return "replace_requires_before_and_after"
        if patch.operation == "remove" and patch.before is None:
            return "remove_requires_before"
        if patch.operation == "add" and patch.after is None:
            return "add_requires_after"
        return None
