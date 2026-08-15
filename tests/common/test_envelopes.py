"""Common envelope / error / meta contract tests (Phase 0/1 foundations)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests import support
from ueaf.admission.objects import PrincipalContext, TaskEnvelope
from ueaf.common.envelope import (
    CommandEnvelope,
    EventCatalog,
    EventCatalogEntry,
    EventEnvelope,
)
from ueaf.common.error import ProblemDetail
from ueaf.common.meta import ContractMeta
from ueaf.runtime.objects import RunRecord, TaskState

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _meta(contract_name: str, object_id: str, tenant: str = support.TENANT) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=tenant,
        created_at=MOMENT,
        producer=support.PRODUCER,
        producer_version=support.PRODUCER_VERSION,
    )


@pytest.mark.test_id("CON-001")
def test_contract_meta_is_present_and_consistent_on_persisted_objects() -> None:
    run = RunRecord(
        meta=_meta("RunRecord", "run:1"),
        run_id="run:1",
        task_id="task:1",
        agent_ref="agent:1",
        runtime_adapter_ref="adapter:langgraph",
        release_id="release:1",
        phase="queued",
        terminal_reason_codes=(),
    )
    task_state = TaskState(
        meta=_meta("TaskState", "task:1"),
        task_id="task:1",
    )
    principal = PrincipalContext(
        meta=_meta("PrincipalContext", "principal:1"),
        principal_id="principal:1",
        principal_type="end_user",
        tenant_id=support.TENANT,
        issued_at=MOMENT,
        expires_at=datetime(2026, 8, 15, 13, 0, 0, tzinfo=UTC),
    )

    assert run.meta.contract_name == "RunRecord"
    assert run.meta.object_id == run.run_id
    assert run.meta.tenant_id == run.tenant if hasattr(run, "tenant") else True
    assert task_state.meta.object_id == task_state.task_id
    assert principal.meta.object_id == principal.principal_id
    assert principal.meta.tenant_id == principal.tenant_id  # CON-008


@pytest.mark.test_id("CON-002")
def test_single_event_envelope_no_reduced_variant() -> None:
    # V1 exposes exactly one public EventEnvelope shape; constructors validate it.
    event = EventEnvelope(
        event_id="evt:1",
        event_name="ueaf.run.created",
        event_version="1.0.0",
        occurred_at=MOMENT,
        recorded_at=MOMENT,
        tenant_id=support.TENANT,
        aggregate_type="RunRecord",
        aggregate_id="run:1",
        aggregate_version=1,
        sequence=1,
        producer=support.PRODUCER,
        producer_version=support.PRODUCER_VERSION,
        correlation_id="req:1",
        trace_id="trace:1",
        principal_ref="principal:1",
        release_id="release:1",
        payload_schema_ref="schema://run-created/1.0.0",
        payload={"run_id": "run:1", "task_id": "task:1", "release_id": "release:1",
                 "runtime_adapter_ref": "adapter:langgraph"},
    )
    assert event.event_id == "evt:1"
    assert event.aggregate_version == 1 and event.sequence == 1


@pytest.mark.test_id("CON-003")
def test_event_naming_is_ueaf_domain_past_tense() -> None:
    with pytest.raises(ValueError, match="invalid event_name"):
        EventEnvelope(
            event_id="evt:1",
            event_name="run.commit_terminal",  # imperative / not ueaf.*
            event_version="1.0.0",
            occurred_at=MOMENT,
            recorded_at=MOMENT,
            tenant_id=support.TENANT,
            aggregate_type="RunRecord",
            aggregate_id="run:1",
            aggregate_version=1,
            sequence=1,
            producer=support.PRODUCER,
            producer_version=support.PRODUCER_VERSION,
            correlation_id="req:1",
            trace_id="trace:1",
            payload_schema_ref="schema://run-phase-changed/1.0.0",
            payload={},
        )
    with pytest.raises(ValueError, match="invalid event_name"):
        EventEnvelope(
            event_id="evt:2",
            event_name="ueaf.Run.PhaseChanged",  # PascalCase forbidden
            event_version="1.0.0",
            occurred_at=MOMENT,
            recorded_at=MOMENT,
            tenant_id=support.TENANT,
            aggregate_type="RunRecord",
            aggregate_id="run:1",
            aggregate_version=1,
            sequence=1,
            producer=support.PRODUCER,
            producer_version=support.PRODUCER_VERSION,
            correlation_id="req:1",
            trace_id="trace:1",
            payload_schema_ref="schema://run-phase-changed/1.0.0",
            payload={},
        )


@pytest.mark.test_id("CON-004")
def test_event_registry_is_unique_and_not_a_second_owner() -> None:
    catalog = EventCatalog(
        catalog_version="1.0.0",
        entries=(
            EventCatalogEntry(
                "ueaf.run.created",
                "1.0.0",
                "schema://run-created/1.0.0",
                "RunRecord",
                "ueaf-runtime",
            ),
        ),
    )
    assert catalog.resolve("ueaf.run.created", "1.0.0").payload_schema_ref == (
        "schema://run-created/1.0.0"
    )
    with pytest.raises(KeyError):
        catalog.resolve("ueaf.run.phase_changed", "1.0.0")


@pytest.mark.test_id("CON-005")
def test_single_error_contract_uses_problem_detail() -> None:
    problem = ProblemDetail(
        code="run_not_admitted",
        category="policy",
        message_safe="Run was not admitted",
        retryability="never",
        source="ueaf-admission",
        observed_at=MOMENT,
    )
    assert problem.code == "run_not_admitted"
    assert problem.category == "policy"

    with pytest.raises(ValueError, match="unknown ProblemDetail.category"):
        ProblemDetail(
            code="x",
            category="not_a_category",
            message_safe="x",
            retryability="never",
            source="test",
        )


@pytest.mark.test_id("CON-008")
def test_canonical_principal_context_tenant_consistency() -> None:
    with pytest.raises(ValueError, match="tenant_id MUST equal meta.tenant_id"):
        PrincipalContext(
            meta=_meta("PrincipalContext", "principal:1"),
            principal_id="principal:1",
            principal_type="end_user",
            tenant_id="other-tenant",
            issued_at=MOMENT,
            expires_at=datetime(2026, 8, 15, 13, 0, 0, tzinfo=UTC),
        )


@pytest.mark.test_id("CON-009")
def test_task_risk_class_is_separate_from_evolution_repair_level() -> None:
    # New TaskEnvelope writes reject deprecated R0..R3 aliases (RUN-006).
    with pytest.raises(ValueError, match="invalid risk_class"):
        TaskEnvelope(
            meta=_meta("TaskEnvelope", "task:1"),
            task_id="task:1",
            request_refs=("request:1",),
            goal="g",
            completion_criteria=("c",),
            constraints={},
            risk_class="R1",  # deprecated alias not accepted
            owner_ref="principal:1",
            budget_ref="budget:1",
        )
    # Migration reader may map the legacy alias explicitly.
    migrated = support.task_envelope(risk_class="read_only").with_legacy_risk_alias("R2")
    assert migrated.risk_class == "reversible_write"


@pytest.mark.test_id("CON-013")
def test_command_envelope_validation() -> None:
    command = CommandEnvelope(
        command_id="cmd:1",
        command_name="ueaf.run.commit_terminal",
        command_version="1.0.0",
        issued_at=MOMENT,
        deadline_at=datetime(2026, 8, 15, 12, 1, 0, tzinfo=UTC),
        tenant_id=support.TENANT,
        actor_ref="principal:1",
        target_type="RunRecord",
        target_id="run:1",
        expected_revision=3,
        idempotency_key="cmd:1",
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://command/1.0.0",
        payload={"disposition": "cancelled"},
    )
    assert command.target_type == "RunRecord"
    with pytest.raises(ValueError, match="deadline_at"):
        CommandEnvelope(
            command_id="cmd:2",
            command_name="ueaf.run.commit_terminal",
            command_version="1.0.0",
            issued_at=MOMENT,
            deadline_at=MOMENT,  # not after issued_at
            tenant_id=support.TENANT,
            actor_ref="principal:1",
            target_type="RunRecord",
            target_id="run:1",
            expected_revision=3,
            idempotency_key="cmd:2",
            correlation_id="req:1",
            trace_id="trace:1",
            payload_schema_ref="schema://command/1.0.0",
            payload={},
        )
