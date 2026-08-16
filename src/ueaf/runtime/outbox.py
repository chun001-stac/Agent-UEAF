"""权威状态/事件原子性的事务性 outbox（CON-013）。

业务行变更与 outbox 插入在同一本地事务中完成。发布者按序消费条目，并将不可变的
``EventEnvelope`` 实例发送到 broker/事件总线（at-least-once 语义，按 ``event_id``
去重）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ueaf.common.envelope import EventEnvelope
from ueaf.common.meta import Classification, Purpose


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    outbox_id: str
    event_id: str
    event_name: str
    event_version: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    sequence: int
    correlation_id: str
    trace_id: str
    payload_schema_ref: str
    payload: dict[str, object]
    created_at: datetime
    release_id: str | None = None
    principal_ref: str | None = None
    causation_id: str | None = None
    classification: Classification = "internal"
    purpose: Purpose = ()
    integrity_ref: str | None = None
    published_at: datetime | None = None
    attempt_count: int = 0


class OutboxStore(Protocol):
    async def append(self, entry: OutboxEntry) -> None: ...

    async def unpublished(self) -> list[OutboxEntry]: ...

    async def mark_published(self, event_id: str, at: datetime) -> None: ...

    async def dedupe_event_id(self, event_id: str) -> bool: ...


class InMemoryOutboxStore:
    """内存 outbox；适用于测试和单进程垂直切片。"""

    def __init__(self) -> None:
        self._entries: list[OutboxEntry] = []
        self._by_event_id: set[str] = set()
        self._published: set[str] = set()

    async def append(self, entry: OutboxEntry) -> None:
        if entry.event_id in self._by_event_id:
            raise ValueError(f"duplicate outbox event_id {entry.event_id}")
        self._by_event_id.add(entry.event_id)
        self._entries.append(entry)

    async def unpublished(self) -> list[OutboxEntry]:
        return [
            entry for entry in self._entries if entry.event_id not in self._published
        ]

    async def mark_published(self, event_id: str, at: datetime | None = None) -> None:
        if event_id not in self._by_event_id:
            raise KeyError(f"no outbox entry for {event_id}")
        self._published.add(event_id)

    async def dedupe_event_id(self, event_id: str) -> bool:
        return event_id in self._published

    def published_events(self) -> list[OutboxEntry]:
        return [entry for entry in self._entries if entry.event_id in self._published]


class InMemoryEventBus:
    """测试/本地事件总线：将 outbox 条目消费为 EventEnvelope。"""

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []
        self._seen: set[str] = set()

    def publish(self, entry: OutboxEntry) -> bool:
        if entry.event_id in self._seen:
            return False  # 按 event_id 去重（at-least-once）
        self._seen.add(entry.event_id)
        self.events.append(
            EventEnvelope(
                event_id=entry.event_id,
                event_name=entry.event_name,
                event_version=entry.event_version,
                occurred_at=entry.created_at,
                recorded_at=entry.published_at or datetime.now(UTC),
                tenant_id=entry.tenant_id,
                aggregate_type=entry.aggregate_type,
                aggregate_id=entry.aggregate_id,
                aggregate_version=entry.aggregate_version,
                sequence=entry.sequence,
                producer="ueaf-runtime",
                producer_version="0.1.0",
                correlation_id=entry.correlation_id,
                causation_id=entry.causation_id,
                trace_id=entry.trace_id,
                principal_ref=entry.principal_ref,
                release_id=entry.release_id,
                payload_schema_ref=entry.payload_schema_ref,
                payload=entry.payload,
                classification=entry.classification,
                purpose=entry.purpose,
                integrity_ref=entry.integrity_ref,
            )
        )
        return True
