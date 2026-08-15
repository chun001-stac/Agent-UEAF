"""Workflow coordinator for multi-agent handoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ueaf.ports import HandoffEnvelope, HandoffProgress, PortResult, Success


class HandoffPort(Protocol):
    """Core SPI used by the workflow coordinator to submit handoffs."""

    def submit(self, envelope: HandoffEnvelope) -> PortResult[HandoffProgress]: ...


@dataclass(slots=True)
class InMemoryWorkflowStore:
    _handoffs: dict[str, HandoffProgress] = field(default_factory=dict)

    def save(self, progress: HandoffProgress) -> HandoffProgress:
        self._handoffs[progress.handoff_id] = progress
        return progress

    def get(self, handoff_id: str) -> HandoffProgress | None:
        return self._handoffs.get(handoff_id)


class WorkflowCoordinator:
    """Coordinates handoffs between agents via the core HandoffPort."""

    def __init__(
        self, handoff_port: HandoffPort, store: InMemoryWorkflowStore | None = None
    ) -> None:
        self._handoff_port = handoff_port
        self._store = store or InMemoryWorkflowStore()

    async def submit(self, envelope: HandoffEnvelope) -> PortResult[HandoffProgress]:
        result = self._handoff_port.submit(envelope)
        if isinstance(result, Success):
            self._store.save(result.value)
        return result

    def status(self, handoff_id: str) -> HandoffProgress | None:
        return self._store.get(handoff_id)
