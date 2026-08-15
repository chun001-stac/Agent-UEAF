"""Command / Event envelope contracts (core spec 03).

There is exactly one public ``EventEnvelope`` and one ``CommandEnvelope`` in
V1; no reduced variants may be created.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ueaf.common.meta import Classification, Purpose

EVENT_NAME_PATTERN = re.compile(r"^ueaf\.[a-z0-9_]+\.[a-z0-9_]+$")
COMMAND_NAME_PATTERN = re.compile(r"^ueaf\.[a-z0-9_]+\.[a-z0-9_]+$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    """A command targeting a canonical aggregate."""

    command_id: str
    command_name: str
    command_version: str
    issued_at: datetime
    deadline_at: datetime
    tenant_id: str
    actor_ref: str
    target_type: str
    target_id: str | None
    expected_revision: int | None
    idempotency_key: str
    correlation_id: str
    trace_id: str
    payload_schema_ref: str
    payload: Mapping[str, object]
    causation_id: str | None = None
    release_id: str | None = None
    classification: Classification = "internal"
    purpose: Purpose = ()
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        if not COMMAND_NAME_PATTERN.fullmatch(self.command_name):
            raise ValueError(f"invalid command_name {self.command_name!r}")
        if not SEMVER_PATTERN.fullmatch(self.command_version):
            raise ValueError(f"invalid command_version {self.command_version!r}")
        if self.deadline_at is not None and self.issued_at is not None:
            if self.deadline_at <= self.issued_at:
                raise ValueError("CommandEnvelope.deadline_at must be later than issued_at")
        if not self.idempotency_key:
            raise ValueError("CommandEnvelope.idempotency_key must not be empty")
        if not self.target_type or not self.target_type[0].isupper():
            raise ValueError(f"invalid target_type {self.target_type!r}")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """The single public event envelope; consumers dedupe on ``event_id``."""

    event_id: str
    event_name: str
    event_version: str
    occurred_at: datetime
    recorded_at: datetime
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    sequence: int
    producer: str
    producer_version: str
    correlation_id: str
    trace_id: str
    payload_schema_ref: str
    payload: Mapping[str, object]
    causation_id: str | None = None
    principal_ref: str | None = None
    release_id: str | None = None
    classification: Classification = "internal"
    purpose: Purpose = ()
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        if not EVENT_NAME_PATTERN.fullmatch(self.event_name):
            raise ValueError(f"invalid event_name {self.event_name!r}")
        if not SEMVER_PATTERN.fullmatch(self.event_version):
            raise ValueError(f"invalid event_version {self.event_version!r}")
        if self.aggregate_version < 1:
            raise ValueError("EventEnvelope.aggregate_version must be >= 1")
        if self.sequence < 1:
            raise ValueError("EventEnvelope.sequence must be >= 1")
        if not self.aggregate_type or not self.aggregate_type[0].isupper():
            raise ValueError(f"invalid aggregate_type {self.aggregate_type!r}")


@dataclass(frozen=True, slots=True)
class EventCatalogEntry:
    event_name: str
    event_version: str
    payload_schema_ref: str
    aggregate_type: str
    producer: str


@dataclass(frozen=True, slots=True)
class EventCatalog:
    """The registered public event set; it is not a second semantic owner."""

    catalog_version: str
    entries: tuple[EventCatalogEntry, ...] = field(default_factory=tuple)

    def resolve(self, event_name: str, event_version: str) -> EventCatalogEntry:
        for entry in self.entries:
            if entry.event_name == event_name and entry.event_version == event_version:
                return entry
        raise KeyError(f"event {event_name}@{event_version} is not registered")

    def names(self) -> frozenset[str]:
        return frozenset(entry.event_name for entry in self.entries)
