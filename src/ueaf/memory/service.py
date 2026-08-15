"""Governed Memory Service (core spec 01 §10.2, functional module 04).

The Memory Service is the only writer of ``MemoryRecord``. It accepts
``MemoryCandidate`` objects, enforces consent for sensitive entries, and
materializes records deterministically (0 LLM token on the governed path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ueaf.common.identifiers import new_object_id, utcnow
from ueaf.common.meta import ContractMeta
from ueaf.memory.objects import MemoryCandidate, MemoryRecord

PRODUCER = "ueaf-memory"
PRODUCER_VERSION = "0.1.0"


class MemoryGovernanceError(RuntimeError):
    """Raised when a candidate cannot be materialized under governance."""


@dataclass(slots=True)
class InMemoryMemoryStore:
    _records: dict[str, MemoryRecord] = field(default_factory=dict)

    def save(self, record: MemoryRecord) -> MemoryRecord:
        if record.record_id in self._records:
            raise ValueError(f"MemoryRecord {record.record_id} already exists")
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


class MemoryService:
    """Materializes governed memory from candidates (consent enforced)."""

    def __init__(self, store: InMemoryMemoryStore | None = None) -> None:
        self._store = store or InMemoryMemoryStore()

    def propose(self, candidate: MemoryCandidate) -> MemoryCandidate:
        """Register a candidate; it is not yet recallable."""
        return candidate

    def promote(self, candidate: MemoryCandidate) -> MemoryRecord:
        """Governed promotion: consent enforced, then an authoritative record."""
        moment = utcnow()
        if candidate.required_consent and candidate.sensitivity in ("confidential", "restricted"):
            raise MemoryGovernanceError(
                "confidential/restricted candidate requires an explicit consent_ref"
            )
        record_id = new_object_id("memory")
        consent_ref = (
            f"consent:{candidate.subject_ref}:{candidate.candidate_id}"
            if candidate.required_consent
            else None
        )
        record = MemoryRecord(
            meta=ContractMeta(
                contract_name="MemoryRecord",
                contract_version="1.0.0",
                object_id=record_id,
                tenant_id=candidate.meta.tenant_id,
                created_at=moment,
                producer=PRODUCER,
                producer_version=PRODUCER_VERSION,
            ),
            record_id=record_id,
            subject_ref=candidate.subject_ref,
            scope=candidate.purpose,
            source_refs=candidate.source_refs,
            statement=candidate.statement,
            confidence=candidate.confidence,
            consent_ref=consent_ref,
            sensitivity=candidate.sensitivity,
            valid_from=moment,
        )
        self._store.save(record)
        return record

    def recall(self, subject_ref: str) -> list[MemoryRecord]:
        """Recall active governed memory (never candidates directly)."""
        return self._store.active_for(subject_ref, moment=utcnow())
