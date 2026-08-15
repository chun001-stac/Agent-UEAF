"""Memory canonical objects (core spec 01 §10.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Pending memory candidate; not recalled until governed and consented."""

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

    def __post_init__(self) -> None:
        if self.candidate_id != self.meta.object_id:
            raise ValueError("MemoryCandidate.meta.object_id must equal candidate_id")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("MemoryCandidate.confidence must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """Authoritative governed memory; the Memory Service is its only writer."""

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
    status: Literal["active", "superseded", "deleted"] = "active"
    supersedes_ref: str | None = None
    deletion_state: str | None = None
    use_audit_policy_ref: str = "audit-policy:default"

    def __post_init__(self) -> None:
        if self.record_id != self.meta.object_id:
            raise ValueError("MemoryRecord.meta.object_id must equal record_id")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("MemoryRecord.confidence must be within [0, 1]")
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("MemoryRecord.expires_at must be later than valid_from")
        if self.sensitivity in ("confidential", "restricted") and not self.consent_ref:
            raise ValueError("confidential/restricted memory requires an explicit consent_ref")
