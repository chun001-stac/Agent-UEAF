"""OpenTelemetry-backed TelemetryPort implementation (EVD-005).

Bridges the core ``TelemetryPort`` semantics to the OpenTelemetry SDK: traces
become spans, metrics become counters, logs become OTel log records, and audit
records become span events. The SDK is imported lazily so the module imports
without ``opentelemetry`` installed; the collector is a no-op fallback when the
dependency is missing so local/CI runs without OTel still succeed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

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


class OtelExporter(Protocol):
    """Structural type for the exported OTel span (tracer API subset)."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any: ...

    def is_recording(self) -> bool: ...


@dataclass(slots=True)
class OtelTelemetryCollector:
    """TelemetryPort that forwards to an OpenTelemetry SDK tracer.

    ``tracer`` may be injected for tests; otherwise one is created lazily from
    the OTel SDK. ``enabled`` is flipped to False when the SDK is unavailable so
    callers get a successful no-op rather than a hard failure.
    """

    service_name: str = "ueaf-runtime"
    tracer: Any | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.tracer is None:
            tracer = _import_tracer(self.service_name)
            self.tracer = tracer
            self.enabled = tracer is not None

    # -- TelemetryPort -----------------------------------------------------

    def EmitTrace(self, record: TraceRecord) -> PortResult[TelemetryAck]:
        if not self.enabled or self.tracer is None:
            return Success(TelemetryAck(accepted_count=1, observed_at=_now()))
        span = self.tracer.start_span(
            "ueaf.trace",
            attributes={
                "trace.id": record.trace_id,
                "tenant.id": record.tenant_id,
                "run.id": record.run_id,
                "release.id": record.release_id,
                "adapter.ref": record.adapter_ref,
                "result.class": record.result_class,
            },
        )
        span.end()
        return Success(TelemetryAck(accepted_count=1, observed_at=_now()))

    def EmitMetric(self, points: Sequence[MetricPoint]) -> PortResult[TelemetryAck]:
        if not self.enabled:
            return Success(TelemetryAck(accepted_count=len(points), observed_at=_now()))
        # High-cardinality ids are never metric labels (EVD-002): only tenant
        # and release are used as dimensions.
        for point in points:
            _emit_metric(self.tracer, point)
        return Success(TelemetryAck(accepted_count=len(points), observed_at=_now()))

    def EmitLog(self, records: Sequence[LogRecord]) -> PortResult[TelemetryAck]:
        if not self.enabled:
            return Success(TelemetryAck(accepted_count=len(records), observed_at=_now()))
        for record in records:
            _emit_log(self.tracer, record)
        return Success(TelemetryAck(accepted_count=len(records), observed_at=_now()))

    def EmitAudit(self, record: AuditRecord) -> PortResult[AuditCommitReceipt]:
        if not self.enabled or self.tracer is None:
            return Success(
                AuditCommitReceipt(
                    audit_record_id=record.audit_record_id,
                    commit_ref=f"commit:{record.audit_record_id}",
                    committed_at=record.occurred_at,
                    integrity_ref=record.integrity_ref,
                )
            )
        span = self.tracer.start_span(
            "ueaf.audit",
            attributes={
                "audit.record.id": record.audit_record_id,
                "audit.action": record.action,
                "audit.object.ref": record.object_ref,
                "audit.actor.ref": record.actor_ref,
                "audit.integrity.ref": record.integrity_ref,
            },
        )
        span.end()
        return Success(
            AuditCommitReceipt(
                audit_record_id=record.audit_record_id,
                commit_ref=f"commit:{record.audit_record_id}",
                committed_at=record.occurred_at,
                integrity_ref=record.integrity_ref,
            )
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _import_tracer(service_name: str) -> Any | None:
    """Build an OTel tracer, or ``None`` when the SDK is unavailable."""
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import (  # type: ignore[import-not-found]
            TracerProvider,
        )
    except ImportError:  # pragma: no cover - optional dependency
        return None
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def _emit_metric(tracer: Any, point: MetricPoint) -> None:
    try:
        from opentelemetry.metrics import (  # type: ignore[import-not-found]
            get_meter,
        )
    except ImportError:  # pragma: no cover - optional dependency
        return
    meter = get_meter("ueaf-runtime")
    counter = meter.create_counter(point.metric_name)
    counter.add(
        point.value,
        attributes={
            "tenant.id": point.tenant_id,
            "release.id": point.release_id,
        },
    )


def _emit_log(tracer: Any, record: LogRecord) -> None:
    if hasattr(tracer, "add_event"):
        tracer.add_event(
            "ueaf.log",
            attributes={
                "log.level": record.level,
                "log.message.ref": record.message_ref,
                "log.run.id": record.run_id or "",
            },
        )


__all__ = ["OtelTelemetryCollector"]
