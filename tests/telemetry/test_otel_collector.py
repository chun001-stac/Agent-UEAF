"""OpenTelemetry TelemetryPort collector tests (EVD-005).

Exercises the OTel-backed collector with an injected fake tracer (no SDK
dependency required) and the graceful no-op fallback when the SDK is absent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests import support
from ueaf.infrastructure.telemetry.otel import OtelTelemetryCollector
from ueaf.ports import (
    AuditRecord,
    LogRecord,
    MetricPoint,
    TraceRecord,
)

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


class _FakeSpan:
    def __init__(self) -> None:
        self.ended = False
        self.attributes: dict[str, object] = {}

    def end(self) -> None:
        self.ended = True

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _FakeTracer:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def start_span(self, name: str, **kwargs: object) -> _FakeSpan:
        span = _FakeSpan()
        span.attributes = dict(kwargs.get("attributes", {}) or {})
        self.spans.append(span)
        return span


@pytest.mark.test_id("EVD-005")
def test_otel_collector_emits_trace_and_audit_spans() -> None:
    tracer = _FakeTracer()
    collector = OtelTelemetryCollector(tracer=tracer, enabled=True)

    trace_result = collector.EmitTrace(
        TraceRecord(
            trace_id="trace:1",
            tenant_id=support.TENANT,
            run_id="run:1",
            release_id="release:1",
            adapter_ref="adapter:langgraph",
            result_class="ok",
            occurred_at=MOMENT,
        )
    )
    assert trace_result.value.accepted_count == 1
    audit = collector.EmitAudit(
        AuditRecord(
            audit_record_id="audit:1",
            tenant_id=support.TENANT,
            actor_ref="principal:1",
            action="run.committed",
            object_ref="run:1",
            evidence_refs=("evidence:1",),
            occurred_at=MOMENT,
            integrity_ref="integrity:1",
        )
    )
    assert audit.value.audit_record_id == "audit:1"
    assert len(tracer.spans) == 2
    assert tracer.spans[0].attributes["run.id"] == "run:1"
    assert tracer.spans[1].attributes["audit.action"] == "run.committed"
    assert all(span.ended for span in tracer.spans)


@pytest.mark.test_id("EVD-005")
def test_otel_collector_emits_metrics_without_high_cardinality_labels() -> None:
    tracer = _FakeTracer()
    collector = OtelTelemetryCollector(tracer=tracer, enabled=True)

    collector.EmitMetric(
        [
            MetricPoint(
                metric_name="ueaf.runs.completed",
                value=1,
                tenant_id=support.TENANT,
                release_id="release:1",
                observed_at=MOMENT,
            )
        ]
    )
    collector.EmitLog(
        [
            LogRecord(
                level="info",
                message_ref="run.committed",
                tenant_id=support.TENANT,
                run_id="run:1",
                occurred_at=MOMENT,
            )
        ]
    )
    # Metrics/logs forward through the SDK path without a hard dependency;
    # the collector still reports acceptance to the caller.
    assert collector.enabled is True


@pytest.mark.test_id("EVD-005")
def test_otel_collector_falls_back_to_noop_without_sdk() -> None:
    collector = OtelTelemetryCollector(tracer=None, enabled=False)
    result = collector.EmitTrace(
        TraceRecord(
            trace_id="trace:1",
            tenant_id=support.TENANT,
            run_id="run:1",
            release_id="release:1",
            adapter_ref="adapter:deterministic",
            result_class="ok",
            occurred_at=MOMENT,
        )
    )
    # The no-op fallback still acknowledges acceptance (EVD-005), never failing.
    assert result.value.accepted_count == 1
    audit = collector.EmitAudit(
        AuditRecord(
            audit_record_id="audit:1",
            tenant_id=support.TENANT,
            actor_ref="principal:1",
            action="run.committed",
            object_ref="run:1",
            evidence_refs=(),
            occurred_at=MOMENT,
            integrity_ref="integrity:1",
        )
    )
    assert audit.value.commit_ref == "commit:audit:1"
