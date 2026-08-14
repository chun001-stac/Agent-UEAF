from __future__ import annotations

import copy
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from ueaf.common.schema_registry import validate_instance

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def meta(contract_name: str, object_id: str) -> dict[str, object]:
    return {
        "contract_name": contract_name,
        "contract_version": "1.0.0",
        "object_id": object_id,
        "tenant_id": "tenant-a",
        "created_at": "2026-08-14T14:00:00Z",
        "producer": "test",
        "producer_version": "1.0.0",
        "classification": "internal",
        "purpose": ["test"],
        "provenance": [],
    }


def test_event_envelope_accepts_canonical_event_name() -> None:
    instance = {
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
        "payload": {},
        "classification": "internal",
        "purpose": ["runtime"],
    }
    validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_event_envelope_rejects_pascal_case_alias() -> None:
    instance = {
        "event_id": "evt-1",
        "event_name": "TaskQueued",
        "event_version": "1.0.0",
        "occurred_at": "2026-08-14T14:00:00Z",
        "recorded_at": "2026-08-14T14:00:01Z",
        "tenant_id": "tenant-a",
        "aggregate_type": "RunRecord",
        "aggregate_id": "run-1",
        "aggregate_version": 1,
        "sequence": 1,
        "producer": "RunCoordinator",
        "producer_version": "1.0.0",
        "correlation_id": "req-1",
        "trace_id": "trace-1",
        "payload_schema_ref": "schema://run-created/1.0.0",
        "payload": {},
        "classification": "internal",
        "purpose": ["runtime"],
    }
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "events/event-envelope.schema.json", SCHEMAS)


def test_evolution_run_requires_null_disposition_before_terminal() -> None:
    instance = {
        "meta": meta("EvolutionRun", "er-1"),
        "evolution_run_id": "er-1",
        "subject_ref": "agent-1",
        "baseline_genome_ref": "genome-1",
        "trigger_ref": "trigger-1",
        "phase": "analyzing",
        "disposition": "no_evolution_needed",
        "budget_ref": "budget-1",
        "mutable_scope": ["context_policy"],
        "strategy_ref": "strategy-1",
        "active_working_set_ref": "ws-1",
        "revision": 1,
        "created_at": "2026-08-14T14:00:00Z",
        "updated_at": "2026-08-14T14:00:01Z",
    }
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "evolution/evolution-run.schema.json", SCHEMAS)


def test_mutation_proposal_requires_machine_changes() -> None:
    instance = {
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
        "hypothesis": "recall improves",
        "expected_gain": {},
        "expected_cost": {},
        "risk_refs": [],
        "created_by": "strategy-1",
        "created_at": "2026-08-14T14:00:00Z",
    }
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "evolution/mutation-proposal.schema.json", SCHEMAS)


def test_principal_context_rejects_second_field_vocabulary() -> None:
    instance = {
        "meta": meta("PrincipalContext", "principal-1"),
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
        "subject_id": "legacy-alias",
    }
    with pytest.raises(ValidationError):
        validate_instance(instance, SCHEMAS / "security/principal-context.schema.json", SCHEMAS)


def test_release_manifest_uses_version_sets_not_singular_aliases() -> None:
    instance = {
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
        "quality_gate_decision_ref": "qg-1",
        "security_gate_decision_ref": "sg-1",
        "operational_readiness_decision_ref": "og-1",
        "release_decision_ref": "rd-1",
        "integrity_ref": "sha256:test",
    }
    validate_instance(instance, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)

    invalid = copy.deepcopy(instance)
    invalid["agent_version"] = "agent-1@1"
    with pytest.raises(ValidationError):
        validate_instance(invalid, SCHEMAS / "release/release-manifest.schema.json", SCHEMAS)
