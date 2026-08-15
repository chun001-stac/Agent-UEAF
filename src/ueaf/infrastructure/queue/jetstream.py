"""NATS JetStream bootstrap + consumer with sequence-gap detection.

The transactional outbox (CON-013) is drained by a publisher; subscribers need a
durable JetStream consumer so a restarted worker resumes exactly where it left
off. ``JetStreamConsumer`` tracks per-stream sequence numbers and reports gaps
(``SequenceGap``) when a message's stream sequence jumps ahead of the last
delivered one — a signal that deliveries were missed and reconciliation is
required before the consumer blindly processes the next event.

The ``nats`` dependency is imported lazily so the module imports without it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ueaf.common.envelope import EventEnvelope


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """JetStream stream configuration used for idempotent bootstrap."""

    name: str = "UEAF_EVENTS"
    subjects: tuple[str, ...] = ("ueaf.events.*",)
    max_age_seconds: int = 86400  # 24h
    max_msgs: int = 100_000
    dedup_window_seconds: int = 120  # server-side dedup window (Nats-Msg-Id)


@dataclass(frozen=True, slots=True)
class SequenceGap:
    """Detected delivery gap: a stream sequence was skipped."""

    subject: str
    expected_sequence: int
    observed_sequence: int
    event_id: str | None


@dataclass(slots=True)
class ConsumerStats:
    deliveries: int = 0
    duplicates: int = 0
    gaps: list[SequenceGap] = field(default_factory=list)
    last_sequence: int | None = None


class JetStreamConsumer:
    """Durable consumer over a JetStream stream with sequence-gap detection."""

    def __init__(self, nc: object, js: object, *, stream: StreamConfig | None = None) -> None:
        self._nc = nc
        self._js = js
        self._stream = stream or StreamConfig()
        self.stats = ConsumerStats()

    async def bootstrap_stream(self) -> Any:
        """Create the stream if absent; returns the stream info object."""
        try:
            return await self._js.stream_info(  # type: ignore[attr-defined]
                self._stream.name
            )
        except Exception:
            await self._js.add_stream(  # type: ignore[attr-defined]
                name=self._stream.name,
                subjects=list(self._stream.subjects),
                max_age=self._stream.max_age_seconds,
                max_msgs=self._stream.max_msgs,
                duplicate_window=self._stream.dedup_window_seconds,
            )
            return await self._js.stream_info(  # type: ignore[attr-defined]
                self._stream.name
            )

    async def consumer_info(self, consumer_name: str) -> Any:
        """Return the durable consumer info or ``None`` if it does not exist."""
        try:
            return await self._js.consumer_info(  # type: ignore[attr-defined]
                self._stream.name, consumer_name
            )
        except Exception:
            return None

    async def subscribe(
        self, consumer_name: str, *, durable: bool = True
    ) -> AsyncIterator[tuple[EventEnvelope, int]]:
        """Subscribe; yields ``(event, stream_sequence)`` per delivered message.

        Duplicates (JetStream ``redelivered``) are counted and skipped; a
        forward sequence jump is recorded as a ``SequenceGap`` but the message
        is still yielded so the caller can decide to reconcile or skip.
        """
        kwargs = {}
        if durable:
            kwargs["durable"] = consumer_name
        sub = await self._js.subscribe(  # type: ignore[attr-defined]
            *self._stream.subjects, stream=self._stream.name, **kwargs
        )
        try:
            while True:
                msg = await sub.next_msg(timeout=0.5)
                meta = getattr(msg, "metadata", None)
                stream_seq = getattr(meta, "sequence", None)
                seq = int(stream_seq.stream) if stream_seq is not None else 0
                if self.stats.last_sequence is not None and seq <= self.stats.last_sequence:
                    self.stats.duplicates += 1
                    await msg.ack()
                    continue
                if self.stats.last_sequence is not None and seq > self.stats.last_sequence + 1:
                    self.stats.gaps.append(
                        SequenceGap(
                            subject=msg.subject,
                            expected_sequence=self.stats.last_sequence + 1,
                            observed_sequence=seq,
                            event_id=None,
                        )
                    )
                self.stats.last_sequence = seq
                self.stats.deliveries += 1
                await msg.ack()
                yield _decode_event(msg.data), seq
        except TimeoutError:
            return
        finally:
            try:
                await sub.unsubscribe()
            except Exception:
                pass

    async def fetch(
        self, consumer_name: str, *, max_events: int = 16, timeout: float = 1.0
    ) -> list[tuple[EventEnvelope, int]]:
        """Collect up to ``max_events`` events, then unsubscribe."""
        events: list[tuple[EventEnvelope, int]] = []
        async for event, seq in self.subscribe(consumer_name, durable=True):
            events.append((event, seq))
            if len(events) >= max_events:
                break
        return events


def _decode_event(data: bytes) -> EventEnvelope:
    import json

    from ueaf.infrastructure.queue.publisher import _envelope_from_dict

    payload = json.loads(data.decode("utf-8"))
    return _envelope_from_dict(payload)


__all__ = [
    "StreamConfig",
    "SequenceGap",
    "ConsumerStats",
    "JetStreamConsumer",
]
