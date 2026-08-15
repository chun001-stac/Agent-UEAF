"""TelemetryPort reference implementation (EVD-005).

Only the core ``EmitTrace/EmitMetric/EmitLog/EmitAudit`` semantics are exposed.
High-cardinality ids are never used as metric labels (EVD-002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ueaf.ports import (
    AuditCommitReceipt,
    AuditRecord,
    LogRecord,
    MetricPoint,
    PortResult,
    Success,
    TelemetryAck,
    TraceRecord,
)


@dataclass(slots=True)
class InMemoryTelemetryCollector:
    """Collects telemetry in-memory for evidence mapping and audits."""

    traces: list[TraceRecord] = field(default_factory=list)
    metrics: list[MetricPoint] = field(default_factory=list)
    logs: list[LogRecord] = field(default_factory=list)
    audits: list[AuditRecord] = field(default_factory=list)
    _dedupe: set[str] = field(default_factory=set)

    def EmitTrace(self, record: TraceRecord) -> PortResult[TelemetryAck]:
        self.traces.append(record)
        return Success(TelemetryAck(accepted_count=1, observed_at=datetime.now(UTC)))

    def EmitMetric(self, points: list[MetricPoint]) -> PortResult[TelemetryAck]:
        self.metrics.extend(points)
        return Success(TelemetryAck(accepted_count=len(points), observed_at=datetime.now(UTC)))

    def EmitLog(self, records: list[LogRecord]) -> PortResult[TelemetryAck]:
        self.logs.extend(records)
        return Success(TelemetryAck(accepted_count=len(records), observed_at=datetime.now(UTC)))

    def EmitAudit(self, record: AuditRecord) -> PortResult[AuditCommitReceipt]:
        if record.audit_record_id in self._dedupe:
            return Success(
                AuditCommitReceipt(
                    audit_record_id=record.audit_record_id,
                    commit_ref=f"commit:{record.audit_record_id}",
                    committed_at=record.occurred_at,
                    integrity_ref=record.integrity_ref,
                )
            )
        self._dedupe.add(record.audit_record_id)
        self.audits.append(record)
        return Success(
            AuditCommitReceipt(
                audit_record_id=record.audit_record_id,
                commit_ref=f"commit:{record.audit_record_id}",
                committed_at=record.occurred_at,
                integrity_ref=record.integrity_ref,
            )
        )
