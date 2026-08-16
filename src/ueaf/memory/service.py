"""受治理的记忆服务（核心规范 01 §10.2，功能模块 04）。

Memory Service 是 ``MemoryRecord`` 的唯一写入方。它接收 ``MemoryCandidate`` 对象，
对敏感条目强制执行同意（consent），以确定性的方式物化记录（受治理路径上 0 个
LLM token），并管理候选评审、更正链、过期、删除传播、同意撤销、召回投影与使用审计
（§4.5 / §5.3 / §6 / §7 / §8 / §9）。终态和转换以 revision/CAS 提交（§6）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from ueaf.common.identifiers import new_object_id, utcnow
from ueaf.common.meta import ContractMeta
from ueaf.memory.governance import MemoryGovernanceRules
from ueaf.memory.memory_audit import MemoryAudit, RecallUsage
from ueaf.memory.memory_recall import RecallProjection
from ueaf.memory.objects import MemoryCandidate, MemoryRecord
from ueaf.memory.resolution import (
    REASON_CONFLICT,
    REASON_CONSENT_REQUIRED,
    REASON_DUPLICATE,
    REASON_NOT_APPROVED,
    REASON_SESSION_NOT_PERSISTED,
    REASON_TEAM_TENANT_REVIEW,
    MemoryResolution,
)
from ueaf.memory.review import CandidateReview, CandidateReviewGate, ReviewDecision

PRODUCER = "ueaf-memory"
PRODUCER_VERSION = "0.1.0"
TEAM_TENANT_SCOPES = ("team", "tenant")


class MemoryGovernanceError(RuntimeError):
    """当候选在治理规则下无法被物化时抛出。"""


@dataclass(slots=True)
class InMemoryMemoryStore:
    _records: dict[str, MemoryRecord] = field(default_factory=dict)

    def save(self, record: MemoryRecord) -> MemoryRecord:
        if record.record_id in self._records:
            raise ValueError(f"MemoryRecord {record.record_id} already exists")
        self._records[record.record_id] = record
        return record

    def update(self, record: MemoryRecord) -> MemoryRecord:
        """以 revision 做乐观并发（CAS）更新：新版本必须恰好是当前版本 + 1。"""
        existing = self._records.get(record.record_id)
        if existing is None:
            raise ValueError(f"MemoryRecord {record.record_id} does not exist")
        if record.revision != existing.revision + 1:
            raise MemoryGovernanceError(
                f"MemoryRecord {record.record_id} revision CAS failed: "
                f"expected {existing.revision + 1}, got {record.revision}"
            )
        self._records[record.record_id] = record
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def active_for(self, subject_ref: str, *, moment: datetime) -> list[MemoryRecord]:
        return [
            record
            for record in self._records.values()
            if record.subject_ref == subject_ref
            and record.status == "active"
            and record.valid_from <= moment
            and (record.expires_at is None or moment < record.expires_at)
        ]

    def for_subject(self, subject_ref: str) -> list[MemoryRecord]:
        """某主体的全部记录（任意状态），供治理去重/冲突扫描。"""
        return [
            record for record in self._records.values() if record.subject_ref == subject_ref
        ]

    def all_records(self) -> tuple[MemoryRecord, ...]:
        return tuple(self._records.values())


class MemoryService:
    """受治理记忆的全生命周期服务。

    流程：``submit_candidate``（评审）→ ``review_candidate`` → ``promote_from_review``
    （从 approved 候选）→ ``correct``（更正链）→ ``expire``（置 expired）→ ``delete``
    （传播删除）→ ``recall``（投影 + 审计）→ ``revoke_consent``（同意撤销）。
    兼容保留既有 ``propose``/``promote``/``recall`` 接口。
    """

    def __init__(
        self,
        store: InMemoryMemoryStore | None = None,
        *,
        rules: MemoryGovernanceRules | None = None,
        audit: MemoryAudit | None = None,
    ) -> None:
        self._store = store or InMemoryMemoryStore()
        self._rules = rules or MemoryGovernanceRules()
        self._audit = audit or MemoryAudit()
        self._review = CandidateReviewGate()
        self._projection = RecallProjection(self._store)

    # -- 候选评审流（§7） ----------------------------------------------------

    def submit_candidate(
        self, candidate: MemoryCandidate, *, reviewed_by: str, moment: datetime | None = None
    ) -> CandidateReview:
        """登记一个候选进入待评审（pending_review）。"""
        return self._review.submit_candidate(candidate, reviewed_by=reviewed_by, moment=moment)

    def review_candidate(
        self,
        candidate_ref: str,
        *,
        decision: ReviewDecision,
        reviewed_by: str,
        note: str = "",
        moment: datetime | None = None,
    ) -> CandidateReview:
        """给出评审决定；团队/租户级低置信度 approved 会被强制降级为 needs_review。"""
        review = self._review.review_candidate(
            candidate_ref, decision=decision, reviewed_by=reviewed_by, note=note, moment=moment
        )
        self._audit.increment("review_total")
        return review

    def review_status(self, candidate_ref: str) -> CandidateReview | None:
        """评审状态可观察（含 needs_review）。"""
        return self._review.status(candidate_ref)

    # -- 晋升（§4.5 / §5.3） -------------------------------------------------

    def propose(self, candidate: MemoryCandidate) -> MemoryCandidate:
        """登记一个候选；此时它尚不可被召回（兼容既有接口）。"""
        return candidate

    def promote(
        self, candidate: MemoryCandidate, *, moment: datetime | None = None
    ) -> MemoryRecord:
        """受治理的晋升：先强制同意，再生成权威记录（兼容 CTX-001 直接晋升）。

        治理不通过（同意缺失/重复/冲突/团队租户未评审/会话级不持久化）时抛出
        ``MemoryGovernanceError``。需要非抛错三态结果请使用 ``resolve``。
        """
        resolution = self._promote_governed(
            candidate,
            candidate_ref=candidate.candidate_id,
            moment=moment,
            require_team_tenant_review=True,
        )
        if resolution.outcome != "promoted" or resolution.record_ref is None:
            raise MemoryGovernanceError(
                f"candidate {candidate.candidate_id} cannot be promoted: "
                f"{','.join(resolution.reason_codes)}"
            )
        record = self._store.get(resolution.record_ref)
        assert record is not None
        return record

    def resolve(
        self, candidate: MemoryCandidate, *, moment: datetime | None = None
    ) -> MemoryResolution:
        """一次候选治理决定（promoted/rejected/needs_review 三态，不抛错）。"""
        return self._promote_governed(
            candidate,
            candidate_ref=candidate.candidate_id,
            moment=moment,
            require_team_tenant_review=True,
        )

    def promote_from_review(
        self, candidate_ref: str, *, moment: datetime | None = None
    ) -> MemoryResolution:
        """从已 approved 的候选晋升；未评审/未 approved 的候选返回 needs_review。"""
        candidate = self._review.approved_candidate(candidate_ref)
        if candidate is None:
            return MemoryResolution(
                outcome="needs_review",
                reason_codes=(REASON_NOT_APPROVED,),
                candidate_ref=candidate_ref,
            )
        return self._promote_governed(
            candidate, candidate_ref=candidate_ref, moment=moment, require_team_tenant_review=False
        )

    def _promote_governed(
        self,
        candidate: MemoryCandidate,
        *,
        candidate_ref: str,
        moment: datetime | None,
        require_team_tenant_review: bool,
    ) -> MemoryResolution:
        moment = moment or utcnow()
        scope = candidate.scope_requested or candidate.purpose

        # 1. 同意：confidential/restricted 必须已获同意（CTX-001 记忆语义 / §10.2）。
        #    参考实现无外部 ConsentPort，因此敏感候选一律以受控 rejected 拒绝，
        #    绝不带缺失 consent_ref 进入 _build_record 抛裸 ValueError。
        if candidate.sensitivity in ("confidential", "restricted"):
            self._audit.increment("candidate_rejected")
            return MemoryResolution(
                outcome="rejected",
                reason_codes=(REASON_CONSENT_REQUIRED,),
                candidate_ref=candidate_ref,
            )

        # 2. 团队/租户级记忆须经 approved 评审（§7 更高审查阈值）。
        if require_team_tenant_review and scope in TEAM_TENANT_SCOPES:
            if self._review.approved_candidate(candidate.candidate_id) is None:
                self._audit.increment("candidate_rejected")
                return MemoryResolution(
                    outcome="needs_review",
                    reason_codes=(REASON_TEAM_TENANT_REVIEW,),
                    candidate_ref=candidate_ref,
                )

        # 3. 保留期：会话级记忆不持久化（§11 默认 session 或不持久化）。
        retention = self._rules.retention_decide(candidate)
        if not retention.persist:
            self._audit.increment("candidate_rejected")
            return MemoryResolution(
                outcome="rejected",
                reason_codes=(REASON_SESSION_NOT_PERSISTED,),
                candidate_ref=candidate_ref,
            )

        # 4. 去重（RAG-011）与冲突（CTX-006 / RAG-012）——绝不后写覆盖。
        existing = tuple(self._store.for_subject(candidate.subject_ref))
        duplicates = self._rules.detect_duplicate(candidate, existing)
        if duplicates:
            self._audit.increment("candidate_rejected")
            return MemoryResolution(
                outcome="rejected",
                reason_codes=(REASON_DUPLICATE, *duplicates),
                candidate_ref=candidate_ref,
            )
        conflicts = self._rules.detect_conflict(candidate, existing)
        if conflicts:
            self._audit.increment("conflict_total")
            return MemoryResolution(
                outcome="needs_review",
                reason_codes=(REASON_CONFLICT, *conflicts),
                candidate_ref=candidate_ref,
            )

        # 5. 物化权威记录。
        record = self._build_record(
            candidate,
            scope=scope,
            valid_from=moment,
            expires_at=retention.expires_at(moment),
        )
        self._store.save(record)
        self._audit.increment("candidate_promoted")
        return MemoryResolution(
            outcome="promoted",
            reason_codes=(),
            record_ref=record.record_id,
            candidate_ref=candidate_ref,
        )

    def _build_record(
        self,
        candidate: MemoryCandidate,
        *,
        scope: str,
        valid_from: datetime,
        expires_at: datetime | None,
    ) -> MemoryRecord:
        record_id = new_object_id("memory")
        consent_ref = (
            f"consent:{candidate.subject_ref}:{candidate.candidate_id}"
            if candidate.required_consent
            else None
        )
        return MemoryRecord(
            meta=ContractMeta(
                contract_name="MemoryRecord",
                contract_version="1.0.0",
                object_id=record_id,
                tenant_id=candidate.meta.tenant_id,
                created_at=valid_from,
                producer=PRODUCER,
                producer_version=PRODUCER_VERSION,
                classification=candidate.sensitivity,
                purpose=(candidate.purpose,),
            ),
            record_id=record_id,
            subject_ref=candidate.subject_ref,
            scope=scope,
            source_refs=candidate.source_refs,
            statement=candidate.statement,
            confidence=candidate.confidence,
            consent_ref=consent_ref,
            sensitivity=candidate.sensitivity,
            valid_from=valid_from,
            expires_at=expires_at,
            revision=1,
        )

    # -- 更正 / 过期 / 删除 / 同意撤销（§5.3 / §6 / §7 / §8） ----------------

    def correct(
        self,
        record_id: str,
        *,
        statement: str,
        confidence: float,
        moment: datetime | None = None,
        reason: str = "",
        source_refs: tuple[str, ...] | None = None,
    ) -> MemoryRecord:
        """更正链：创建新版本并使旧记录 superseded（§5.3 / CTX-004 / CTX-005）。"""
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be within [0, 1]")
        moment = moment or utcnow()
        old = self._store.get(record_id)
        if old is None:
            raise MemoryGovernanceError(f"cannot correct unknown record {record_id!r}")
        # M2：更正链必须是线性的——只允许更正当前活动版本；对已 superseded/expired/
        # deleted 记录再更正会造成谱系分叉（同 subject/scope 出现多条 active）。
        if old.status != "active":
            raise MemoryGovernanceError(
                f"cannot correct {old.status!r} record {record_id!r}; "
                "only the current active version can be corrected"
            )

        superseded = replace(old, status="superseded", revision=old.revision + 1)
        self._store.update(superseded)

        # 原记录已过有效期则新记录不再继承过期时间（避免新版本立即过期）。
        expires_at = old.expires_at
        if expires_at is not None and expires_at <= moment:
            expires_at = None
        new_id = new_object_id("memory")
        new = MemoryRecord(
            meta=ContractMeta(
                contract_name="MemoryRecord",
                contract_version="1.0.0",
                object_id=new_id,
                tenant_id=old.meta.tenant_id,
                created_at=moment,
                producer=PRODUCER,
                producer_version=PRODUCER_VERSION,
                classification=old.sensitivity,
                purpose=old.meta.purpose,
            ),
            record_id=new_id,
            subject_ref=old.subject_ref,
            scope=old.scope,
            source_refs=source_refs or old.source_refs,
            statement=statement,
            confidence=confidence,
            consent_ref=old.consent_ref,
            sensitivity=old.sensitivity,
            valid_from=moment,
            expires_at=expires_at,
            status="active",
            supersedes_ref=old.record_id,
            deletion_state=None,
            use_audit_policy_ref=old.use_audit_policy_ref,
            revision=1,
        )
        self._store.save(new)
        return new

    def expire(self, record_id: str, *, moment: datetime | None = None) -> MemoryRecord:
        """显式过期：状态置 expired（§6），并观测过期滞后。"""
        moment = moment or utcnow()
        record = self._store.get(record_id)
        if record is None:
            raise MemoryGovernanceError(f"cannot expire unknown record {record_id!r}")
        if record.status != "active":
            raise MemoryGovernanceError(
                f"only active records can be expired, got {record.status!r}"
            )
        if record.expires_at is not None and moment > record.expires_at:
            lag = (moment - record.expires_at).total_seconds()
            self._audit.observe_expiry_lag(lag)
        updated = replace(record, status="expired", revision=record.revision + 1)
        self._store.update(updated)
        return updated

    def delete(
        self,
        record_id: str,
        *,
        moment: datetime | None = None,
        reason: str = "",
        slo_seconds: float = 0.0,
    ) -> MemoryRecord:
        """删除传播：覆盖权威 Store + 检索投影 + 使用审计（§5.3 / RAG-007 / RAG-008）。

        投影始终读取权威 Store，标记 deleted 后自动不再命中；超过 SLO 时计数
        ``deletion_slo_breach``。
        """
        del moment
        record = self._store.get(record_id)
        if record is None:
            raise MemoryGovernanceError(f"cannot delete unknown record {record_id!r}")
        if record.status == "deleted":
            return record
        updated = replace(
            record,
            status="deleted",
            deletion_state=reason or "deleted",
            revision=record.revision + 1,
        )
        self._store.update(updated)
        # 内存实现传播为即时完成；SLO 判断由审计方法承载（测试可显式构造滞后）。
        self._audit.observe_deletion(0.0, slo_seconds)
        return updated

    def revoke_consent(
        self,
        consent_ref: str,
        *,
        moment: datetime | None = None,
        reason: str = "consent_revoked",
    ) -> tuple[str, ...]:
        """同意撤销：使受影响记录失效（删除），并传播到投影（RAG-007）。"""
        del moment
        affected = [
            record
            for record in self._store.all_records()
            if record.consent_ref == consent_ref and record.status == "active"
        ]
        affected_ids: list[str] = []
        for record in affected:
            updated = replace(
                record,
                status="deleted",
                deletion_state=reason,
                revision=record.revision + 1,
            )
            self._store.update(updated)
            affected_ids.append(record.record_id)
        return tuple(affected_ids)

    # -- 召回投影 + 使用审计（§5.1 第 7 点 / §9） ------------------------------

    def recall(
        self,
        subject_ref: str,
        *,
        scope: str | None = None,
        purpose: str | None = None,
        moment: datetime | None = None,
        include_team_tenant: bool = False,
        consent_ref: str | None = None,
        authorized_team_refs: tuple[str, ...] = (),
        authorized_tenant_ref: str | None = None,
    ) -> list[MemoryRecord]:
        """召回受治理记忆并记录使用审计（绝不直接召回候选；兼容既有 recall(subject_ref)）。

        M3：团队/租户级记忆须由调用方授权身份背书（``authorized_team_refs`` /
        ``authorized_tenant_ref``），未授权绝不返回（§7）。
        """
        moment = moment or utcnow()
        records = self._projection.recall(
            subject_ref,
            scope=scope,
            purpose=purpose,
            moment=moment,
            include_team_tenant=include_team_tenant,
            consent_ref=consent_ref,
            authorized_team_refs=authorized_team_refs,
            authorized_tenant_ref=authorized_tenant_ref,
        )
        self._audit.record_recall(
            subject_ref,
            scope=scope,
            purpose=purpose,
            moment=moment,
            hit_count=len(records),
            record_refs=tuple(record.record_id for record in records),
        )
        return records

    def audit_metrics(self) -> dict[str, int | float]:
        """指标快照：供 TelemetryPort 采集（§9）。"""
        return self._audit.metrics()

    def audit_usages(self) -> tuple[RecallUsage, ...]:
        """召回使用审计记录。"""
        return self._audit.usages()
