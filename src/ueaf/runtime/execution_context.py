"""Runtime execution context assembly (core spec 04 §4.2, functional module 02).

Builds a ``RuntimeExecutionContext`` exposing only the whitelisted ports; the
adapter never receives raw credentials or a direct state store.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ueaf.ports import (
    ContextBuildPort,
    HandoffPort,
    ModelStepPort,
    RuntimeExecutionContext,
    TelemetryPort,
    ToolIntentPort,
)
from ueaf.runtime.objects import RunRecord


def build_execution_context(
    run: RunRecord,
    *,
    trace_id: str,
    fencing_token: int,
    context_build_port: ContextBuildPort,
    model_step_port: ModelStepPort,
    tool_intent_port: ToolIntentPort,
    handoff_port: HandoffPort,
    telemetry_port: TelemetryPort,
) -> RuntimeExecutionContext:
    """Assemble the minimal capability context for a run session."""
    return RuntimeExecutionContext(
        tenant_id=run.meta.tenant_id,
        run_id=run.run_id,
        release_id=run.release_id,
        trace_id=trace_id,
        revision=run.revision,
        fencing_token=fencing_token,
        deadline_at=run.deadline_at or datetime.now(UTC),
        cancellation_ref=f"cancel:{run.run_id}",
        context_build_port=context_build_port,
        model_step_port=model_step_port,
        tool_intent_port=tool_intent_port,
        handoff_port=handoff_port,
        telemetry_port=telemetry_port,
    )
