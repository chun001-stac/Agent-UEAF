"""Shared builders/fakes for V1 reference implementation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ueaf.admission.controller import AdmissionController, PolicyDecisionRefs
from ueaf.admission.objects import (
    BudgetEnvelope,
    PrincipalContext,
    RiskClass,
    TaskEnvelope,
)
from ueaf.common.meta import ContractMeta, ProvenanceRef
from ueaf.infrastructure.db.database import Database

TENANT = "tenant-demo"
PRODUCER = "ueaf-test"
PRODUCER_VERSION = "0.1.0"


def now() -> datetime:
    return datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def principal(
    principal_id: str = "principal-user-1",
    *,
    roles: tuple[str, ...] = ("analyst",),
    scopes: tuple[str, ...] = ("read", "run"),
    regions: tuple[str, ...] = ("cn-east",),
    issued: datetime | None = None,
    expires: datetime | None = None,
) -> PrincipalContext:
    moment = issued or now()
    return PrincipalContext(
        meta=ContractMeta(
            contract_name="PrincipalContext",
            contract_version="1.0.0",
            object_id=principal_id,
            tenant_id=TENANT,
            created_at=moment,
            producer=PRODUCER,
            producer_version=PRODUCER_VERSION,
        ),
        principal_id=principal_id,
        principal_type="end_user",
        tenant_id=TENANT,
        roles=roles,
        scopes=scopes,
        data_regions=regions,
        issued_at=moment,
        expires_at=expires or moment + timedelta(hours=1),
    )


def task_envelope(
    task_id: str = "task-1",
    *,
    risk_class: RiskClass = "read_only",
    revision: int = 1,
    goal: str = "Summarize the quarterly report",
) -> TaskEnvelope:
    moment = now()
    return TaskEnvelope(
        meta=ContractMeta(
            contract_name="TaskEnvelope",
            contract_version="1.0.0",
            object_id=task_id,
            tenant_id=TENANT,
            created_at=moment,
            producer=PRODUCER,
            producer_version=PRODUCER_VERSION,
            provenance=(ProvenanceRef("request", "request-1", moment),),
        ),
        task_id=task_id,
        request_refs=("request-1",),
        goal=goal,
        completion_criteria=("answer_provided",),
        constraints={},
        risk_class=risk_class,
        owner_ref="principal-user-1",
        budget_ref="budget-1",
        revision=revision,
    )


def budget(
    budget_id: str = "budget-1",
    *,
    max_steps: int | None = 10,
    max_model_calls: int | None = 5,
    max_tool_calls: int | None = 5,
    max_token_budget: int | None = 20_000,
) -> BudgetEnvelope:
    return BudgetEnvelope(
        meta=ContractMeta(
            contract_name="BudgetEnvelope",
            contract_version="1.0.0",
            object_id=budget_id,
            tenant_id=TENANT,
            created_at=now(),
            producer=PRODUCER,
            producer_version=PRODUCER_VERSION,
        ),
        budget_id=budget_id,
        max_steps=max_steps,
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
        max_token_budget=max_token_budget,
    )


class AllowAllReleaseGate:
    def __init__(self, usable: bool = True) -> None:
        self._usable = usable

    def lifecycle_is_usable(self, release_manifest_ref: str) -> bool:
        return self._usable

    def is_compatible(self, release_manifest_ref: str, task: TaskEnvelope) -> bool:
        return True


class StubPolicySource(PolicyDecisionRefs):
    def __init__(
        self,
        *,
        refs: tuple[str, ...] = ("policy-decision:1",),
        denied: bool = False,
    ) -> None:
        self._refs = refs
        self._denied = denied

    def resolved_policy_decision_refs(self, run_id: str) -> tuple[str, ...]:
        del run_id
        return self._refs

    def any_deny(self, run_id: str) -> bool:
        del run_id
        return self._denied


def admission_controller(
    *,
    usable_release: bool = True,
    policy_refs: tuple[str, ...] = ("policy-decision:1",),
    denied: bool = False,
) -> AdmissionController:
    return AdmissionController(
        AllowAllReleaseGate(usable=usable_release),
        StubPolicySource(refs=policy_refs, denied=denied),
    )


async def clean_authoritative_tables(database: Database) -> None:
    """Delete all rows from authoritative tables (test isolation).

    SQL integration tests assume a clean authority DB; a real PostgreSQL left
    over from a previous run (or a shared CI DB) otherwise violates unique-key
    assumptions (e.g. ``task-1``). Truncation restores hermeticity regardless of
    driver/backing store.
    """

    from sqlalchemy import delete

    from ueaf.infrastructure.db.orm import Base

    async with database.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(delete(table))
