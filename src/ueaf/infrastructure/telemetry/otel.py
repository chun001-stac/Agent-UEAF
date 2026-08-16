"""基于 OpenTelemetry 的 TelemetryPort 实现（EVD-005）。

将核心 ``TelemetryPort`` 语义桥接到 OpenTelemetry SDK：trace 变为 span，指标
变为计数器，日志变为 OTel 日志记录，审计记录变为 span 事件。SDK 为懒导入，
因此未安装 ``opentelemetry`` 时模块仍可导入；依赖缺失时收集器是 no-op 回退，
使没有 OTel 的本地/CI 运行依然成功。
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
    """导出的 OTel span 的结构化类型（tracer API 子集）。"""

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any: ...

    def is_recording(self) -> bool: ...


@dataclass(slots=True)
class OtelTelemetryCollector:
    """转发到 OpenTelemetry SDK tracer 的 TelemetryPort。

    ``tracer`` 可注入以用于测试；否则会从 OTel SDK 懒创建。当 SDK 不可用时
    ``enabled`` 被置为 False，使调用方得到成功的 no-op 而不是硬失败。
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
        # 高基数 id 绝不用作指标标签（EVD-002）：仅 tenant
        # 与 release 用作维度。
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
    """构建 OTel tracer，SDK 不可用时返回 ``None``。"""
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
