"""Evidence Assembler：把已授权检索结果装配为 EvidencePack（RAG-001/CTX-006/RAG-013）。

装配只处理已授权候选（RAG-001：ACL 先于相关性；未携带 ACL 证明的候选以
fail-closed 方式省略）。来源冲突保留在 ``conflicts`` 中而绝不静默消解
（CTX-006），去重绝不删除存在冲突的来源。每项证据携带可解析到来源版本 +
locator 的引用句柄（RAG-013）。证据正文与元数据分离：items 只保存内容引用与
最小片段，正文留在受控 Artifact Store。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ueaf.common.identifiers import new_object_id
from ueaf.context.conflict import ClaimConflict, ConflictRegistry
from ueaf.context.query_planner import QueryIntent
from ueaf.context.retrieval_router import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """单个证据项（模块内部派生对象，非持久化规范对象）。

    正文与元数据分离：只携带内容引用与最小片段，不复制正文到 Run 状态。
    """

    source_ref: str
    source_version: str
    locator: str
    content_ref: str
    snippet: str
    allowed_scopes: tuple[str, ...]
    trust_label: str
    citation_handle: str


@dataclass(frozen=True, slots=True)
class SourceVersion:
    """装配时观察到的来源版本（用于重放/缓存/新鲜度判断）。"""

    source_ref: str
    source_version: str


@dataclass(frozen=True, slots=True)
class Coverage:
    """已覆盖 / 缺失 / 矛盾集合。"""

    covered: tuple[str, ...]
    missing: tuple[str, ...]
    contradictions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FreshnessStatus:
    """各来源新鲜度、水位和是否满足需求。"""

    source_ref: str
    observed_at: datetime | None
    max_freshness_seconds: int | None
    satisfies: bool


@dataclass(frozen=True, slots=True)
class CitationMapEntry:
    """结果片段到稳定来源定位的映射（RAG-013）。"""

    citation_handle: str
    source_ref: str
    source_version: str
    locator: str


@dataclass(frozen=True, slots=True)
class OmissionSummary:
    """因授权/预算/过期/冲突被排除的安全统计（不泄露内容）。"""

    authorization_omitted: int = 0
    budget_omitted: int = 0
    expired_omitted: int = 0
    conflict_omitted: int = 0
    note: str = ""


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """已授权证据包（模块内部派生对象，非持久化规范对象）。

    证明“在给定时间、主体和用途下观察到什么”，不证明内容必然为真，也不替代
    权威 ``BusinessFactRef`` 指向的来源系统。
    """

    evidence_pack_id: str
    query_intent_ref: str
    principal_context_ref: str
    items: tuple[EvidenceItem, ...]
    authorization_proof_refs: tuple[str, ...]
    source_versions: tuple[SourceVersion, ...]
    coverage: Coverage
    conflicts: tuple[ClaimConflict, ...]
    freshness: tuple[FreshnessStatus, ...]
    selection_policy_ref: str
    citation_map: tuple[CitationMapEntry, ...]
    expires_at: datetime
    omission_summary: OmissionSummary


class EvidenceAssembler:
    """装配 EvidencePack；证据正文与元数据分离（RAG-001/CTX-006/RAG-013）。"""

    def __init__(
        self,
        *,
        selection_policy_ref: str,
        producer_version: str = "0.1.0",
    ) -> None:
        self._selection_policy_ref = selection_policy_ref
        self._producer_version = producer_version

    def assemble(
        self,
        intent: QueryIntent,
        *,
        candidates: tuple[RetrievalCandidate, ...],
        registry: ConflictRegistry | None = None,
        required_question_refs: tuple[str, ...] = (),
        max_freshness_seconds: int | None = None,
        observed_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> EvidencePack:
        registry = registry or ConflictRegistry()
        authorization_omitted = 0
        expired_omitted = 0
        items: list[EvidenceItem] = []
        for candidate in candidates:
            # RAG-001：未携带 ACL 证明的候选以 fail-closed 方式省略。
            if candidate.acl_proof_ref is None:
                authorization_omitted += 1
                continue
            if max_freshness_seconds is not None and self._is_stale(
                candidate, observed_at=observed_at, max_freshness_seconds=max_freshness_seconds
            ):
                expired_omitted += 1
                continue
            items.append(
                EvidenceItem(
                    source_ref=candidate.source_ref,
                    source_version=candidate.source_version,
                    locator=candidate.locator,
                    content_ref=candidate.content_ref,
                    snippet=candidate.snippet,
                    allowed_scopes=candidate.allowed_scopes,
                    trust_label=candidate.trust_label,
                    citation_handle=candidate.citation_handle,
                )
            )

        item_source_refs = tuple(item.source_ref for item in items)
        # CTX-006：来源冲突保留，绝不静默消解；去重绝不删除存在冲突的来源。
        conflicts = registry.evidence_pack_conflicts(item_source_refs)
        covered = tuple(
            ref
            for ref in required_question_refs
            if any(
                ref in (item.source_ref, item.content_ref, item.citation_handle) for item in items
            )
        )
        coverage = Coverage(
            covered=covered,
            missing=tuple(ref for ref in required_question_refs if ref not in covered),
            contradictions=tuple(conflict.claim_ref for conflict in conflicts),
        )
        freshness = self._freshness(items, observed_at, max_freshness_seconds)
        proof_refs = tuple(
            dict.fromkeys(
                candidate.acl_proof_ref
                for candidate in candidates
                if candidate.acl_proof_ref is not None
            )
        )
        return EvidencePack(
            evidence_pack_id=new_object_id("evidence-pack"),
            query_intent_ref=intent.query_intent_id,
            principal_context_ref=intent.principal_context_ref,
            items=tuple(items),
            authorization_proof_refs=proof_refs,
            source_versions=tuple(
                dict.fromkeys(
                    SourceVersion(item.source_ref, item.source_version) for item in items
                )
            ),
            coverage=coverage,
            conflicts=conflicts,
            freshness=freshness,
            selection_policy_ref=self._selection_policy_ref,
            citation_map=tuple(
                CitationMapEntry(
                    citation_handle=item.citation_handle,
                    source_ref=item.source_ref,
                    source_version=item.source_version,
                    locator=item.locator,
                )
                for item in items
            ),
            expires_at=expires_at or intent.expires_at,
            omission_summary=OmissionSummary(
                authorization_omitted=authorization_omitted,
                expired_omitted=expired_omitted,
                conflict_omitted=len(registry.conflicts()) - len(conflicts),
            ),
        )

    @staticmethod
    def _is_stale(
        candidate: RetrievalCandidate,
        *,
        observed_at: datetime | None,
        max_freshness_seconds: int,
    ) -> bool:
        # M3/RAG-013：设置了严格新鲜度约束时，未知时效的候选按过期处理
        # （fail-closed），绝不把无时效信息当作实时证据装入。
        if candidate.observed_at is None or observed_at is None:
            return True
        return (observed_at - candidate.observed_at).total_seconds() > max_freshness_seconds

    @staticmethod
    def _freshness(
        items: list[EvidenceItem],
        observed_at: datetime | None,
        max_freshness_seconds: int | None,
    ) -> tuple[FreshnessStatus, ...]:
        if max_freshness_seconds is None:
            return tuple(
                FreshnessStatus(
                    source_ref=item.source_ref,
                    observed_at=None,
                    max_freshness_seconds=None,
                    satisfies=True,
                )
                for item in items
            )
        return tuple(
            FreshnessStatus(
                source_ref=item.source_ref,
                observed_at=observed_at,
                max_freshness_seconds=max_freshness_seconds,
                satisfies=True,
            )
            for item in items
        )


__all__ = [
    "EvidenceItem",
    "SourceVersion",
    "Coverage",
    "FreshnessStatus",
    "CitationMapEntry",
    "OmissionSummary",
    "EvidencePack",
    "EvidenceAssembler",
]
