"""Failure-injection utilities for recovery / resilience tests (P2-B).

A ``FailureInjector`` controls where a scenario should fail next, and
``FailingOutboxStore`` wraps an outbox so a broker/DB fault can be simulated
mid-transaction. These are used by the formal ``tests/failure_injection`` suite
to prove atomic rollback (CON-013), fencing (RUN-003), timeout-unknown
reconciliation (ACT-003) and at-least-once redelivery (ACT-013).
"""

from __future__ import annotations

from typing import Any

from ueaf.runtime.outbox import OutboxEntry, OutboxStore


class FailureInjector:
    """Deterministic fault switch: fail the next N matching operations."""

    def __init__(self) -> None:
        self._fail_remaining: dict[str, int] = {}
        self._triggered: list[str] = []

    def fail_next(self, point: str, *, count: int = 1) -> None:
        if count < 1:
            raise ValueError("count must be >= 1")
        self._fail_remaining[point] = self._fail_remaining.get(point, 0) + count

    def should_fail(self, point: str) -> bool:
        remaining = self._fail_remaining.get(point, 0)
        if remaining <= 0:
            return False
        self._fail_remaining[point] = remaining - 1
        self._triggered.append(point)
        return True

    @property
    def triggered(self) -> list[str]:
        return list(self._triggered)

    def reset(self) -> None:
        self._fail_remaining.clear()
        self._triggered.clear()


class FailingOutboxStore:
    """Wraps an outbox store and raises on ``append`` when the injector fires."""

    def __init__(self, inner: OutboxStore, injector: FailureInjector) -> None:
        self._inner = inner
        self._injector = injector

    async def append(self, entry: OutboxEntry) -> None:
        if self._injector.should_fail("outbox.append"):
            raise RuntimeError("injected outbox append failure")
        await self._inner.append(entry)

    async def unpublished(self) -> list[OutboxEntry]:
        return await self._inner.unpublished()

    async def mark_published(self, event_id: str, at: Any = None) -> None:
        await self._inner.mark_published(event_id, at)

    async def dedupe_event_id(self, event_id: str) -> bool:
        return await self._inner.dedupe_event_id(event_id)


__all__ = ["FailureInjector", "FailingOutboxStore"]
