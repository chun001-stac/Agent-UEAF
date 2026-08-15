"""Evolution canonical objects (V1 strict scope, AGENTS.md §3).

Only these five canonical objects may exist:
EvolutionTrigger / EvolutionRun / GenomeManifest / MutationProposal /
EvolutionAuthorityPolicy. RepairLevel concepts are R0..R5, wire r0..r5, and
MutationProposal.repair_level accepts only r1..r4.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta

RepairLevel = Literal["r0", "r1", "r2", "r3", "r4", "r5"]
MutationRepairLevel = Literal["r1", "r2", "r3", "r4"]
RepairRouterOutcome = Literal["NO_EVOLUTION", "OPERATIONAL_ONLY", "MUTATION", "ROUTE_GOVERNANCE"]

_MUTATION_REPAIR_LEVELS: frozenset[str] = frozenset({"r1", "r2", "r3", "r4"})


@dataclass(frozen=True, slots=True)
class EvolutionTrigger:
    meta: ContractMeta
    evolution_trigger_id: str
    candidate_ref: str
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    cooldown_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.evolution_trigger_id != self.meta.object_id:
            raise ValueError("EvolutionTrigger.meta.object_id must equal id")
        if not self.reason_codes:
            raise ValueError("EvolutionTrigger.reason_codes MUST be non-empty")


@dataclass(frozen=True, slots=True)
class EvolutionRun:
    meta: ContractMeta
    evolution_run_id: str
    trigger_ref: str
    strategy_ref: str
    status: Literal["pending", "running", "completed", "no_evolution_needed", "aborted"] = "pending"
    proposal_ref: str | None = None
    candidate_ref: str | None = None

    def __post_init__(self) -> None:
        if self.evolution_run_id != self.meta.object_id:
            raise ValueError("EvolutionRun.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class MutationPatch:
    """One structural change in a MutationProposal (patch shape, MUT-008)."""

    target_ref: str
    path: str
    operation: Literal["add", "remove", "replace"]
    before: object | None = None
    after: object | None = None
    constraint_profile_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MutationProposal:
    meta: ContractMeta
    mutation_proposal_id: str
    trigger_ref: str
    run_ref: str
    target_ref: str
    repair_level: MutationRepairLevel
    change_summary: str
    changes: tuple[MutationPatch, ...] = ()
    status: Literal["proposed", "validated", "rejected", "materialized"] = "proposed"

    def __post_init__(self) -> None:
        if self.mutation_proposal_id != self.meta.object_id:
            raise ValueError("MutationProposal.meta.object_id must equal id")
        if self.repair_level not in _MUTATION_REPAIR_LEVELS:
            raise ValueError("MutationProposal.repair_level must be r1..r4 (MUT-004)")
        if not self.changes:
            raise ValueError("MutationProposal.changes must be non-empty (MUT-008)")


@dataclass(frozen=True, slots=True)
class GenomeManifest:
    """Immutable genome candidate produced by machine validation (MUT-007)."""

    meta: ContractMeta
    genome_id: str
    proposal_ref: str
    target_ref: str
    changes: tuple[MutationPatch, ...] = ()
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        if self.genome_id != self.meta.object_id:
            raise ValueError("GenomeManifest.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class EvolutionAuthorityPolicy:
    """Governance contract for the evolution kernel (never recursively mutated)."""

    meta: ContractMeta
    evolution_authority_policy_id: str
    max_triggers_per_window: int = 4
    cooldown_seconds: int = 3600
    max_proposals_per_run: int = 1
    allow_mutation: bool = True
    governance_kernel_frozen: bool = True
    r5_routes_governance: bool = True

    def __post_init__(self) -> None:
        if self.evolution_authority_policy_id != self.meta.object_id:
            raise ValueError("EvolutionAuthorityPolicy.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class SubjectProfile:
    """Declares the mutable surface for one subject (MUT-005/006)."""

    meta: ContractMeta
    profile_id: str
    subject_type: str
    mutable_fields: tuple[str, ...] = ()
    frozen_fields: tuple[str, ...] = ()
    allowed_repair_levels: tuple[MutationRepairLevel, ...] = ("r1", "r2")
    max_patch_fields: int = 2

    def __post_init__(self) -> None:
        if self.profile_id != self.meta.object_id:
            raise ValueError("SubjectProfile.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class ObjectiveProfile:
    """Hard constraints first, then weighted objectives, then tie-break (OBJ-*)."""

    meta: ContractMeta
    profile_id: str
    primary_objectives: Mapping[str, float] = field(default_factory=dict)
    hard_constraints: tuple[str, ...] = ()
    guardrails: tuple[str, ...] = ()
    tie_break_rule: str = "lowest_repair_level"


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    meta: ContractMeta
    profile_id: str
    strategy_id: str
    bounded_input: bool = True
    max_candidates: int = 1
    max_proposal_budget: int = 3

    def __post_init__(self) -> None:
        if self.strategy_id != "llm_guided_sparse_mutation":
            raise ValueError("V1 supports only the llm_guided_sparse_mutation strategy (STR-*)")
