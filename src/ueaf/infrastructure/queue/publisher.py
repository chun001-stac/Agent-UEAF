"""Outbox publisher adapters.

The transactional outbox (CON-013) is drained by a publisher that emits each
entry at-least-once and relies on broker-level dedupe (NATS ``Nats-Msg-Id`` or
an in-memory event_id set) so consumers see exactly-once semantics. Publishing
succeeds only after the broker accepts the message; the outbox row is then
marked published.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from ueaf.common.envelope import EventEnvelope
from ueaf.common.identifiers import utcnow
from ueaf.runtime.outbox import OutboxEntry, OutboxStore


class OutboxPublisher(Protocol):
    async def publish(self, entry: OutboxEntry) -> bool: ...

    async def drain(self, outbox: OutboxStore) -> int: ...


def _to_envelope(entry: OutboxEntry) -> EventEnvelope:
    return EventEnvelope(
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
        producer="ueaf-outbox-publisher",
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


class InMemoryOutboxPublisher:
    """Test/local publisher: dedupes by event_id, keeps delivered envelopes."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.events: list[EventEnvelope] = []

    async def publish(self, entry: OutboxEntry) -> bool:
        if entry.event_id in self._seen:
            return False
        self._seen.add(entry.event_id)
        self.events.append(_to_envelope(entry))
        return True

    async def drain(self, outbox: OutboxStore) -> int:
        count = 0
        for entry in await outbox.unpublished():
            if await self.publish(entry):
                await outbox.mark_published(entry.event_id, utcnow())
                count += 1
        return count


class NatsJetStreamOutboxPublisher:
    """Publishes outbox entries to a NATS JetStream stream.

    ``js`` is a JetStream context (nats.js). Each message carries the
    ``Nats-Msg-Id`` header set to the event id so JetStream server-side
    deduplication drops redeliveries within the stream's dedup window. The
    ``nats`` dependency is imported lazily so the module imports without it.
    """

    def __init__(self, js: object, *, subject_prefix: str = "ueaf.events") -> None:
        self._js = js
        self._subject_prefix = subject_prefix

    async def publish(self, entry: OutboxEntry) -> bool:
        _import_nats()  # ensure the dependency is present before publishing
        subject = f"{self._subject_prefix}.{entry.event_name}"
        body = json.dumps(
            dataclasses.asdict(_to_envelope(entry)), default=str
        ).encode("utf-8")
        ack = await self._js.publish(  # type: ignore[attr-defined]
            subject, body, headers={"Nats-Msg-Id": entry.event_id}
        )
        # Server-side dedup: a duplicate message id is acknowledged but not stored.
        if getattr(ack, "duplicate", False) or (
            hasattr(ack, "info") and getattr(ack.info, "duplicate", False)
        ):
            return False
        return True

    async def drain(self, outbox: OutboxStore) -> int:
        count = 0
        for entry in await outbox.unpublished():
            if await self.publish(entry):
                await outbox.mark_published(entry.event_id, utcnow())
                count += 1
        return count


def _import_nats() -> Any:
    try:
        import nats
    except ImportError as error:  # pragma: no cover
        raise RuntimeError(
            "nats-py is required for the NATS JetStream outbox publisher"
        ) from error
    return nats
