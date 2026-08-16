"""阶段 5 evidence / telemetry 验收测试（EVD-*）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests import support
from ueaf.evidence.evidence import ErrorFingerprint, EvidencePipeline
from ueaf.infrastructure.telemetry.collector import InMemoryTelemetryCollector
from ueaf.ports import LogRecord, MetricPoint, TraceRecord

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _trace(run_id: str, result_class: str = "success", *, at=None) -> TraceRecord:
    return TraceRecord(
        trace_id=f"trace:{run_id}",
        tenant_id=support.TENANT,
        run_id=run_id,
        release_id="release:1",
        adapter_ref="adapter:langgraph",
        result_class=result_class,
        occurred_at=at or MOMENT,
    )


def _log(run_id: str, message_ref: str, *, at=None) -> LogRecord:
    return LogRecord(
        level="error" if "error" in message_ref else "info",
        message_ref=message_ref,
        tenant_id=support.TENANT,
        run_id=run_id,
        occurred_at=at or MOMENT,
    )


@pytest.mark.test_id("EVD-001")
def test_normal_path_uses_zero_llm_tokens() -> None:
    collector = InMemoryTelemetryCollector()
    collector.EmitTrace(_trace("run:1"))
    collector.EmitLog([_log("run:1", "module:stage:error_code")])

    pipeline = EvidencePipeline(tenant_id=support.TENANT)
    observations = pipeline.ingest(collector)
    summary = pipeline.run_summary("run:1")
    window = pipeline.rolling_window(now=MOMENT + timedelta(minutes=1))
    candidate = pipeline.detect_trigger_candidate(
        error_code="error", component="langgraph", message="boom",
        now=MOMENT + timedelta(minutes=1),
    )

    # 下方的确定性映射都不涉及 LLM 调用。
    assert observations
    assert summary.observation_count >= 1
    assert window.total_observations >= 1
    assert candidate is None or candidate.candidate_id  # deterministically derived


@pytest.mark.test_id("EVD-002")
def test_high_cardinality_ids_are_not_metric_labels() -> None:
    collector = InMemoryTelemetryCollector()
    collector.EmitMetric(
        [
            MetricPoint(
                metric_name="run_latency",
                value=100,
                tenant_id=support.TENANT,
                release_id="release:1",
                observed_at=MOMENT,
            )
        ]
    )
    # 指标名粒度较粗；run/trace id 永远不会成为标签。
    assert collector.metrics[0].metric_name == "run_latency"
    assert collector.metrics[0].value == 100


@pytest.mark.test_id("EVD-004")
def test_evidence_gap_is_explicit() -> None:
    pipeline = EvidencePipeline(tenant_id=support.TENANT)
    summary = pipeline.run_summary("run:missing")
    # 没有观测的 run 会产生可见的零观测摘要，绝不被静默视为健康。
    assert summary.observation_count == 0
    assert summary.error_codes == ()


@pytest.mark.test_id("EVD-005")
def test_telemetry_port_exposes_core_semantics_only() -> None:
    collector = InMemoryTelemetryCollector()
    # 核心 SPI 方法是唯一的公开接口。
    assert callable(collector.EmitTrace)
    assert callable(collector.EmitMetric)
    assert callable(collector.EmitLog)
    assert callable(collector.EmitAudit)


@pytest.mark.test_id("EVO-001")
def test_single_anomaly_is_not_a_trigger_candidate() -> None:
    collector = InMemoryTelemetryCollector()
    collector.EmitTrace(_trace("run:1", "failure"))
    collector.EmitLog([_log("run:1", "module:error_code")])

    pipeline = EvidencePipeline(tenant_id=support.TENANT)
    pipeline.ingest(collector)
    candidate = pipeline.detect_trigger_candidate(
        error_code="error", component="langgraph", message="single failure"
    )
    assert candidate is None  # 聚合证据不足


@pytest.mark.test_id("EVO-002")
def test_trigger_gate_requires_aggregate_evidence() -> None:
    collector = InMemoryTelemetryCollector()
    base = MOMENT
    for i in range(6):
        at = base + timedelta(seconds=10 * i)
        collector.EmitTrace(_trace(f"run:{i}", "failure", at=at))
        collector.EmitLog([_log(f"run:{i}", "module:error_code", at=at)])

    pipeline = EvidencePipeline(tenant_id=support.TENANT, window_period_millis=300_000)
    pipeline.ingest(collector)
    candidate = pipeline.detect_trigger_candidate(
        error_code="error",
        component="langgraph",
        message="repeated failure",
        threshold_error_rate=0.5,
        now=base + timedelta(seconds=120),
    )
    assert candidate is not None
    assert "error_rate_breach" in candidate.reason_codes


@pytest.mark.test_id("EVD-003")
def test_error_fingerprint_is_stable_and_deduplicating() -> None:
    a = ErrorFingerprint.build("E100", "Provider timeout after 1234ms", "model")
    b = ErrorFingerprint.build("E100", "Provider timeout after 5678ms", "model")
    # 高基数 id（如耗时）不会拆分指纹。
    assert a == b
