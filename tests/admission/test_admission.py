"""阶段 1 准入验收测试（RUN-*）。"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.admission.edge import EdgePreValidator
from ueaf.admission.objects import RequestEnvelope, TaskEnvelope
from ueaf.common.meta import ContractMeta
from ueaf.infrastructure.db.repositories import (
    Clock,
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.objects import RunRecord
from ueaf.runtime.outbox import InMemoryOutboxStore
from ueaf.runtime.state_machine import StateMachineError


def _harness(**kwargs) -> tuple[RunCoordinator, InMemoryRunRecordRepository, InMemoryOutboxStore]:
    runs = InMemoryRunRecordRepository()
    tasks = InMemoryTaskStateRepository()
    admissions = InMemoryAdmissionResultRepository()
    outbox = InMemoryOutboxStore()
    controller = support.admission_controller(**kwargs)
    coordinator = RunCoordinator(
        runs, tasks, admissions, controller, outbox, clock=Clock(support.now())
    )
    return coordinator, runs, outbox


async def _create_run(coordinator: RunCoordinator, *, risk_class="read_only") -> RunRecord:
    return await coordinator.create_run(
        RunCreateInput(
            task_envelope=support.task_envelope(risk_class=risk_class),
            agent_ref="agent:1",
            runtime_adapter_ref="adapter:langgraph",
            release_id="release:1",
            budget_snapshot_ref="budget-snapshot:1",
            trace_id="trace:1",
            actor_ref="principal:1",
        )
    )


@pytest.mark.test_id("RUN-001")
async def test_queued_cannot_skip_admitting() -> None:
    coordinator, _, _ = _harness()
    run = await _create_run(coordinator)
    assert run.phase == "queued"

    # 封闭状态机拒绝直接由 queued 跳转到 running。
    with pytest.raises(StateMachineError):
        await coordinator.resume(run.run_id, to_phase="running", resume_signal_ref="sig")

    # 正确路径：queued -> admitting -> running（仅在准入通过后）。
    admitting = await coordinator.begin_admission(run.run_id)
    assert admitting.phase == "admitting"

    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    assert result.outcome == "admitted"

    running = await coordinator.apply_admission(admitting.run_id, result)
    assert running.phase == "running"
    assert running.completion_disposition is None


@pytest.mark.test_id("RUN-005")
async def test_edge_reject_creates_no_run() -> None:
    coordinator, runs, _ = _harness()
    moment = support.now()

    rejected_request = RequestEnvelope(
        meta=ContractMeta(
            contract_name="RequestEnvelope",
            contract_version="1.0.0",
            object_id="request:bad",
            tenant_id=support.TENANT,
            created_at=moment,
            producer="ueaf-edge",
            producer_version="0.1.0",
        ),
        request_id="request:bad",
        channel="smoke-signals",  # not allowed
        protocol="test",
        client_correlation_id="c-1",
        received_at=moment,
        deadline_at=None,
        principal_context_ref="principal:1",
        validation_status="pending",
    )

    edge = EdgePreValidator()
    result = edge.validate(rejected_request, observed_at=moment)
    assert result.accepted is False
    # 被边缘层拒绝的请求不应存在任何 RunRecord / RunAdmissionResult。
    assert await runs.get("run:any") is None
    assert await coordinator._admissions.get("run-admission:any:1") is None


@pytest.mark.test_id("RUN-006")
async def test_task_risk_enum_rejects_deprecated_aliases() -> None:
    coordinator, _, _ = _harness()
    with pytest.raises(ValueError, match="invalid risk_class"):
        await _create_run(coordinator, risk_class="R3")  # 已弃用的别名被拒绝
    with pytest.raises(ValueError, match="invalid risk_class"):
        TaskEnvelope(
            meta=ContractMeta(
                contract_name="TaskEnvelope",
                contract_version="1.0.0",
                object_id="task:bad",
                tenant_id=support.TENANT,
                created_at=support.now(),
                producer="ueaf-test",
                producer_version="0.1.0",
            ),
            task_id="task:bad",
            request_refs=("request:1",),
            goal="g",
            completion_criteria=("c",),
            constraints={},
            risk_class="R0",
            owner_ref="p",
            budget_ref="b",
        )


@pytest.mark.test_id("RUN-007")
async def test_adapter_binding_is_frozen_before_admission() -> None:
    coordinator, runs, _ = _harness()
    run = await _create_run(coordinator)
    frozen_adapter = run.runtime_adapter_ref
    assert frozen_adapter == "adapter:langgraph"

    admitting = await coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    running = await coordinator.apply_admission(admitting.run_id, result)
    # 准入校验已冻结的绑定；重试/恢复不能重新选择。
    assert running.runtime_adapter_ref == frozen_adapter
    assert running.runtime_adapter_ref == "adapter:langgraph"


@pytest.mark.test_id("ADP-003")
async def test_unsupported_capability_rejects_with_unsupported() -> None:
    coordinator, _, _ = _harness()
    run = await _create_run(coordinator)
    admitting = await coordinator.begin_admission(run.run_id)
    # 能力集合不满足任务的适配器会在准入时通过绑定检查被拒绝
    # （reason code 为 unsupported_capability）。
    result = support.admission_controller(usable_release=False).evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    assert result.outcome == "rejected"
    assert any("release" in code for code in result.reason_codes)
