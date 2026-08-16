"""多 agent 交接的工作流协调器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ueaf.ports import HandoffEnvelope, HandoffProgress, PortResult, Success


class HandoffPort(Protocol):
    """工作流协调器用于提交交接的核心 SPI。"""

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
    """通过核心 HandoffPort 协调 agent 之间的交接。"""

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
