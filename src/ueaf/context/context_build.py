"""ContextBuildPort 参考实现（模块 04 拥有 ContextManifest）。

ACL 过滤必须先于相关性排序（RAG-001）；模块 03/05 只负责校验与映射，绝不重写清单。
该构建器符合核心 ``ContextBuildPort.build(request) -> PortResult[ContextManifest]``
签名；来源与主体范围在构造时提供。构建流程：ACL 过滤 -> 确定性选择 -> Token 预算
装配（TokenBudgeter，CTX-002/003）-> EvidencePack 装配（EvidenceAssembler，
CTX-006/RAG-013）-> 完整 ContextManifest。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.context.compression import CompressionLineage
from ueaf.context.conflict import ConflictRegistry
from ueaf.context.evidence_assembler import EvidenceAssembler, EvidencePack
from ueaf.context.query_planner import QueryIntent
from ueaf.context.retrieval_router import RetrievalCandidate
from ueaf.context.token_budgeter import (
    Slot,
    SlotItem,
    TokenBudgeter,
    estimate_item_tokens,
)
from ueaf.ports import (
    ContextBuildRequest,
    ContextManifest,
    PortError,
    PortResult,
    Rejected,
    Success,
)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """可被打包进 ContextManifest 的来源。"""

    source_ref: str
    source_version: str
    content_digest: str
    allowed_scopes: tuple[str, ...]
    trust_label: str
    summary_ref: str | None = None
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class ManifestSection:
    """装配后的槽位/分区（模块内部派生对象，非持久化规范对象）。

    只记录内容引用/来源版本/用途/Token 与选择原因，不复制正文到 Run 状态。
    """

    section_ref: str
    source_refs: tuple[str, ...]
    purpose: str
    tokens: int
    selection_reason: str


# trust_label -> Context tier（CTX-002 五层打包优先级；不存在第二套公共 tier enum）。
_TIER_OF_TRUST = {
    "tier0": 0,
    "high": 1,
    "medium": 2,
    "low": 4,
}


class ContextBuilder:
    """确定性上下文打包器：先 ACL，再选择，再预算，再省略。"""

    def __init__(
        self,
        *,
        sources: list[SourceDocument] | None = None,
        principal_scopes: tuple[str, ...] = (),
        max_snippets: int = 8,
        producer_version: str = "0.1.0",
        max_manifest_tokens: int = 10_000,
        critical_reserve_tokens: int = 512,
        principal_context_ref: str = "",
        purpose: str = "",
        source_constraints: tuple[str, ...] = (),
        authorization_scope_ref: str = "",
        freshness_requirement: str = "",
        citation_requirement: bool = False,
        budget_slice: str = "",
        selection_policy_ref: str = "context-selection@1.0.0",
        conflict_registry: ConflictRegistry | None = None,
        compression_lineage: CompressionLineage | None = None,
    ) -> None:
        self._sources = list(sources or [])
        self._principal_scopes = tuple(principal_scopes)
        self._max_snippets = max_snippets
        self._producer_version = producer_version
        self._max_manifest_tokens = max_manifest_tokens
        self._critical_reserve_tokens = critical_reserve_tokens
        self._principal_context_ref = principal_context_ref
        self._purpose = purpose
        self._source_constraints = tuple(source_constraints)
        self._authorization_scope_ref = authorization_scope_ref
        self._freshness_requirement = freshness_requirement
        self._citation_requirement = citation_requirement
        self._budget_slice = budget_slice
        self._selection_policy_ref = selection_policy_ref
        self._conflict_registry = conflict_registry or ConflictRegistry()
        self._compression_lineage = compression_lineage or CompressionLineage()
        self._superseded_refs: dict[str, str] = {}  # 纠正来源 -> 被取代的来源
        self._last_evidence_pack: EvidencePack | None = None

    def build(self, request: ContextBuildRequest) -> PortResult[ContextManifest]:
        # RAG-001：ACL 先于相关性：主体范围之外的来源会被省略。
        allowed = [
            source
            for source in self._sources
            if set(source.allowed_scopes).intersection(self._principal_scopes)
        ]
        # 确定性选择：先按 Context tier 优先级（Tier 0 最高，绝不被优先截断），
        # 再按来源顺序（CTX-002/CTX-008）。
        allowed.sort(key=lambda s: (self._tier_of(s.trust_label), s.source_ref))
        selected = allowed[: self._max_snippets]

        intent = self._intent_for(request)
        # CTX-002/003：Token Budgeter 按槽位裁剪；Tier 0 与关键否定绝不静默截断。
        budgeter = TokenBudgeter(
            critical_reserve_tokens=self._critical_reserve_tokens,
            lineage=self._compression_lineage,
        )
        slots = tuple(
            Slot(
                slot_ref=source.source_ref,
                tier=self._tier_of(source.trust_label),
                max_tokens=self._max_manifest_tokens,
                items=(
                    SlotItem(
                        ref=source.source_ref,
                        tokens=estimate_item_tokens(source.snippet or ""),
                    ),
                ),
                is_critical=self._tier_of(source.trust_label) == 0,
            )
            for source in selected
        )
        budget_result = budgeter.budget(slots, max_total_tokens=self._max_manifest_tokens)
        if budget_result.status == "budget_failure":
            failure = budget_result.failure
            # CTX-003：返回确定性的预算失败而不是看似合理的清单；模型绝不会被调用。
            return Rejected(
                PortError(
                    code=failure.code if failure is not None else "context_budget_exceeded",
                    category="budget",
                    retryability="never",
                    certainty="not_executed",
                    message_ref=None,
                    provider_error_ref=None,
                    observed_at=request.deadline_at,
                    details_schema_ref=(
                        failure.details_schema_ref
                        if failure is not None
                        else "schema://context-budget-failure/1.0.0"
                    ),
                )
            )

        fitted_refs = {ref for outcome in budget_result.fitted for ref in outcome.kept}
        fitted = [source for source in selected if source.source_ref in fitted_refs]

        # EvidencePack：只装配最终装入的（已授权 + 已预算）来源。
        evidence_pack = self._assemble_pack(intent, fitted, request)
        self._last_evidence_pack = evidence_pack

        sections = tuple(
            ManifestSection(
                section_ref=outcome.slot_ref,
                source_refs=outcome.kept,
                purpose=self._purpose,
                tokens=outcome.tokens,
                selection_reason="selected" if outcome.kept else "omitted",
            )
            for outcome in budget_result.fitted
            if outcome.kept
        )
        selection_decisions = tuple(
            f"{source.source_ref}:"
            + ("selected" if source.source_ref in fitted_refs else "omitted:budget")
            for source in selected
        )

        manifest_id = new_object_id("context")
        integrity = sha256_hex(
            "|".join(
                f"{source.source_ref}@{source.source_version}:{source.content_digest}"
                for source in fitted
            )
        )
        manifest = ContextManifest(
            context_manifest_id=manifest_id,
            run_id=request.run_id,
            schema_ref="schema://context-manifest/1.0.0",
            # M2/RAG-013：引用产生本次清单的 EvidencePack，而非重复 source 列表；
            # 使 Manifest 可追溯回其证据包。
            evidence_pack_refs=(evidence_pack.evidence_pack_id,),
            integrity_ref=integrity,
            sections=sections,
            source_refs=tuple(item.source_ref for item in evidence_pack.items),
            policy_snapshot_ref=request.policy_snapshot_ref,
            budget_before=budget_result.budget_before,
            budget_after=budget_result.budget_after,
            selection_decisions=selection_decisions,
            omissions=budget_result.omissions,
            compression_records=tuple(self._compression_lineage.records),
            trust_labels=tuple(source.trust_label for source in fitted),
        )
        return Success(manifest)

    def record_superseded(self, correction_ref: str, superseded_ref: str) -> None:
        """记录更新的纠正取代旧摘要（CTX-004）。"""
        self._superseded_refs[correction_ref] = superseded_ref

    @property
    def superseded_refs(self) -> dict[str, str]:
        return dict(self._superseded_refs)

    @property
    def last_evidence_pack(self) -> EvidencePack | None:
        """最近一次装配的 EvidencePack（供审计/评测/诊断）。"""
        return self._last_evidence_pack

    @property
    def packed_source_count(self) -> int:
        return len(self._sources)

    def _intent_for(self, request: ContextBuildRequest) -> QueryIntent:
        """从请求派生出本次装配的 QueryIntent（只读，不改变 TaskState）。"""
        return QueryIntent(
            query_intent_id=request.query_intent_ref,
            run_id=request.run_id,
            principal_context_ref=self._principal_context_ref,
            query=request.query_intent_ref,
            purpose=self._purpose,
            source_constraints=self._source_constraints,
            authorization_scope_ref=self._authorization_scope_ref,
            freshness_requirement=self._freshness_requirement,
            citation_requirement=self._citation_requirement,
            budget_slice=self._budget_slice,
            normalized_query_hash=sha256_hex(request.query_intent_ref),
            policy_snapshot_ref=request.policy_snapshot_ref,
            expires_at=request.deadline_at,
        )

    def _assemble_pack(
        self,
        intent: QueryIntent,
        fitted: list[SourceDocument],
        request: ContextBuildRequest,
    ) -> EvidencePack:
        candidates = tuple(
            RetrievalCandidate(
                source_ref=source.source_ref,
                source_version=source.source_version,
                locator=source.summary_ref or source.source_ref,
                content_ref=source.source_ref,
                snippet=source.snippet or "",
                allowed_scopes=source.allowed_scopes,
                trust_label=source.trust_label,
                citation_handle=f"cite:{source.source_ref}",
                route="lexical",
                acl_proof_ref=f"acl-proof:{sha256_hex(f'{request.policy_snapshot_ref}|{source.source_ref}@{source.source_version}')}",
            )
            for source in fitted
        )
        return EvidenceAssembler(selection_policy_ref=self._selection_policy_ref).assemble(
            intent,
            candidates=candidates,
            registry=self._conflict_registry,
            expires_at=request.deadline_at,
            # M3：把 fresh 约束解析下传；未提供 observed_at 的来源会按
            # fail-closed 省略（严格新鲜度下无时效证据不装入）。
            max_freshness_seconds=_parse_freshness_seconds(self._freshness_requirement),
        )

    @staticmethod
    def _tier_of(trust_label: str) -> int:
        return _TIER_OF_TRUST.get(trust_label, 4)


def _parse_freshness_seconds(freshness_requirement: str) -> int | None:
    """从 ``max_age_seconds=N`` 解析新鲜度上限；无法解析则返回 None（不强制）。"""
    if not freshness_requirement:
        return None
    marker = "max_age_seconds="
    if marker not in freshness_requirement:
        return None
    tail = freshness_requirement.split(marker, 1)[1].strip()
    try:
        value = int(tail.split()[0])
    except ValueError:
        return None
    return value if value >= 0 else None
