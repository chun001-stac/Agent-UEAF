"""记忆规范对象（核心规范 01 §10.2）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """待处理的记忆候选；在受治理并获得同意之前不会被召回。

    ``scope_requested`` 表达候选申请的记忆可见范围（``session/subject/team/tenant``）；
    ``retention_hint`` 表达候选期望的保留策略提示（如 ``90d``、``session``），由治理
    规则映射为 ``MemoryRecord.expires_at``。两者均带默认值，不破坏既有构造。
    """

    meta: ContractMeta
    candidate_id: str
    subject_ref: str
    source_refs: tuple[str, ...]
    purpose: str
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    statement: str
    confidence: float
    required_consent: bool
    proposed_at: datetime | None = None
    scope_requested: str = ""
    retention_hint: str = ""

    def __post_init__(self) -> None:
        if self.candidate_id != self.meta.object_id:
            raise ValueError("MemoryCandidate.meta.object_id must equal candidate_id")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("MemoryCandidate.confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """权威的受治理记忆；Memory Service 是其唯一写入方。

    ``status`` 覆盖 ``active/superseded/expired/deleted``；``expired`` 由保留期到期或
    显式过期产生（功能模块 04 §6）。``revision`` 用于更正/状态迁移的乐观并发（CAS，
    §6：终态和转换由 Memory Service 以 revision/CAS 提交）。
    """

    meta: ContractMeta
    record_id: str
    subject_ref: str
    scope: str
    source_refs: tuple[str, ...]
    statement: str
    confidence: float
    consent_ref: str | None
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    valid_from: datetime
    expires_at: datetime | None = None
    status: Literal["active", "superseded", "expired", "deleted"] = "active"
    supersedes_ref: str | None = None
    deletion_state: str | None = None
    use_audit_policy_ref: str = "audit-policy:default"
    revision: int = 1

    def __post_init__(self) -> None:
        if self.record_id != self.meta.object_id:
            raise ValueError("MemoryRecord.meta.object_id must equal record_id")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("MemoryRecord.confidence must be within [0, 1]")
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("MemoryRecord.expires_at must be later than valid_from")
        if self.sensitivity in ("confidential", "restricted") and not self.consent_ref:
            raise ValueError("confidential/restricted memory requires an explicit consent_ref")
        if self.revision < 1:
            raise ValueError("MemoryRecord.revision must be >= 1")
