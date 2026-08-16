"""tests/memory 共享构造器（非测试模块，不携带 Test ID）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ueaf.common.meta import ContractMeta
from ueaf.memory.objects import MemoryCandidate

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-demo"


def meta(contract_name: str, object_id: str, *, tenant: str = TENANT) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=tenant,
        created_at=MOMENT,
        producer="ueaf-test",
        producer_version="0.1.0",
    )


def candidate(
    candidate_id: str,
    *,
    subject_ref: str = "principal:1",
    purpose: str = "analytics",
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal",
    statement: str = "workflow preference",
    confidence: float = 0.8,
    required_consent: bool = False,
    scope_requested: str = "",
    retention_hint: str = "",
    tenant: str = TENANT,
) -> MemoryCandidate:
    """构造一个测试 MemoryCandidate（默认 internal 非敏感、subject 级）。"""
    return MemoryCandidate(
        meta=meta("MemoryCandidate", candidate_id, tenant=tenant),
        candidate_id=candidate_id,
        subject_ref=subject_ref,
        source_refs=(f"evidence:{candidate_id}",),
        purpose=purpose,
        sensitivity=sensitivity,
        statement=statement,
        confidence=confidence,
        required_consent=required_consent,
        proposed_at=MOMENT,
        scope_requested=scope_requested,
        retention_hint=retention_hint,
    )
