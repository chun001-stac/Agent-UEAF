"""llm_guided_sparse_mutation strategy (STR-*).

V1 first strategy: single-candidate, sparse, bounded-input, deterministic in
CI. Produces zero proposals when there is no new evidence or when the proposal
would repeat a known failure (STR-002/003).
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
    """Lightweight strategy output; the kernel materializes the canonical proposal."""

    target_ref: str
    repair_level: MutationRepairLevel
    change_summary: str
    changes: tuple[MutationPatch, ...]

@dataclass(frozen=True, slots=True)
class StrategyInput:
    """Bounded read-only working set; never scans full history (STR-001)."""

    trigger_ref: str
    run_ref: str
    target_ref: str
    symptom_code: str
    working_set: Mapping[str, Any]
    known_failed_fingerprints: tuple[str, ...] = ()


class SparseMutationStrategy:
    """Deterministic sparse strategy yielding 0..1 proposals per call."""

    def __init__(self, *, profile: StrategyProfile) -> None:
        self._profile = profile

    def propose(self, inputs: StrategyInput) -> ProposalDraft | None:
        # STR-002: zero candidate is a legal outcome.
        candidate_field = inputs.working_set.get("repair_field")
        if not candidate_field or not isinstance(candidate_field, str):
            return None
        # STR-003: no evidence-free repeats of a known failed proposal.
        proposal_fingerprint = f"{inputs.target_ref}:{candidate_field}"
        if proposal_fingerprint in inputs.known_failed_fingerprints:
            return None
        if inputs.symptom_code.startswith("governance"):
            return None  # R5 governance never auto-mutates (REP-004)

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
