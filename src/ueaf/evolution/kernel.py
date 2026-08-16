"""Evolution Kernel（V1）—— 垂直切片。

触发门（EVO-002）-> RepairRouter（REP-001..005）-> 稀疏策略（STR-*）
-> MutationValidator（MUT-*）-> GenomeManifest 物化（MUT-007）
-> 候选构建钩子（CON-011）。治理 kernel 绝不递归变更，
R5 路由到独立治理（REP-004）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ueaf.common.identifiers import new_object_id
from ueaf.common.meta import ContractMeta
from ueaf.evolution.objects import (
    EvolutionAuthorityPolicy,
    EvolutionRun,
    EvolutionTrigger,
    GenomeManifest,
    MutationProposal,
    MutationRepairLevel,
    RepairRouterOutcome,
    SubjectProfile,
)
from ueaf.evolution.strategy import ProposalDraft, SparseMutationStrategy, StrategyInput
from ueaf.evolution.validator import MutationValidator

CandidateBuildHook = Callable[[GenomeManifest], str]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RepairRouting:
    outcome: RepairRouterOutcome
    reason_codes: tuple[str, ...] = ()
    repair_level: MutationRepairLevel | None = None


@dataclass(slots=True)
class EvolutionKernel:
    """小型受控的 evolution kernel（V1）。"""

    authority: EvolutionAuthorityPolicy
    subject: SubjectProfile
    validator: MutationValidator
    strategy: SparseMutationStrategy
    candidate_build_hook: CandidateBuildHook | None = None
    _now: Callable[[], datetime] = field(default_factory=lambda: _utcnow)
    _triggers: dict[str, EvolutionTrigger] = field(default_factory=dict)
    _runs: dict[str, EvolutionRun] = field(default_factory=dict)
    _proposals: dict[str, MutationProposal] = field(default_factory=dict)
    _genomes: dict[str, GenomeManifest] = field(default_factory=dict)
    _recent_trigger_keys: set[str] = field(default_factory=set)

    # -- 触发门 ------------------------------------------------------

    def register_trigger(
        self,
        *,
        candidate_ref: str,
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        cooldown_expires_at: datetime | None = None,
    ) -> EvolutionTrigger | None:
        """EVO-002 门：创建 EvolutionTrigger 前先去重 + 冷却 + 证据校验。"""
        if len(self._triggers) >= self.authority.max_triggers_per_window:
            return None  # ETH-002：触发洪泛有界
        key = candidate_ref
        if key in self._recent_trigger_keys:
            return None  # 冷却/去重
        if not evidence_refs:
            return None  # EVO-003：无证据 -> 不演进
        if cooldown_expires_at is None:
            cooldown_expires_at = self._now() + timedelta(seconds=self.authority.cooldown_seconds)
        trigger_id = new_object_id("trigger")
        trigger = EvolutionTrigger(
            meta=self._meta("EvolutionTrigger", trigger_id),
            evolution_trigger_id=trigger_id,
            candidate_ref=candidate_ref,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            cooldown_expires_at=cooldown_expires_at,
        )
        self._triggers[trigger_id] = trigger
        self._recent_trigger_keys.add(key)
        return trigger

    # -- 修复路由 -----------------------------------------------------

    def route(self, *, symptom_code: str, evidence_refs: tuple[str, ...]) -> RepairRouting:
        """REP-001..005 四路路由器。"""
        if symptom_code.startswith("governance"):
            return RepairRouting("ROUTE_GOVERNANCE", ("r5_governance",))
        if not evidence_refs:
            return RepairRouting("NO_EVOLUTION", ("insufficient_evidence",))
        if symptom_code.startswith("operational"):
            return RepairRouting("OPERATIONAL_ONLY", ("operational_remediation",))
        return RepairRouting("MUTATION", (), "r1")

    # -- 垂直切片 ------------------------------------------------------

    def run_evolution(
        self,
        trigger: EvolutionTrigger,
        *,
        strategy_input: StrategyInput | None = None,
    ) -> EvolutionRun:
        """Trigger -> router -> strategy -> validator -> genome -> candidate。"""
        run_id = new_object_id("evolution-run")
        run = EvolutionRun(
            meta=self._meta("EvolutionRun", run_id),
            evolution_run_id=run_id,
            trigger_ref=trigger.evolution_trigger_id,
            strategy_ref="llm_guided_sparse_mutation",
            status="running",
        )
        self._runs[run_id] = run

        routing = self.route(
            symptom_code=strategy_input.symptom_code if strategy_input else "unknown",
            evidence_refs=trigger.evidence_refs,
        )
        if routing.outcome != "MUTATION":
            done = EvolutionRun(
                meta=run.meta,
                evolution_run_id=run_id,
                trigger_ref=trigger.evolution_trigger_id,
                strategy_ref="llm_guided_sparse_mutation",
                status="no_evolution_needed",
            )
            self._runs[run_id] = done
            return done

        if strategy_input is None:
            done = EvolutionRun(
                meta=run.meta,
                evolution_run_id=run_id,
                trigger_ref=trigger.evolution_trigger_id,
                strategy_ref="llm_guided_sparse_mutation",
                status="no_evolution_needed",
            )
            self._runs[run_id] = done
            return done

        draft = self.strategy.propose(strategy_input)
        if draft is None:
            done = EvolutionRun(
                meta=run.meta,
                evolution_run_id=run_id,
                trigger_ref=trigger.evolution_trigger_id,
                strategy_ref="llm_guided_sparse_mutation",
                status="no_evolution_needed",
            )
            self._runs[run_id] = done
            return done

        # 附加 proposal 身份 + meta，然后进行机器校验。
        proposal = self._finalize_proposal(draft, trigger)
        validation = self.validator.validate(proposal)
        if not validation.valid:
            rejected = self._reject_proposal(proposal)
            done = EvolutionRun(
                meta=run.meta,
                evolution_run_id=run_id,
                trigger_ref=trigger.evolution_trigger_id,
                strategy_ref="llm_guided_sparse_mutation",
                status="aborted",
                proposal_ref=rejected.mutation_proposal_id,
            )
            self._runs[run_id] = done
            return done

        validated = self._validate_proposal(proposal)
        genome = self.materialize(validated)
        candidate_ref: str | None = None
        if self.candidate_build_hook is not None:
            candidate_ref = self.candidate_build_hook(genome)  # CON-011 链路

        completed = EvolutionRun(
            meta=run.meta,
            evolution_run_id=run_id,
            trigger_ref=trigger.evolution_trigger_id,
            strategy_ref="llm_guided_sparse_mutation",
            status="completed",
            proposal_ref=validated.mutation_proposal_id,
            candidate_ref=candidate_ref,
        )
        self._runs[run_id] = completed
        return completed

    def materialize(self, proposal: MutationProposal) -> GenomeManifest:
        """MUT-007：proposal -> 不可变 GenomeManifest 候选。"""
        if proposal.status != "validated":
            raise ValueError("only a validated proposal can be materialized")
        genome_id = new_object_id("genome")
        genome = GenomeManifest(
            meta=self._meta("GenomeManifest", genome_id),
            genome_id=genome_id,
            proposal_ref=proposal.mutation_proposal_id,
            target_ref=proposal.target_ref,
            changes=proposal.changes,
            integrity_ref=f"integrity:{genome_id}",
        )
        self._genomes[genome_id] = genome
        return genome

    # -- 辅助方法 ------------------------------------------------------------

    def _finalize_proposal(
        self, draft: ProposalDraft, trigger: EvolutionTrigger
    ) -> MutationProposal:
        proposal_id = new_object_id("mutation")
        final = MutationProposal(
            meta=self._meta("MutationProposal", proposal_id),
            mutation_proposal_id=proposal_id,
            trigger_ref=trigger.evolution_trigger_id,
            run_ref="",
            target_ref=draft.target_ref,
            repair_level=draft.repair_level,
            change_summary=draft.change_summary,
            changes=draft.changes,
            status="proposed",
        )
        self._proposals[proposal_id] = final
        return final

    def _reject_proposal(self, proposal: MutationProposal) -> MutationProposal:
        rejected = MutationProposal(
            meta=proposal.meta,
            mutation_proposal_id=proposal.mutation_proposal_id,
            trigger_ref=proposal.trigger_ref,
            run_ref=proposal.run_ref,
            target_ref=proposal.target_ref,
            repair_level=proposal.repair_level,
            change_summary=proposal.change_summary,
            changes=proposal.changes,
            status="rejected",
        )
        self._proposals[proposal.mutation_proposal_id] = rejected
        return rejected

    def _validate_proposal(self, proposal: MutationProposal) -> MutationProposal:
        validated = MutationProposal(
            meta=proposal.meta,
            mutation_proposal_id=proposal.mutation_proposal_id,
            trigger_ref=proposal.trigger_ref,
            run_ref=proposal.run_ref,
            target_ref=proposal.target_ref,
            repair_level=proposal.repair_level,
            change_summary=proposal.change_summary,
            changes=proposal.changes,
            status="validated",
        )
        self._proposals[proposal.mutation_proposal_id] = validated
        return validated

    @staticmethod
    def _meta(contract_name: str, object_id: str) -> ContractMeta:
        return ContractMeta(
            contract_name=contract_name,
            contract_version="1.0.0",
            object_id=object_id,
            tenant_id="tenant-evolution",
            created_at=datetime.now(UTC),
            producer="ueaf-evolution",
            producer_version="0.1.0",
        )
