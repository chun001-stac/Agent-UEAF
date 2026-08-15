"""UEAF canonical metadata for cross-module persisted objects.

Implements ``ContractMeta`` (core spec 01 §5) as a frozen dataclass so every
persisted canonical object can carry a complete, reconstructable metadata
block without leaking ORM-internal fields into the wire contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Classification = Literal["public", "internal", "confidential", "restricted"]
Purpose = tuple[str, ...]

_PROVENANCE_SOURCE_TYPES = ("request", "task", "run", "evidence_pack", "external_system")


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    """A single origin or derivation link in ``ContractMeta.provenance``."""

    source_type: str
    source_ref: str
    observed_at: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.source_type:
            raise ValueError("ProvenanceRef.source_type must not be empty")
        if not self.source_ref:
            raise ValueError("ProvenanceRef.source_ref must not be empty")
        if (
            self.source_type not in _PROVENANCE_SOURCE_TYPES
            and not self.source_type.startswith("x-")
        ):
            raise ValueError(
                f"unknown provenance source_type {self.source_type!r}; "
                f"use one of {sorted(_PROVENANCE_SOURCE_TYPES)} or an x- extension"
            )


@dataclass(frozen=True, slots=True)
class ContractMeta:
    """Mandatory metadata block for every cross-module persisted object.

    Field semantics follow core spec 01 §5. ``object_id`` must equal the
    owning object's canonical id field and ``tenant_id`` must equal the
    top-level tenant id of the owning object.
    """

    contract_name: str
    contract_version: str
    object_id: str
    tenant_id: str
    created_at: datetime
    producer: str
    producer_version: str
    classification: Classification = "internal"
    purpose: Purpose = ()
    provenance: tuple[ProvenanceRef, ...] = ()
    integrity_ref: str | None = None
    expires_at: datetime | None = None
    request_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None
    trace_id: str | None = None
    release_id: str | None = None
    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contract_name or not self.contract_name[0].isupper():
            raise ValueError(
                f"ContractMeta.contract_name must be a PascalCase canonical name: "
                f"{self.contract_name!r}"
            )
        if not self.contract_version:
            raise ValueError("ContractMeta.contract_version must not be empty")
        if not self.object_id:
            raise ValueError("ContractMeta.object_id must not be empty")
        if not self.tenant_id:
            raise ValueError("ContractMeta.tenant_id must not be empty")
        if not self.producer or not self.producer_version:
            raise ValueError("ContractMeta.producer/producer_version must not be empty")
        if self.expires_at is not None and self.created_at is not None:
            if self.expires_at <= self.created_at:
                raise ValueError(
                    "ContractMeta.expires_at must be strictly later than created_at"
                )
        for key in self.extensions:
            if "." not in key:
                raise ValueError(
                    f"ContractMeta.extensions keys must use a reverse-domain prefix: {key!r}"
                )

    def with_integrity(self, integrity_ref: str) -> ContractMeta:
        """Return a copy with an integrity reference set (frozen object)."""
        return ContractMeta(
            contract_name=self.contract_name,
            contract_version=self.contract_version,
            object_id=self.object_id,
            tenant_id=self.tenant_id,
            created_at=self.created_at,
            producer=self.producer,
            producer_version=self.producer_version,
            classification=self.classification,
            purpose=self.purpose,
            provenance=self.provenance,
            integrity_ref=integrity_ref,
            expires_at=self.expires_at,
            request_id=self.request_id,
            task_id=self.task_id,
            run_id=self.run_id,
            turn_id=self.turn_id,
            trace_id=self.trace_id,
            release_id=self.release_id,
            extensions=self.extensions,
        )
