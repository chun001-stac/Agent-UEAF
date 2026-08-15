"""FastAPI control-plane for the V1 reference implementation.

Endpoints follow the edge pre-validation -> run creation -> run admission ->
command submission flow. All domain errors surface as ``ProblemDetail``.
The app is constructed with an injected coordinator (in-memory or SQL-backed)
plus ingress registries for the immutable task/budget envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from ueaf.admission.controller import AdmissionController
from ueaf.admission.edge import EdgePreValidator
from ueaf.admission.objects import (
    BudgetEnvelope,
    PrincipalContext,
    RequestEnvelope,
    TaskEnvelope,
)
from ueaf.api.errors import register_exception_handlers
from ueaf.api.schemas import (
    AdmissionIn,
    AdmissionResultOut,
    CommandIn,
    ProblemDetailOut,
    RequestIn,
    RunCreateIn,
    RunOut,
)
from ueaf.common.identifiers import utcnow
from ueaf.common.meta import ContractMeta
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.objects import RunRecord

_PROBLEM_HEADER = "application/problem+json"


@dataclass(slots=True)
class ApiContext:
    """Wiring for the API: coordinator + ingress registries."""

    coordinator: RunCoordinator
    edge: EdgePreValidator
    admission: AdmissionController
    tenant_id: str
    task_envelopes: dict[str, TaskEnvelope] = field(default_factory=dict)
    budget_envelopes: dict[str, BudgetEnvelope] = field(default_factory=dict)


def create_app(ctx: ApiContext) -> FastAPI:
    app = FastAPI(title="UEAF V1 Control Plane", version="0.1.0")
    app.state.ctx = ctx
    register_exception_handlers(app)
    app.include_router(_requests_router())
    app.include_router(_runs_router())
    return app


def _requests_router() -> APIRouter:
    router = APIRouter(prefix="/v1/requests", tags=["requests"])

    @router.post("", status_code=201)
    async def ingest_request(
        body: RequestIn, request: Request
    ) -> JSONResponse:
        ctx: ApiContext = request.app.state.ctx
        moment = body.received_at
        envelope = RequestEnvelope(
            meta=_meta("RequestEnvelope", body.request_id, ctx.tenant_id, moment),
            request_id=body.request_id,
            channel=body.channel,
            protocol=body.protocol,
            client_correlation_id=body.client_correlation_id,
            received_at=body.received_at,
            deadline_at=body.deadline_at,
            principal_context_ref=body.principal_ref,
            validation_status=body.validation_status,
            input_ref=body.input_ref,
        )
        result = ctx.edge.validate(envelope, observed_at=utcnow())
        if not result.accepted:
            problem = ProblemDetailOut(
                code=result.problem.code if result.problem else "rejected",
                category="validation",
                message_safe="edge pre-validation failed",
                retryability="never",
                source="ueaf-edge",
                object_ref=body.request_id,
                observed_at=utcnow(),
            )
            return JSONResponse(
                status_code=422,
                content=problem.model_dump(mode="json"),
                headers={"Content-Type": _PROBLEM_HEADER},
            )
        return JSONResponse(
            status_code=201,
            content={"request_id": body.request_id, "status": "accepted"},
        )

    return router


def _runs_router() -> APIRouter:
    router = APIRouter(prefix="/v1/runs", tags=["runs"])

    @router.post("", status_code=201, response_model=RunOut)
    async def create_run(body: RunCreateIn, request: Request) -> RunOut:
        ctx: ApiContext = request.app.state.ctx
        task = _task_envelope(body, ctx)
        budget = _budget_envelope(body, ctx)
        ctx.task_envelopes[task.task_id] = task
        ctx.budget_envelopes[task.task_id] = budget
        record = ctx.coordinator.create_run(
            RunCreateInput(
                task_envelope=task,
                agent_ref=body.agent_ref,
                runtime_adapter_ref=body.runtime_adapter_ref,
                release_id=body.release_id,
                budget_snapshot_ref=body.budget_snapshot_ref,
                trace_id=body.trace_id,
                deadline_at=body.deadline_at,
                actor_ref=body.owner_ref,
            )
        )
        return _run_out(record)

    @router.get("/{run_id}", response_model=RunOut)
    async def get_run(run_id: str, request: Request) -> RunOut:
        ctx: ApiContext = request.app.state.ctx
        return _run_out(ctx.coordinator.require_run(run_id))

    @router.post("/{run_id}/admission", response_model=AdmissionResultOut)
    async def admit_run(
        run_id: str, body: AdmissionIn, request: Request
    ) -> AdmissionResultOut:
        ctx: ApiContext = request.app.state.ctx
        run = ctx.coordinator.begin_admission(run_id, actor_ref=body.actor_ref)
        task = ctx.task_envelopes[run.task_id]
        budget = ctx.budget_envelopes[run.task_id]
        principal = _principal(body, ctx)
        result = ctx.admission.evaluate(run, task, budget, principal)
        ctx.coordinator.apply_admission(run_id, result, actor_ref=body.actor_ref)
        return AdmissionResultOut(
            run_admission_result_id=result.run_admission_result_id,
            run_id=result.run_id,
            outcome=result.outcome,
            reason_codes=list(result.reason_codes),
            policy_decision_refs=list(result.policy_decision_refs),
            budget_snapshot_ref=result.budget_snapshot_ref,
            release_manifest_ref=result.release_manifest_ref,
            expires_at=result.expires_at,
        )

    @router.post("/{run_id}/commands", status_code=202, response_model=RunOut)
    async def submit_command(
        run_id: str, body: CommandIn, request: Request
    ) -> RunOut:
        ctx: ApiContext = request.app.state.ctx
        record = _dispatch_command(ctx.coordinator, run_id, body)
        return _run_out(record)

    return router


def _dispatch_command(
    coordinator: RunCoordinator, run_id: str, body: CommandIn
) -> RunRecord:
    payload: dict[str, Any] = body.payload
    if body.command_name == "ueaf.run.commit_terminal":
        return coordinator.commit_terminal(
            run_id,
            disposition=payload["disposition"],
            reason_codes=tuple(payload.get("reason_codes", [])),
            result_ref=payload.get("result_ref"),
            error_ref=payload.get("error_ref"),
            actor_ref=body.actor_ref,
        )
    if body.command_name == "ueaf.run.cancel":
        return coordinator.cancel(run_id, actor_ref=body.actor_ref)
    if body.command_name == "ueaf.run.pause":
        return coordinator.pause(
            run_id,
            reason_codes=tuple(payload.get("reason_codes", ["paused"])),
            checkpoint_ref=payload.get("checkpoint_ref"),
            actor_ref=body.actor_ref,
        )
    raise ValueError(f"unsupported command {body.command_name!r}")


# -- mappers ----------------------------------------------------------------


def _meta(contract_name: str, object_id: str, tenant_id: str, moment: datetime) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=tenant_id,
        created_at=moment,
        producer="ueaf-api",
        producer_version="0.1.0",
    )


def _task_envelope(body: RunCreateIn, ctx: ApiContext) -> TaskEnvelope:
    return TaskEnvelope(
        meta=_meta("TaskEnvelope", body.task_id, ctx.tenant_id, utcnow()),
        task_id=body.task_id,
        request_refs=tuple(body.request_refs),
        goal=body.goal,
        completion_criteria=tuple(body.completion_criteria),
        constraints=body.constraints,
        risk_class=body.risk_class,
        owner_ref=body.owner_ref,
        budget_ref=body.budget_snapshot_ref,
    )


def _budget_envelope(body: RunCreateIn, ctx: ApiContext) -> BudgetEnvelope:
    return BudgetEnvelope(
        meta=_meta("BudgetEnvelope", f"budget:{body.task_id}", ctx.tenant_id, utcnow()),
        budget_id=f"budget:{body.task_id}",
        max_steps=100,
        max_model_calls=50,
        max_tool_calls=50,
        max_token_budget=100_000,
    )


def _principal(body: AdmissionIn, ctx: ApiContext) -> PrincipalContext:
    moment = utcnow()
    return PrincipalContext(
        meta=_meta("PrincipalContext", body.principal_id, ctx.tenant_id, moment),
        principal_id=body.principal_id,
        principal_type="end_user",
        tenant_id=ctx.tenant_id,
        roles=("analyst",),
        scopes=("read", "run"),
        data_regions=tuple(body.data_regions),
        issued_at=moment,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


def _run_out(record: RunRecord) -> RunOut:
    return RunOut(
        run_id=record.run_id,
        task_id=record.task_id,
        tenant_id=record.meta.tenant_id,
        phase=record.phase,
        completion_disposition=record.completion_disposition,
        wait_reason=record.wait_reason,
        attempt=record.attempt,
        revision=record.revision,
        release_id=record.release_id,
        runtime_adapter_ref=record.runtime_adapter_ref,
        result_ref=record.result_ref,
        error_ref=record.error_ref,
        updated_at=record.updated_at,
    )
