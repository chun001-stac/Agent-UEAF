from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from ueaf.common.schema_registry import validate_canonical_invariants, validate_instance

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def meta(
    contract_name: str,
    object_id: str,
    *,
    tenant_id: str = "tenant-a",
    purpose: list[str] | None = None,
) -> dict[str, object]:
    return {
        "contract_name": contract_name,
        "contract_version": "1.0.0",
        "object_id": object_id,
        "tenant_id": tenant_id,
        "created_at": "2026-08-14T14:00:00Z",
        "producer": "test",
        "producer_version": "1.0.0",
        "classification": "internal",
        "purpose": ["test"] if purpose is None else purpose,
        "provenance": [{"source_ref": "fixture://canonical-schema-tests"}],
    }


def phase_changed_event() -> dict[str, Any]:
    return {
        "event_id": "evt-1",
        "event_name": "ueaf.run.phase_changed",
        "event_version": "1.0.0",
        "occurred_at": "2026-08-14T14:00:00Z",
        "recorded_at": "2026-08-14T14:00:01Z",
        "tenant_id": "tenant-a",
        "aggregate_type": "RunRecord",
        "aggregate_id": "run-1",
        "aggregate_version": 2,
        "sequence": 2,
        "producer": "RunCoordinator",
        "producer_version": "1.0.0",
        "correlation_id": "req-1",
        "trace_id": "trace-1",
        "payload_schema_ref": "schema://run-phase-changed/1.0.0",
        "payload": {
            "from_phase": "queued",
            "to_phase": "admitting",
            "reason_codes": ["admission_lease_acquired"],
        },
        "classification": "internal",
        "purpose": ["runtime"],
    }


def principal_context() -> dict[str, Any]:
    return {
        "meta": meta("PrincipalContext", "user-1"),
        "principal_id": "user-1",
        "principal_type": "end_user",
        "tenant_id": "tenant-a",
        "roles": ["user"],
        "scopes": ["read"],
        "delegation_chain": [],
        "authentication_strength": "mfa",
        "data_regions": ["ap-east"],
        "consent_refs": [],
        "issued_at": "2026-08-14T14:00:00Z",
        "expires_at": "2026-08-14T15:00:00Z",
    }


def release_manifest() -> dict[str, Any]:
    return {
        "meta": meta("ReleaseManifest", "release-1"),
        "release_id": "release-1",
        "environment": "staging",
        "lifecycle_status": "approved",
        "agent_versions": ["agent-1@1"],
        "prompt_versions": ["prompt-1@1"],
        "schema_versions": ["schema-1@1"],
        "model_route_versions": ["route-1@1"],
        "capability_versions": [],
        "adapter_versions": ["runtime-1@1"],
        "knowledge_index_versions": [],
        "memory_policy_versions": [],
        "policy_versions": ["policy-1@1"],
        "contract_version_ranges": {"ueaf": ">=1.0.0,<2.0.0"},
        "compatibility_matrix_ref": "compatibility://release-1",
        "migration_refs": [],
        "quality_gate_decision_ref": "qg-1",
        "security_gate_decision_ref": "sg-1",
        "operational_readiness_decision_ref": "og-1",
        "release_decision_ref": "rd-1",
        "rollout": {
            "slice_refs": ["slice://staging"],
            "stop_condition_refs": ["condition://quality-regression"],
            "capacity_limit_ref": "capacity://staging",
        },
        "rollback": {
            "target_release_ref": "release://previous",
            "irreversible_migration_refs": [],
            "recovery_precondition_refs": [],
        },
        "observation_window": {
            "duration_seconds": 900,
            "success_condition_refs": ["condition://healthy"],
            "failure_condition_refs": ["condition://rollback"],
        },
        "integrity_ref": "sha256:test",
    }


def mutation_proposal() -> dict[str, Any]:
    return {
        "meta": meta("MutationProposal", "mp-1"),
        "mutation_proposal_id": "mp-1",
        "subject_ref": "agent-1",
        "baseline_genome_ref": "genome-1",
        "trigger_ref": "trigger-1",
        "evidence_refs": ["evidence-1"],
        "strategy_ref": "strategy-1",
        "mutation_type": "modify",
        "mutable_scope": ["context_policy"],
        "change_summary": {"summary": "increase retrieval depth"},
        "changes": [
            {
                "target_ref": "context-policy-1",
                "path": "retrieval_top_k",
                "operation": "replace",
                "before": 5,
                "after": 8,
                "constraint_profile_ref": "context-policy-standard-v1",
            }
        ],
        "hypothesis": "recall improves",
        "expected_gain": {},
        "expected_cost": {},
        "risk_refs": [],
        "created_by": "strategy-1",
        "created_at": "2026-08-14T14:00:00Z",
    }


def evolution_run() -> dict[str, Any]:
    return {
        "meta": meta("EvolutionRun", "er-1"),
        "evolution_run_id": "er-1",
        "subject_ref": "agent-1",
        "baseline_genome_ref": "genome-1",
        "trigger_ref": "trigger-1",
        "phase": "analyzing",
        "disposition": None,
        "budget_ref": "budget-1",
        "mutable_scope": ["context_policy"],
        "strategy_ref": "strategy-1",
        "active_working_set_ref": "ws-1",
        "revision": 1,
        "created_at": "2026-08-14T14:00:00Z",
        "updated_at": "2026-08-14T14:00:01Z",
    }


def problem_detail() -> dict[str, Any]:
    return {
        "code": "invalid_request",
        "category": "contract_invalid",
        "message_safe": "request is invalid",
        "retryability": "never",
        "source": "gateway",
        "object_ref": None,
        "field_paths": [],
        "correlation_refs": {},
        "cause_ref": None,
        "observed_at": "2026-08-14T14:00:00Z",
        "details_ref": None,
    }


def port_error() -> dict[str, Any]:
    return {
        "code": "invalid_request",
        "category": "invalid_request",
        "retryability": "never",
        "certainty": "not_executed",
        "message_ref": None,
        "provider_error_ref": None,
        "observed_at": "2026-08-14T14:00:00Z",
        "details_schema_ref": None,
    }


def action_record(*, disposition: str = "executed") -> dict[str, Any]:
    instance: dict[str, Any] = {
        "meta": meta("ActionRecord", "action-1"),
        "action_id": "action-1",
        "action_key": "action-key-1",
        "action_fingerprint": "action-fingerprint-1",
        "tool_intent_ref": "tool-intent-1",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "capability_ref": "capability-1",
        "phase": "terminal",
        "disposition": disposition,
        "policy_decision_ref": "policy-decision-1",
        "approval_request_ref": None,
        "idempotency_reservation_ref": "reservation-1",
        "latest_receipt_ref": "receipt-1",
        "receipt_refs": ["receipt-1"],
        "attempt": 1,
        "reconciliation_state": None,
        "lease_fencing_token": 1,
        "revision": 1,
        "sequence": 1,
        "created_at": "2026-08-14T14:00:00Z",
        "updated_at": "2026-08-14T14:00:01Z",
    }
    if disposition == "unresolved":
        instance["reconciliation_state"] = {
            "policy_ref": "reconciliation-policy-1",
            "observation_refs": ["receipt-1"],
            "attempts": 1,
            "last_observed_at": "2026-08-14T14:00:01Z",
            "next_check_at": None,
            "exhausted": True,
        }
    return instance


def run_record() -> dict[str, Any]:
    budget = {"runtime_steps": 1}
    instance: dict[str, Any] = {
        "meta": meta("RunRecord", "run-1"),
        "run_id": "run-1",
        "task_id": "task-1",
        "agent_ref": "agent-1",
        "runtime_adapter_ref": "runtime-1",
        "release_id": "release-1",
        "phase": "terminal",
        "completion_disposition": "completed",
        "wait_reason": None,
        "wait_condition_refs": [],
        "attempt": 1,
        "sequence": 1,
        "lease": None,
        "deadline_at": None,
        "budget_snapshot": {
            "allocated": budget,
            "reserved": budget,
            "consumed": budget,
            "remaining": budget,
        },
        "checkpoint_ref": None,
        "pending_action_refs": [],
        "terminal_reason_codes": ["completion_contract_satisfied"],
        "result_ref": "result-1",
        "error_ref": None,
        "revision": 1,
        "created_at": "2026-08-14T14:00:00Z",
        "updated_at": "2026-08-14T14:00:01Z",
    }
    return instance


def run_lease() -> dict[str, Any]:
    return {
        "lease_id": "lease-1",
        "holder_id": "worker-1",
        "fencing_token": 1,
        "acquired_at": "2026-08-14T13:59:00Z",
        "heartbeat_at": "2026-08-14T14:00:00Z",
        "expires_at": "2026-08-14T15:00:00Z",
    }


def run_record_in_phase(
    phase: str,
    *,
    lease: dict[str, Any] | None,
) -> dict[str, Any]:
    instance = run_record()
    instance.update(
        {
            "phase": phase,
            "completion_disposition": None,
            "terminal_reason_codes": [],
            "result_ref": None,
            "lease": lease,
        }
    )
    if phase == "waiting":
        instance["wait_reason"] = "approval"
        instance["wait_condition_refs"] = ["approval-request-1"]
    return instance


def test_con_001_contract_meta_allows_empty_purpose() -> None:
    instance = meta("TestObject", "test-1", purpose=[])
    validate_instance(instance, SCHEMAS / "common/contract-meta.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "required_field",
    [
        "contract_name",
        "contract_version",
        "object_id",
        "tenant_id",
        "created_at",
        "producer",
        "producer_version",
        "classification",
        "purpose",
        "provenance",
    ],
)
def test_con_001_contract_meta_rejects_missing_required_field(required_field: str) -> None:
    instance = meta("TestObject", "test-1")
    del instance[required_field]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/contract-meta.schema.json", SCHEMAS)


def test_con_001_contract_meta_rejects_empty_provenance() -> None:
    instance = meta("TestObject", "test-1")
    instance["provenance"] = []
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/contract-meta.schema.json", SCHEMAS)


def test_con_001_contract_meta_rejects_empty_provenance_item() -> None:
    instance = meta("TestObject", "test-1")
    instance["provenance"] = [{}]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/contract-meta.schema.json", SCHEMAS)


def test_con_001_contract_meta_rejects_invalid_rfc3339_timestamp() -> None:
    instance = meta("TestObject", "test-1")
    instance["created_at"] = "not-a-timestamp"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/contract-meta.schema.json", SCHEMAS)


def test_con_003_event_envelope_accepts_registered_canonical_event() -> None:
    validate_instance(phase_changed_event(), SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_002_event_envelope_rejects_reduced_alias_contract() -> None:
    reduced_envelope = {
        "event_type": "run.phase_changed",
        "aggregate_ref": "run-1",
        "revision": 2,
        "correlation_refs": {"request_id": "req-1"},
    }
    with pytest.raises(ValidationError):
        validate_instance(reduced_envelope, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_003_event_envelope_rejects_pascal_case_alias() -> None:
    instance = phase_changed_event()
    instance["event_name"] = "TaskQueued"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_004_event_registry_rejects_unregistered_event() -> None:
    instance = phase_changed_event()
    instance["event_name"] = "ueaf.run.not_registered"
    with pytest.raises(ValidationError, match="not registered"):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_004_event_registry_rejects_version_mismatch() -> None:
    instance = phase_changed_event()
    instance["event_version"] = "2.0.0"
    with pytest.raises(ValidationError, match="not registered"):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_004_event_registry_rejects_payload_schema_mismatch() -> None:
    instance = phase_changed_event()
    instance["payload_schema_ref"] = "schema://run-created/1.0.0"
    with pytest.raises(ValidationError, match="payload_schema_ref"):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_con_004_event_registry_validates_payload() -> None:
    instance = phase_changed_event()
    instance["payload"] = {
        "from_phase": "queued",
        "to_phase": "not_a_run_phase",
        "reason_codes": ["invalid"],
    }
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "required_field",
    [
        "code",
        "category",
        "message_safe",
        "retryability",
        "source",
        "object_ref",
        "field_paths",
        "correlation_refs",
        "cause_ref",
        "observed_at",
        "details_ref",
    ],
)
def test_con_005_problem_detail_rejects_missing_required_field(required_field: str) -> None:
    instance = problem_detail()
    del instance[required_field]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/problem-detail.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "required_field",
    [
        "code",
        "category",
        "retryability",
        "certainty",
        "message_ref",
        "provider_error_ref",
        "observed_at",
        "details_schema_ref",
    ],
)
def test_con_005_port_error_rejects_missing_required_field(required_field: str) -> None:
    instance = port_error()
    del instance[required_field]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/port-error.schema.json", SCHEMAS)


@pytest.mark.parametrize("certainty", ["not_executed", "unknown"])
def test_con_005_port_error_accepts_normative_certainty(certainty: str) -> None:
    instance = port_error()
    instance["certainty"] = certainty
    validate_instance(instance, SCHEMAS / "common/port-error.schema.json", SCHEMAS)


def test_con_005_port_error_rejects_noncanonical_certainty() -> None:
    instance = port_error()
    instance["certainty"] = "certain_success"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "common/port-error.schema.json", SCHEMAS)


def test_evo_003_no_evolution_needed_is_valid_terminal_disposition() -> None:
    instance = evolution_run()
    instance["phase"] = "terminal"
    instance["disposition"] = "no_evolution_needed"
    validate_instance(instance, SCHEMAS / "evolution/evolution-run.schema.json", SCHEMAS)


def test_evo_003_evolution_run_rejects_terminal_disposition_before_terminal() -> None:
    instance = evolution_run()
    instance["disposition"] = "no_evolution_needed"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "evolution/evolution-run.schema.json", SCHEMAS)


def test_mut_008_mutation_proposal_requires_machine_changes() -> None:
    instance = mutation_proposal()
    del instance["changes"]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "evolution/mutation-proposal.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "change",
    [
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "add",
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "add",
            "before": 4,
            "after": 5,
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "remove",
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "remove",
            "before": 4,
            "after": 5,
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "replace",
            "before": 4,
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "replace",
            "after": 5,
            "constraint_profile_ref": "profile-1",
        },
    ],
)
def test_mut_008_mutation_operation_requires_correct_before_after(
    change: dict[str, Any],
) -> None:
    instance = mutation_proposal()
    instance["changes"] = [change]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "evolution/mutation-proposal.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "change",
    [
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "add",
            "after": 5,
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "remove",
            "before": 4,
            "constraint_profile_ref": "profile-1",
        },
        {
            "target_ref": "policy-1",
            "path": "top_k",
            "operation": "replace",
            "before": 4,
            "after": 5,
            "constraint_profile_ref": "profile-1",
        },
    ],
)
def test_mut_008_mutation_operation_accepts_correct_before_after(
    change: dict[str, Any],
) -> None:
    instance = mutation_proposal()
    instance["changes"] = [change]
    validate_instance(instance, SCHEMAS / "evolution/mutation-proposal.schema.json", SCHEMAS)


def test_con_008_principal_context_rejects_second_field_vocabulary() -> None:
    instance = principal_context()
    instance["subject_id"] = "legacy-alias"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "security/principal-context.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("contract_name", "id_field"),
    [
        ("RequestEnvelope", "request_id"),
        ("TaskEnvelope", "task_id"),
        ("TaskState", "task_id"),
        ("BudgetEnvelope", "budget_id"),
        ("RunRecord", "run_id"),
        ("RunAdmissionResult", "run_admission_result_id"),
        ("Checkpoint", "checkpoint_id"),
        ("HandoffEnvelope", "handoff_id"),
        ("AuditRecord", "audit_record_id"),
        ("ContextBuildRequest", "context_request_id"),
        ("ContextManifest", "context_manifest_id"),
        ("EvidencePack", "evidence_pack_id"),
        ("QueryIntent", "query_intent_id"),
        ("ModelInvocation", "model_invocation_id"),
        ("PromptContract", "prompt_contract_id"),
        ("StructuredDecision", "structured_decision_id"),
        ("ApprovalRequest", "approval_request_id"),
        ("AuthorizationRequest", "authorization_request_id"),
        ("PolicyDecision", "policy_decision_id"),
        ("ActionReceipt", "action_receipt_id"),
        ("ActionRecord", "action_id"),
        ("CapabilityDescriptor", "capability_id"),
        ("ToolIntent", "tool_intent_id"),
        ("ToolResult", "tool_result_id"),
        ("ReleaseCandidate", "release_candidate_id"),
        ("EvalCase", "eval_case_id"),
        ("EvalDataset", "eval_dataset_id"),
        ("EvalConfig", "eval_config_id"),
        ("EvalRun", "eval_run_id"),
        ("EvalResult", "eval_result_id"),
        ("QualityGateDecision", "quality_gate_decision_id"),
        ("SecurityGateDecision", "security_gate_decision_id"),
        ("OperationalReadinessDecision", "operational_readiness_decision_id"),
        ("ReleaseDecision", "release_decision_id"),
        ("EvolutionTrigger", "evolution_trigger_id"),
        ("EvolutionRun", "evolution_run_id"),
        ("GenomeManifest", "genome_id"),
        ("MutationProposal", "mutation_proposal_id"),
        ("EvolutionAuthorityPolicy", "evolution_authority_policy_id"),
        ("PrincipalContext", "principal_id"),
        ("ReleaseManifest", "release_id"),
    ],
)
def test_con_001_canonical_object_id_must_match_meta_object_id(
    contract_name: str, id_field: str
) -> None:
    instance = {
        "meta": {"contract_name": contract_name, "object_id": "canonical-id"},
        id_field: "different-id",
    }
    with pytest.raises(ValidationError, match=id_field):
        validate_canonical_invariants(instance, {"title": contract_name})


def test_con_001_contract_version_must_match_current_schema_version() -> None:
    instance = principal_context()
    instance["meta"]["contract_version"] = "9.9.9"

    with pytest.raises(ValidationError, match="current schema version 1.0.0"):
        validate_instance(
            instance,
            SCHEMAS / "security/principal-context.schema.json",
            SCHEMAS,
        )


def test_con_008_principal_context_tenant_must_match_meta_tenant() -> None:
    instance = principal_context()
    instance["tenant_id"] = "tenant-b"
    with pytest.raises(ValidationError, match="tenant_id"):
        validate_instance(instance, SCHEMAS / "security/principal-context.schema.json", SCHEMAS)


def test_con_010_release_manifest_uses_version_sets_not_singular_aliases() -> None:
    instance = release_manifest()
    validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)

    invalid = copy.deepcopy(instance)
    invalid["agent_version"] = "agent-1@1"
    with pytest.raises(ValidationError):
        validate_instance(invalid, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)


def test_rel_005_release_manifest_rejects_unknown_lifecycle_status() -> None:
    instance = release_manifest()
    instance["lifecycle_status"] = "invented_state"
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "required_field",
    [
        "contract_version_ranges",
        "compatibility_matrix_ref",
        "migration_refs",
        "rollout",
        "rollback",
        "observation_window",
    ],
)
def test_rel_005_release_manifest_rejects_missing_delivery_contract(
    required_field: str,
) -> None:
    instance = release_manifest()
    del instance[required_field]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("section", "required_field"),
    [
        ("rollout", "slice_refs"),
        ("rollout", "stop_condition_refs"),
        ("rollout", "capacity_limit_ref"),
        ("rollback", "target_release_ref"),
        ("rollback", "irreversible_migration_refs"),
        ("rollback", "recovery_precondition_refs"),
        ("observation_window", "duration_seconds"),
        ("observation_window", "success_condition_refs"),
        ("observation_window", "failure_condition_refs"),
    ],
)
def test_rel_005_release_manifest_rejects_missing_delivery_plan_field(
    section: str, required_field: str
) -> None:
    instance = release_manifest()
    del instance[section][required_field]
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("section", "field", "invalid_value"),
    [
        ("rollout", "slice_refs", []),
        ("rollout", "stop_condition_refs", []),
        ("observation_window", "duration_seconds", 0),
        ("observation_window", "success_condition_refs", []),
        ("observation_window", "failure_condition_refs", []),
    ],
)
def test_rel_005_release_manifest_rejects_unsafe_delivery_plan(
    section: str, field: str, invalid_value: object
) -> None:
    instance = release_manifest()
    instance[section][field] = invalid_value
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)


@pytest.mark.parametrize("disposition", ["executed", "failed", "unresolved"])
def test_act_018_action_record_accepts_execution_terminal_with_complete_chain(
    disposition: str,
) -> None:
    validate_instance(
        action_record(disposition=disposition),
        SCHEMAS / "tool/action-record.schema.json",
        SCHEMAS,
    )


@pytest.mark.parametrize("disposition", ["executed", "failed", "unresolved"])
@pytest.mark.parametrize(
    "missing_ref",
    ["policy_decision_ref", "idempotency_reservation_ref", "latest_receipt_ref"],
)
def test_act_018_action_record_rejects_execution_terminal_without_execution_chain(
    disposition: str,
    missing_ref: str,
) -> None:
    instance = action_record(disposition=disposition)
    instance[missing_ref] = None
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


def test_act_018_action_record_latest_receipt_must_be_last_receipt() -> None:
    instance = action_record()
    instance["receipt_refs"] = ["receipt-1", "receipt-2"]
    instance["latest_receipt_ref"] = "receipt-1"

    with pytest.raises(ValidationError, match="last receipt_refs entry"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


def test_act_018_action_record_nonempty_receipts_require_latest_receipt() -> None:
    instance = action_record(disposition="invalid")
    instance["latest_receipt_ref"] = None

    with pytest.raises(ValidationError, match="last receipt_refs entry"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


def test_act_018_action_record_empty_receipts_require_null_latest_receipt() -> None:
    instance = action_record()
    instance["receipt_refs"] = []

    with pytest.raises(ValidationError, match="must be null when receipt_refs is empty"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("disposition", ["executed", "failed", "unresolved"])
def test_act_018_action_record_execution_terminal_requires_receipt_history(
    disposition: str,
) -> None:
    instance = action_record(disposition=disposition)
    instance["receipt_refs"] = []
    instance["latest_receipt_ref"] = None

    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("disposition", "policy_ref", "approval_ref"),
    [
        ("denied", "policy-decision-1", None),
        ("approval_rejected", None, "approval-request-1"),
        ("invalid", None, None),
    ],
)
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("idempotency_reservation_ref", "reservation-after-terminal"),
        ("latest_receipt_ref", "receipt-after-terminal"),
        ("receipt_refs", ["receipt-after-terminal"]),
    ],
)
def test_act_018_nonexecuted_action_cannot_retain_forbidden_execution_artifacts(
    disposition: str,
    policy_ref: str | None,
    approval_ref: str | None,
    field: str,
    invalid_value: object,
) -> None:
    instance = action_record(disposition=disposition)
    instance["policy_decision_ref"] = policy_ref
    instance["approval_request_ref"] = approval_ref
    instance["idempotency_reservation_ref"] = None
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None
    instance[field] = invalid_value
    if field == "latest_receipt_ref":
        instance["receipt_refs"] = ["receipt-after-terminal"]
    elif field == "receipt_refs":
        instance["latest_receipt_ref"] = "receipt-after-terminal"

    with pytest.raises(ValidationError, match="cannot retain"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("policy_decision_ref", "policy-after-invalid"),
        ("approval_request_ref", "approval-after-invalid"),
    ],
)
def test_act_018_invalid_action_cannot_retain_pre_execution_authority_or_lease(
    field: str,
    invalid_value: object,
) -> None:
    instance = action_record(disposition="invalid")
    instance["policy_decision_ref"] = None
    instance["approval_request_ref"] = None
    instance["idempotency_reservation_ref"] = None
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None
    instance[field] = invalid_value

    with pytest.raises(ValidationError, match="cannot retain"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("latest_receipt_ref", "receipt-after-cancel"),
        ("receipt_refs", ["receipt-after-cancel"]),
    ],
)
def test_act_018_cancelled_action_cannot_retain_receipts(
    field: str,
    invalid_value: object,
) -> None:
    instance = action_record(disposition="cancelled")
    instance["policy_decision_ref"] = None
    instance["idempotency_reservation_ref"] = "reservation-before-cancel"
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None
    instance[field] = invalid_value
    if field == "latest_receipt_ref":
        instance["receipt_refs"] = ["receipt-after-cancel"]
    else:
        instance["latest_receipt_ref"] = "receipt-after-cancel"

    with pytest.raises(ValidationError, match="cannot retain"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


def test_act_018_cancelled_action_may_retain_committed_reservation() -> None:
    instance = action_record(disposition="cancelled")
    instance["policy_decision_ref"] = "policy-before-cancel"
    instance["approval_request_ref"] = "approval-before-cancel"
    instance["idempotency_reservation_ref"] = "reservation-before-cancel"
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None

    validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    "disposition",
    ["denied", "approval_rejected", "invalid", "cancelled"],
)
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("lease_fencing_token", 1),
        (
            "reconciliation_state",
            {
                "policy_ref": "reconciliation-policy-1",
                "observation_refs": ["receipt-1"],
                "attempts": 1,
                "last_observed_at": "2026-08-14T14:00:01Z",
                "next_check_at": None,
                "exhausted": False,
            },
        ),
    ],
)
def test_act_018_nonexecuted_terminal_cannot_retain_execution_state(
    disposition: str,
    field: str,
    invalid_value: object,
) -> None:
    instance = action_record(disposition=disposition)
    instance["policy_decision_ref"] = (
        "policy-decision-1" if disposition in {"denied", "cancelled"} else None
    )
    instance["approval_request_ref"] = (
        "approval-request-1" if disposition in {"approval_rejected", "cancelled"} else None
    )
    instance["idempotency_reservation_ref"] = (
        "reservation-before-cancel" if disposition == "cancelled" else None
    )
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None
    instance["reconciliation_state"] = None
    instance[field] = invalid_value

    with pytest.raises(ValidationError, match="execution lease or reconciliation state"):
        validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("disposition", "policy_ref", "approval_ref"),
    [
        ("denied", "policy-decision-1", None),
        ("approval_rejected", None, "approval-request-1"),
        ("invalid", None, None),
        ("cancelled", None, None),
    ],
)
def test_act_018_action_record_nonexecuted_terminal_does_not_require_reservation(
    disposition: str,
    policy_ref: str | None,
    approval_ref: str | None,
) -> None:
    instance = action_record(disposition=disposition)
    instance["policy_decision_ref"] = policy_ref
    instance["approval_request_ref"] = approval_ref
    instance["idempotency_reservation_ref"] = None
    instance["latest_receipt_ref"] = None
    instance["receipt_refs"] = []
    instance["lease_fencing_token"] = None
    instance["reconciliation_state"] = None
    validate_instance(instance, SCHEMAS / "tool/action-record.schema.json", SCHEMAS)


def test_run_008_run_record_accepts_completed_without_wait_or_pending_actions() -> None:
    validate_instance(run_record(), SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("wait_condition_refs", ["still-waiting"]),
        ("pending_action_refs", ["unknown-action"]),
        ("result_ref", None),
        ("error_ref", "error-1"),
    ],
)
def test_run_008_run_record_rejects_invalid_completed_state(
    field: str, invalid_value: object
) -> None:
    instance = run_record()
    instance[field] = invalid_value
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


def test_run_008_terminal_run_rejects_live_lease() -> None:
    instance = run_record()
    instance["lease"] = run_lease()

    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("phase", ["admitting", "running"])
def test_run_008_active_run_requires_lease(phase: str) -> None:
    instance = run_record_in_phase(phase, lease=None)

    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("phase", ["admitting", "running"])
def test_run_008_active_run_accepts_live_lease(phase: str) -> None:
    instance = run_record_in_phase(phase, lease=run_lease())

    validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("lease", [None, run_lease()], ids=["waiting", "leased"])
def test_run_008_retrying_run_allows_optional_lease(
    lease: dict[str, Any] | None,
) -> None:
    instance = run_record_in_phase("retrying", lease=lease)

    validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("phase", ["queued", "waiting", "paused"])
def test_run_008_inactive_run_rejects_live_lease(phase: str) -> None:
    instance = run_record_in_phase(phase, lease=run_lease())

    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "acquired_at",
            "2026-08-14T14:00:01Z",
            "acquired_at must be earlier than or equal to heartbeat_at",
        ),
        (
            "heartbeat_at",
            "2026-08-14T15:00:00Z",
            "heartbeat_at must be earlier than expires_at",
        ),
        (
            "heartbeat_at",
            "2026-08-14T15:00:01Z",
            "heartbeat_at must be earlier than expires_at",
        ),
    ],
)
def test_run_008_run_lease_rejects_invalid_internal_time_order(
    field: str,
    value: str,
    message: str,
) -> None:
    lease = run_lease()
    lease[field] = value
    instance = run_record_in_phase("running", lease=lease)

    with pytest.raises(ValidationError, match=message):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


def test_run_008_run_lease_rejects_submicrosecond_time_inversion() -> None:
    lease = run_lease()
    lease.update(
        {
            "acquired_at": "2026-08-14T14:00:00.0000002Z",
            "heartbeat_at": "2026-08-14T14:00:00.0000001Z",
        }
    )

    with pytest.raises(ValidationError, match="acquired_at must be earlier"):
        validate_instance(
            run_record_in_phase("running", lease=lease),
            SCHEMAS / "runtime/run-record.schema.json",
            SCHEMAS,
        )


def test_run_008_run_lease_accepts_exact_offset_equivalence_and_arbitrary_precision() -> None:
    lease = run_lease()
    lease.update(
        {
            "acquired_at": "2026-08-14T14:00:00.123456789123456789+08:00",
            "heartbeat_at": "2026-08-14T06:00:00.123456789123456789Z",
            "expires_at": "2026-08-14T06:00:00.123456789123456790Z",
        }
    )

    validate_instance(
        run_record_in_phase("running", lease=lease),
        SCHEMAS / "runtime/run-record.schema.json",
        SCHEMAS,
    )


def test_run_008_run_lease_applies_negative_offset_with_correct_sign() -> None:
    lease = run_lease()
    lease.update(
        {
            "acquired_at": "2026-08-14T00:00:00.123456789-01:00",
            "heartbeat_at": "2026-08-14T01:00:00.123456789Z",
            "expires_at": "2026-08-14T01:00:00.123456790Z",
        }
    )

    validate_instance(
        run_record_in_phase("running", lease=lease),
        SCHEMAS / "runtime/run-record.schema.json",
        SCHEMAS,
    )


def test_run_008_run_lease_rejects_unknown_negative_zero_offset() -> None:
    lease = run_lease()
    lease["acquired_at"] = "2026-08-14T14:00:00-00:00"

    with pytest.raises(ValidationError, match="known RFC 3339 timezone offset"):
        validate_instance(
            run_record_in_phase("running", lease=lease),
            SCHEMAS / "runtime/run-record.schema.json",
            SCHEMAS,
        )


@pytest.mark.parametrize(
    ("acquired_at", "heartbeat_at", "expires_at"),
    [
        (
            "9999-12-31T23:59:59.000000000000000001-23:59",
            "9999-12-31T23:59:59.000000000000000002-23:59",
            "9999-12-31T23:59:59.000000000000000003-23:59",
        ),
        (
            "0001-01-01T00:00:00.000000000000000001+23:59",
            "0001-01-01T00:00:00.000000000000000002+23:59",
            "0001-01-01T00:00:00.000000000000000003+23:59",
        ),
    ],
    ids=["utc-overflow", "utc-underflow"],
)
def test_run_008_run_lease_accepts_rfc3339_year_offset_boundaries(
    acquired_at: str,
    heartbeat_at: str,
    expires_at: str,
) -> None:
    lease = run_lease()
    lease.update(
        {
            "acquired_at": acquired_at,
            "heartbeat_at": heartbeat_at,
            "expires_at": expires_at,
        }
    )

    validate_instance(
        run_record_in_phase("running", lease=lease),
        SCHEMAS / "runtime/run-record.schema.json",
        SCHEMAS,
    )


def test_run_008_run_lease_allows_acquire_and_heartbeat_at_same_time() -> None:
    lease = run_lease()
    lease["acquired_at"] = lease["heartbeat_at"]

    validate_instance(
        run_record_in_phase("running", lease=lease),
        SCHEMAS / "runtime/run-record.schema.json",
        SCHEMAS,
    )


def test_run_008_static_run_lease_validation_does_not_assert_wall_clock_freshness() -> None:
    lease = run_lease()
    lease.update(
        {
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T00:01:00Z",
            "expires_at": "2020-01-01T00:02:00Z",
        }
    )

    validate_instance(
        run_record_in_phase("running", lease=lease),
        SCHEMAS / "runtime/run-record.schema.json",
        SCHEMAS,
    )


def test_run_008_run_lease_rejects_noncanonical_worker_epoch_aliases() -> None:
    instance = run_record_in_phase(
        "running",
        lease={
            "worker_ref": "worker-1",
            "lease_epoch": 1,
            "fencing_token": 1,
            "heartbeat_at": "2026-08-14T14:00:00Z",
            "expires_at": "2026-08-14T15:00:00Z",
        },
    )

    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


@pytest.mark.parametrize("phase", ["queued", "admitting", "running", "retrying", "paused"])
def test_run_008_run_record_rejects_wait_conditions_outside_waiting(phase: str) -> None:
    instance = run_record()
    instance.update(
        {
            "phase": phase,
            "completion_disposition": None,
            "wait_condition_refs": ["stale-wait-condition"],
            "terminal_reason_codes": [],
            "result_ref": None,
        }
    )
    if phase in {"admitting", "running"}:
        instance["lease"] = run_lease()
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)


def test_run_008_run_record_accepts_registered_wait() -> None:
    instance = run_record()
    instance.update(
        {
            "phase": "waiting",
            "completion_disposition": None,
            "wait_reason": "approval",
            "wait_condition_refs": ["approval-request-1"],
            "terminal_reason_codes": [],
            "result_ref": None,
        }
    )
    validate_instance(instance, SCHEMAS / "runtime/run-record.schema.json", SCHEMAS)
