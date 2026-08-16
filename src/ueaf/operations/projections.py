"""基于权威运行事件构建的 RunSummary 投影（默认 0 LLM）。

仅投影：绝不是状态写入方，绝不决定终态。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ueaf.common.envelope import EventEnvelope


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    tenant_id: str
    task_id: str | None = None
    phase: str | None = None
    disposition: str | None = None
    attempt: int | None = None
    revision: int | None = None
    event_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    wait_reason: str | None = None
    release_id: str | None = None


@dataclass(slots=True)
class RunSummaryProjector:
    """通过折叠运行域事件推导运行摘要（确定性）。"""

    _summaries: dict[str, RunSummary] = field(default_factory=dict)

    def apply(self, event: EventEnvelope) -> RunSummary:
        if event.aggregate_type != "RunRecord":
            return self._summaries.get(
                event.aggregate_id, RunSummary(run_id=event.aggregate_id, tenant_id=event.tenant_id)
            )
        current = self._summaries.get(
            event.aggregate_id, RunSummary(run_id=event.aggregate_id, tenant_id=event.tenant_id)
        )
        payload: Mapping[str, Any] = event.payload
        phase = current.phase
        if event.event_name == "ueaf.run.phase_changed":
            phase = payload.get("to_phase", current.phase)
        disposition = current.disposition
        if event.event_name == "ueaf.run.terminal_committed":
            disposition = payload.get("disposition", current.disposition)
        wait_reason = current.wait_reason
        if event.event_name == "ueaf.run.wait_registered":
            wait_reason = payload.get("wait_reason", current.wait_reason)
        attempt = current.attempt
        if event.event_name == "ueaf.run.retry_scheduled":
            attempt = payload.get("attempt", current.attempt)
        summary = RunSummary(
            run_id=event.aggregate_id,
            tenant_id=event.tenant_id,
            task_id=payload.get("task_id", current.task_id),
            phase=phase,
            disposition=disposition,
            attempt=attempt,
            revision=event.aggregate_version,
            event_count=current.event_count + 1,
            first_event_at=current.first_event_at or event.occurred_at,
            last_event_at=event.occurred_at,
            wait_reason=wait_reason,
            release_id=event.release_id,
        )
        self._summaries[event.aggregate_id] = summary
        return summary

    def get(self, run_id: str) -> RunSummary | None:
        return self._summaries.get(run_id)
