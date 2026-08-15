from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints

import pytest

from ueaf import ports

ROOT = Path(__file__).resolve().parents[1]


def test_p0_port_001_runtime_adapter_uses_the_normative_typed_spi() -> None:
    expected: dict[str, tuple[type[object] | None, type[object]]] = {
        "DescribeRuntime": (None, ports.RuntimeCapabilities),
        "StartRun": (ports.RuntimeStartRequest, ports.RuntimeSession),
        "AdvanceRun": (ports.RuntimeAdvanceRequest, ports.RuntimeEventStream),
        "SuspendRun": (ports.RuntimeSuspendRequest, ports.RuntimeCheckpointRef),
        "ResumeRun": (ports.RuntimeResumeRequest, ports.RuntimeSession),
        "CancelRun": (
            ports.RuntimeCancelRequest,
            ports.RuntimeCancellationObservation,
        ),
        "InspectRun": (ports.RuntimeInspectRequest, ports.RuntimeObservation),
    }

    for name, (request_type, result_type) in expected.items():
        signature = inspect.signature(getattr(ports.RuntimeAdapter, name), eval_str=True)
        request_parameters = [
            parameter
            for parameter_name, parameter in signature.parameters.items()
            if parameter_name != "self"
        ]
        if request_type is None:
            assert request_parameters == []
        else:
            assert len(request_parameters) == 1
            assert request_parameters[0].annotation is request_type
        assert signature.return_annotation is result_type


def test_p0_port_001_result_branches_preserve_side_effect_certainty() -> None:
    observed_at = datetime(2026, 8, 15, tzinfo=UTC)
    rejected_error = ports.PortError(
        code="not_authorized",
        category="policy",
        retryability="never",
        certainty="not_executed",
        message_ref=None,
        provider_error_ref=None,
        observed_at=observed_at,
        details_schema_ref=None,
    )
    unknown_error = ports.PortError(
        code="provider_timeout",
        category="transport",
        retryability="after_reconciliation",
        certainty="unknown",
        message_ref=None,
        provider_error_ref="provider-error:42",
        observed_at=observed_at,
        details_schema_ref=None,
    )

    success = ports.Success("context-manifest:1")
    rejected = ports.Rejected(rejected_error)
    unknown = ports.Unknown(unknown_error)

    assert (success.status, success.value, success.error) == (
        "success",
        "context-manifest:1",
        None,
    )
    assert (rejected.status, rejected.value, rejected.error) == (
        "rejected",
        None,
        rejected_error,
    )
    assert (unknown.status, unknown.value, unknown.error) == (
        "unknown",
        None,
        unknown_error,
    )

    with pytest.raises(ValueError, match="not_executed"):
        ports.Rejected(unknown_error)
    with pytest.raises(ValueError, match="unknown"):
        ports.Unknown(rejected_error)


@pytest.mark.test_id("RUN-008")
def test_p0_port_001_fencing_tokens_are_monotonic_positive_integers() -> None:
    for request_type in (
        ports.RuntimeExecutionContext,
        ports.RuntimeAdvanceRequest,
        ports.RuntimeSuspendRequest,
        ports.RuntimeResumeRequest,
        ports.RuntimeCancelRequest,
    ):
        assert get_type_hints(request_type)["fencing_token"] is int

    run_schema = json.loads(
        (ROOT / "schemas/runtime/run-record.schema.json").read_text(encoding="utf-8")
    )
    checkpoint_schema = json.loads(
        (ROOT / "schemas/runtime/checkpoint.schema.json").read_text(encoding="utf-8")
    )
    action_schema = json.loads(
        (ROOT / "schemas/tool/action-record.schema.json").read_text(encoding="utf-8")
    )

    assert run_schema["$defs"]["runLease"]["properties"]["fencing_token"] == {
        "type": "integer",
        "minimum": 1,
    }
    assert checkpoint_schema["$defs"]["concurrencyToken"]["properties"]["fencing_token"] == {
        "type": "integer",
        "minimum": 1,
    }
    assert action_schema["properties"]["lease_fencing_token"] == {
        "type": ["integer", "null"],
        "minimum": 1,
    }
