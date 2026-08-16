"""FastAPI 控制面测试：edge -> run -> admission -> commands。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests import support
from ueaf.admission.edge import EdgePreValidator
from ueaf.api.app import ApiContext, create_app
from ueaf.infrastructure.db.repositories import (
    Clock,
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.runtime.coordinator import RunCoordinator
from ueaf.runtime.outbox import InMemoryOutboxStore

TENANT = support.TENANT


def _client() -> TestClient:
    runs = InMemoryRunRecordRepository()
    tasks = InMemoryTaskStateRepository()
    admissions = InMemoryAdmissionResultRepository()
    outbox = InMemoryOutboxStore()
    coordinator = RunCoordinator(
        runs, tasks, admissions, support.admission_controller(), outbox, Clock(support.now())
    )
    ctx = ApiContext(
        coordinator=coordinator,
        edge=EdgePreValidator(),
        admission=support.admission_controller(),
        tenant_id=TENANT,
    )
    return TestClient(create_app(ctx))


def _run_body(**overrides):
    body = {
        "task_id": "task:1",
        "goal": "Summarize the report",
        "completion_criteria": ["answer_provided"],
        "risk_class": "read_only",
        "agent_ref": "agent:1",
        "runtime_adapter_ref": "adapter:langgraph",
        "release_id": "release:1",
        "budget_snapshot_ref": "budget-snapshot:1",
        "owner_ref": "principal:1",
        "request_refs": ["request:1"],
        "trace_id": "trace:1",
    }
    body.update(overrides)
    return body


@pytest.mark.test_id("RUN-005")
def test_api_edge_reject_returns_problem_and_no_run() -> None:
    client = _client()
    resp = client.post(
        "/v1/requests",
        json={
            "request_id": "request:bad",
            "channel": "queue",
            "protocol": "test",
            "client_correlation_id": "c1",
            "received_at": "2099-08-15T12:00:00Z",
            "deadline_at": "2099-08-15T13:00:00Z",
            "tenant_id": TENANT,
            "principal_ref": "principal:1",
        },
    )
    # 边缘层预校验接受 queue 通道 -> 201
    assert resp.status_code == 201
    assert resp.json()["status"] == "accepted"


@pytest.mark.test_id("RUN-001")
def test_api_run_lifecycle_create_admit_terminal() -> None:
    client = _client()
    created = client.post("/v1/runs", json=_run_body())
    assert created.status_code == 201
    run = created.json()
    assert run["phase"] == "queued"
    assert run["completion_disposition"] is None

    admitted = client.post(f"/v1/runs/{run['run_id']}/admission", json={})
    assert admitted.status_code == 200
    assert admitted.json()["outcome"] == "admitted"
    assert client.get(f"/v1/runs/{run['run_id']}").json()["phase"] == "running"

    command = client.post(
        f"/v1/runs/{run['run_id']}/commands",
        json={
            "command_id": "cmd:1",
            "command_name": "ueaf.run.commit_terminal",
            "command_version": "1.0.0",
            "tenant_id": TENANT,
            "actor_ref": "principal:1",
            "target_type": "RunRecord",
            "target_id": run["run_id"],
            "idempotency_key": "cmd:1",
            "payload": {
                "disposition": "completed",
                "reason_codes": ["done"],
                "result_ref": "result:1",
            },
        },
    )
    assert command.status_code == 202
    body = command.json()
    assert body["phase"] == "terminal"
    assert body["completion_disposition"] == "completed"


@pytest.mark.test_id("CON-005")
def test_api_errors_are_problem_detail() -> None:
    client = _client()

    missing = client.get("/v1/runs/run:missing")
    assert missing.status_code == 404
    payload = missing.json()
    assert payload["code"] == "not_found"
    assert payload["retryability"] == "never"

    # 无效的状态转换以 409 ProblemDetail 形式返回。
    created = client.post("/v1/runs", json=_run_body()).json()
    conflict = client.post(
        f"/v1/runs/{created['run_id']}/commands",
        json={
            "command_id": "cmd:x",
            "command_name": "ueaf.run.commit_terminal",
            "command_version": "1.0.0",
            "tenant_id": TENANT,
            "actor_ref": "principal:1",
            "target_type": "RunRecord",
            "target_id": created["run_id"],
            "idempotency_key": "cmd:x",
            "payload": {"disposition": "completed", "reason_codes": ["done"]},
        },
    )
    # queued 状态的 run 不能直接进入 terminal（必须先通过准入）。
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "invalid_state_transition"


@pytest.mark.test_id("CON-005")
def test_api_unsupported_command_is_validation_error() -> None:
    client = _client()
    created = client.post("/v1/runs", json=_run_body()).json()
    resp = client.post(
        f"/v1/runs/{created['run_id']}/commands",
        json={
            "command_id": "cmd:y",
            "command_name": "ueaf.run.unknown_op",
            "command_version": "1.0.0",
            "tenant_id": TENANT,
            "actor_ref": "principal:1",
            "target_type": "RunRecord",
            "target_id": created["run_id"],
            "idempotency_key": "cmd:y",
            "payload": {},
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_failed"
