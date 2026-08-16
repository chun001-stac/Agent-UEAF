from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError

from ueaf.common.schema_registry import validate_instance, validate_release_activation
from ueaf.ports import ReleaseActivationVerifier

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


class RecordingReleaseActivationVerifier:
    """仅用于测试 Phase 4 所需信任边界的全允许假实现。"""

    def __init__(
        self,
        *,
        fail_method: str | None = None,
        failure_result: object = False,
    ) -> None:
        self.fail_method = fail_method
        self.failure_result = failure_result
        self.calls: list[tuple[str, str]] = []

    def _record(self, method: str, contract_name: str) -> bool:
        self.calls.append((method, contract_name))
        if method == self.fail_method:
            return cast(bool, self.failure_result)
        return True

    def verify_integrity(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        return self._record("integrity", contract_name)

    def verify_evidence_access(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        return self._record("evidence", contract_name)

    def verify_authority_role_and_trust(
        self,
        contract_name: str,
        authority_ref: str,
        instance: Mapping[str, object],
    ) -> bool:
        return self._record("authority", contract_name)

    def verify_waiver_conflicts(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        return self._record("waiver", contract_name)

    def verify_scope_coverage(
        self,
        contract_name: str,
        expected_scope: Mapping[str, object],
        instance: Mapping[str, object],
    ) -> bool:
        return self._record("scope", contract_name)

    def verify_rollback_compatibility(
        self,
        release_candidate: Mapping[str, object],
        release_manifest: Mapping[str, object],
    ) -> bool:
        return self._record("rollback", "ReleaseCandidate+ReleaseManifest")


class CopyMutatingReleaseActivationVerifier(RecordingReleaseActivationVerifier):
    """修改一次性回调入参，以证明钩子从不共享主状态。"""

    def __init__(self, caller_manifest: Mapping[str, object]) -> None:
        super().__init__()
        self.caller_manifest = caller_manifest

    def verify_integrity(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        if contract_name == "ReleaseManifest":
            assert instance is not self.caller_manifest
            cast(dict[str, object], instance)["lifecycle_status"] = "withdrawn"
        return super().verify_integrity(contract_name, instance)

    def verify_evidence_access(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        if contract_name == "ReleaseManifest":
            assert instance.get("lifecycle_status") == "active"
        return super().verify_evidence_access(contract_name, instance)


class CallerMutatingReleaseActivationVerifier(RecordingReleaseActivationVerifier):
    """在回调期间篡改所捕获调用方对象的恶意假实现。"""

    def __init__(self, caller_manifest: dict[str, Any]) -> None:
        super().__init__()
        self.caller_manifest = caller_manifest
        self.mutated = False

    def verify_integrity(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        if contract_name == "ReleaseManifest" and not self.mutated:
            self.caller_manifest["lifecycle_status"] = "withdrawn"
            self.mutated = True
        return super().verify_integrity(contract_name, instance)


def contract_meta(
    contract_name: str,
    object_id: str,
    *,
    tenant_id: str = "tenant-1",
    created_at: str = "2026-08-15T08:00:00Z",
) -> dict[str, Any]:
    return {
        "contract_name": contract_name,
        "contract_version": "1.0.0",
        "object_id": object_id,
        "tenant_id": tenant_id,
        "created_at": created_at,
        "producer": "ueaf-test",
        "producer_version": "1.0.0",
        "classification": "internal",
        "purpose": ["conformance"],
        "provenance": [{"source_ref": "fixture-1"}],
    }


def authorization_request() -> dict[str, Any]:
    return {
        "meta": contract_meta("AuthorizationRequest", "authorization-request-1"),
        "authorization_request_id": "authorization-request-1",
        "tenant_id": "tenant-1",
        "principal_context_ref": "principal-1",
        "workload_identity_ref": None,
        "delegation_context_ref": None,
        "action": "tool.read",
        "resource": {"resource_ref": "document-1"},
        "environment": {"name": "prod"},
        "purpose": "answer_request",
        "risk_level": "low",
        "input_digest": "sha256:authorization-input",
        "policy_bundle_version": "policy-bundle-1",
        "requested_at": "2026-08-15T09:00:00Z",
    }


def policy_decision() -> dict[str, Any]:
    return {
        "meta": contract_meta("PolicyDecision", "policy-decision-1"),
        "policy_decision_id": "policy-decision-1",
        "authorization_request_id": "authorization-request-1",
        "tenant_id": "tenant-1",
        "principal_context_ref": "principal-1",
        "action": "tool.read",
        "resource": {"resource_ref": "document-1"},
        "environment": {"name": "prod"},
        "outcome": "allow",
        "constraints": {},
        "reason_codes": [],
        "policy_versions": ["policy-1"],
        "input_hash": "sha256:authorization-input",
        "evaluated_at": "2026-08-15T09:01:00Z",
        "expires_at": "2026-08-15T13:00:00Z",
    }


@pytest.mark.parametrize(
    ("relative_schema", "instance"),
    [
        (Path("security/authorization-request.schema.json"), authorization_request()),
        (Path("security/policy-decision.schema.json"), policy_decision()),
    ],
    ids=["AuthorizationRequest", "PolicyDecision"],
)
@pytest.mark.test_id("SEC-001")
def test_con_001_top_level_tenant_must_match_contract_meta(
    relative_schema: Path, instance: dict[str, Any]
) -> None:
    instance["tenant_id"] = "tenant-2"

    with pytest.raises(ValidationError, match=r"tenant_id must equal meta\.tenant_id"):
        validate_instance(instance, SCHEMAS / relative_schema, SCHEMAS)


def release_candidate() -> dict[str, Any]:
    return {
        "meta": contract_meta("ReleaseCandidate", "candidate-1"),
        "release_candidate_id": "candidate-1",
        "genome_manifest_ref": "genome-1",
        "mutation_proposal_refs": ["mutation-1"],
        "baseline_ref": None,
        "candidate_builder_ref": "builder-1",
        "candidate_builder_version": "1.0.0",
        "components": [
            {
                "component_type": component_type,
                "component_ref": f"{component_type}-1",
                "version": "1.0.0",
                "digest": f"sha256:{component_type}",
                "provenance_refs": [f"provenance-{component_type}-1"],
            }
            for component_type in (
                "agent",
                "prompt",
                "schema",
                "model_route",
                "capability",
                "adapter",
                "knowledge_index",
                "memory_policy",
                "policy",
            )
        ],
        "contract_version_ranges": {"EventEnvelope": ">=1.0.0,<2.0.0"},
        "compatibility_matrix_ref": "compatibility-1",
        "dependency_lock_ref": "dependency-lock-1",
        "dependency_refs": [],
        "dependency_digest": "sha256:dependencies",
        "migration_refs": ["migration-1"],
        "sbom_ref": "sbom-1",
        "sbom_digest": "sha256:sbom",
        "build_provenance_refs": ["provenance-1"],
        "build_evidence_refs": ["evidence-build-1"],
        "candidate_digest": "sha256:candidate",
        "built_at": "2026-08-15T09:00:00Z",
        "integrity_ref": "integrity-candidate-1",
    }


def quality_gate_decision() -> dict[str, Any]:
    return {
        "meta": contract_meta(
            "QualityGateDecision",
            "quality-gate-1",
            created_at="2026-08-15T09:30:00Z",
        ),
        "quality_gate_decision_id": "quality-gate-1",
        "candidate_ref": "candidate-1",
        "environment": "prod",
        "scope": {"region": "cn", "tenant_id": "tenant-1"},
        "outcome": "pass",
        "status": "active",
        "baseline_ref": "baseline-1",
        "threshold_profile_version": "thresholds-1",
        "evidence_graph_ref": "evidence-graph-1",
        "evidence_refs": ["quality-evidence-1"],
        "hard_failure_refs": [],
        "condition_refs": [],
        "waiver_refs": [],
        "issued_by": "quality-authority-1",
        "issued_at": "2026-08-15T10:00:00Z",
        "expires_at": "2026-08-15T14:00:00Z",
        "integrity_ref": "integrity-quality-1",
    }


def security_gate_decision() -> dict[str, Any]:
    return {
        "meta": contract_meta(
            "SecurityGateDecision",
            "security-gate-1",
            created_at="2026-08-15T09:30:00Z",
        ),
        "security_gate_decision_id": "security-gate-1",
        "candidate_ref": "candidate-1",
        "environment": "prod",
        "scope": {"region": "cn", "tenant_id": "tenant-1"},
        "outcome": "pass",
        "status": "active",
        "security_policy_version": "security-policy-1",
        "evidence_refs": ["security-evidence-1"],
        "hard_failure_refs": [],
        "condition_refs": [],
        "waiver_refs": [],
        "issued_by": "security-authority-1",
        "issued_at": "2026-08-15T10:05:00Z",
        "expires_at": "2026-08-15T14:00:00Z",
        "integrity_ref": "integrity-security-1",
    }


def operational_readiness_decision() -> dict[str, Any]:
    return {
        "meta": contract_meta(
            "OperationalReadinessDecision",
            "operational-gate-1",
            created_at="2026-08-15T09:30:00Z",
        ),
        "operational_readiness_decision_id": "operational-gate-1",
        "candidate_ref": "candidate-1",
        "environment": "prod",
        "scope": {"region": "cn", "tenant_id": "tenant-1"},
        "outcome": "pass",
        "status": "active",
        "readiness_policy_version": "readiness-policy-1",
        "slo_profile_ref": "slo-1",
        "capacity_evidence_refs": ["capacity-evidence-1"],
        "observability_evidence_refs": ["observability-evidence-1"],
        "migration_evidence_refs": ["migration-evidence-1"],
        "rollback_evidence_refs": ["rollback-evidence-1"],
        "recovery_evidence_refs": ["recovery-evidence-1"],
        "condition_refs": [],
        "waiver_refs": [],
        "issued_by": "operations-authority-1",
        "issued_at": "2026-08-15T10:10:00Z",
        "expires_at": "2026-08-15T14:00:00Z",
        "integrity_ref": "integrity-operational-1",
    }


def release_decision() -> dict[str, Any]:
    return {
        "meta": contract_meta(
            "ReleaseDecision",
            "release-decision-1",
            created_at="2026-08-15T10:30:00Z",
        ),
        "release_decision_id": "release-decision-1",
        "candidate_ref": "candidate-1",
        "environment": "prod",
        "scope": {"region": "cn", "tenant_id": "tenant-1"},
        "outcome": "approved",
        "status": "active",
        "release_policy_version": "release-policy-1",
        "quality_gate_decision_ref": "quality-gate-1",
        "security_gate_decision_ref": "security-gate-1",
        "operational_readiness_decision_ref": "operational-gate-1",
        "evidence_refs": ["release-evidence-1"],
        "condition_refs": [],
        "waiver_refs": [],
        "rollout_constraints": {"max_parallel": 1},
        "issued_by": "release-authority-1",
        "issued_at": "2026-08-15T11:00:00Z",
        "expires_at": "2026-08-15T14:00:00Z",
        "integrity_ref": "integrity-release-decision-1",
    }


def release_manifest() -> dict[str, Any]:
    return {
        "meta": contract_meta(
            "ReleaseManifest",
            "release-1",
            created_at="2026-08-15T11:30:00Z",
        ),
        "release_id": "release-1",
        "environment": "prod",
        "lifecycle_status": "active",
        "agent_versions": ["agent-1@1.0.0"],
        "prompt_versions": ["prompt-1@1.0.0"],
        "schema_versions": ["schema-1@1.0.0"],
        "model_route_versions": ["model_route-1@1.0.0"],
        "capability_versions": ["capability-1@1.0.0"],
        "adapter_versions": ["adapter-1@1.0.0"],
        "knowledge_index_versions": ["knowledge_index-1@1.0.0"],
        "memory_policy_versions": ["memory_policy-1@1.0.0"],
        "policy_versions": ["policy-1@1.0.0"],
        "contract_version_ranges": {"EventEnvelope": ">=1.0.0,<2.0.0"},
        "compatibility_matrix_ref": "compatibility-1",
        "migration_refs": ["migration-1"],
        "quality_gate_decision_ref": "quality-gate-1",
        "security_gate_decision_ref": "security-gate-1",
        "operational_readiness_decision_ref": "operational-gate-1",
        "release_decision_ref": "release-decision-1",
        "rollout": {
            "slice_refs": ["slice-1"],
            "stop_condition_refs": ["stop-condition-1"],
            "capacity_limit_ref": "capacity-limit-1",
        },
        "rollback": {
            "target_release_ref": "release-0",
            "irreversible_migration_refs": [],
            "recovery_precondition_refs": ["recovery-precondition-1"],
        },
        "observation_window": {
            "duration_seconds": 300,
            "success_condition_refs": ["success-condition-1"],
            "failure_condition_refs": ["failure-condition-1"],
        },
        "integrity_ref": "integrity-release-1",
    }


def release_activation_chain() -> dict[str, dict[str, Any]]:
    return {
        "candidate": release_candidate(),
        "quality": quality_gate_decision(),
        "security": security_gate_decision(),
        "operational": operational_readiness_decision(),
        "release_decision": release_decision(),
        "manifest": release_manifest(),
    }


def validate_chain(
    chain: dict[str, dict[str, Any]],
    *,
    expected_candidate_ref: str = "candidate-1",
    now: datetime = NOW,
    verifier: ReleaseActivationVerifier | None = None,
) -> None:
    trusted_verifier = verifier or RecordingReleaseActivationVerifier()
    validate_release_activation(
        chain["candidate"],
        chain["quality"],
        chain["security"],
        chain["operational"],
        chain["release_decision"],
        chain["manifest"],
        SCHEMAS,
        expected_candidate_ref=expected_candidate_ref,
        verifier=trusted_verifier,
        now=now,
    )


def test_rel_004_release_activation_accepts_complete_active_chain() -> None:
    validate_chain(release_activation_chain())


def test_rel_004_release_activation_invokes_every_trusted_verifier_hook() -> None:
    verifier = RecordingReleaseActivationVerifier()
    validate_chain(release_activation_chain(), verifier=verifier)

    contract_names = {
        "ReleaseCandidate",
        "QualityGateDecision",
        "SecurityGateDecision",
        "OperationalReadinessDecision",
        "ReleaseDecision",
        "ReleaseManifest",
    }
    for method in ("integrity", "evidence", "authority", "waiver", "scope"):
        assert {contract for called, contract in verifier.calls if called == method} == (
            contract_names
        )
    assert verifier.calls.count(("rollback", "ReleaseCandidate+ReleaseManifest")) == 1


def test_rel_004_release_activation_isolates_every_verifier_callback_copy() -> None:
    chain = release_activation_chain()
    verifier = CopyMutatingReleaseActivationVerifier(chain["manifest"])

    validate_chain(chain, verifier=verifier)

    assert chain["manifest"]["lifecycle_status"] == "active"


def test_rel_004_release_activation_rejects_caller_mutation_during_verification() -> None:
    chain = release_activation_chain()
    verifier = CallerMutatingReleaseActivationVerifier(chain["manifest"])

    with pytest.raises(ValidationError, match="caller input changed"):
        validate_chain(chain, verifier=verifier)


@pytest.mark.parametrize(
    "method",
    ["integrity", "evidence", "authority", "waiver", "scope", "rollback"],
)
def test_rel_004_release_activation_fails_closed_when_verifier_rejects(
    method: str,
) -> None:
    verifier = RecordingReleaseActivationVerifier(fail_method=method)

    with pytest.raises(ValidationError, match="verifier rejected"):
        validate_chain(release_activation_chain(), verifier=verifier)


def test_rel_004_release_activation_verifier_must_return_literal_true() -> None:
    verifier = RecordingReleaseActivationVerifier(
        fail_method="integrity",
        failure_result=1,
    )

    with pytest.raises(ValidationError, match="verifier rejected"):
        validate_chain(release_activation_chain(), verifier=verifier)


def test_rel_004_release_activation_rejects_explicitly_missing_verifier() -> None:
    chain = release_activation_chain()

    with pytest.raises(ValidationError, match="requires a trusted verifier"):
        validate_release_activation(
            chain["candidate"],
            chain["quality"],
            chain["security"],
            chain["operational"],
            chain["release_decision"],
            chain["manifest"],
            SCHEMAS,
            expected_candidate_ref="candidate-1",
            verifier=None,
            now=NOW,
        )


def test_rel_004_release_activation_verifier_argument_is_required() -> None:
    chain = release_activation_chain()

    with pytest.raises(TypeError, match="verifier"):
        validate_release_activation(  # type: ignore[call-arg]
            chain["candidate"],
            chain["quality"],
            chain["security"],
            chain["operational"],
            chain["release_decision"],
            chain["manifest"],
            SCHEMAS,
            expected_candidate_ref="candidate-1",
            now=NOW,
        )


@pytest.mark.parametrize("outcome", ["fail", "conditional"])
def test_rel_004_release_activation_rejects_non_passing_gate(outcome: str) -> None:
    chain = release_activation_chain()
    chain["quality"]["outcome"] = outcome
    if outcome == "conditional":
        chain["quality"]["condition_refs"] = ["condition-1"]

    with pytest.raises(ValidationError, match=r"QualityGateDecision\.outcome must be pass"):
        validate_chain(chain)


@pytest.mark.parametrize("gate_name", ["quality", "security"])
@pytest.mark.test_id("REL-004")
def test_eval_002_release_activation_rejects_hard_failure_on_passing_gate(
    gate_name: str,
) -> None:
    chain = release_activation_chain()
    chain[gate_name]["hard_failure_refs"] = ["hard-failure-1"]

    with pytest.raises(ValidationError, match=r"hard_failure_refs must be empty for pass"):
        validate_chain(chain)


@pytest.mark.parametrize("status", ["expired", "revoked"])
def test_rel_004_release_activation_rejects_inactive_gate_status(status: str) -> None:
    chain = release_activation_chain()
    chain["security"]["status"] = status

    with pytest.raises(ValidationError, match=r"SecurityGateDecision\.status must be active"):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_wall_clock_expired_gate() -> None:
    chain = release_activation_chain()
    chain["operational"]["expires_at"] = "2026-08-15T11:59:59Z"

    with pytest.raises(ValidationError, match="OperationalReadinessDecision is expired"):
        validate_chain(chain)


@pytest.mark.parametrize(
    ("contract_name", "field", "value", "message"),
    [
        ("security", "candidate_ref", "candidate-2", "candidate_ref"),
        ("operational", "environment", "staging", "environment"),
        ("release_decision", "scope", {"region": "us"}, "scope"),
        ("release_decision", "quality_gate_decision_ref", "quality-gate-2", "quality"),
        ("manifest", "security_gate_decision_ref", "security-gate-2", "security"),
    ],
)
def test_rel_004_release_activation_rejects_chain_mismatch(
    contract_name: str,
    field: str,
    value: Any,
    message: str,
) -> None:
    chain = release_activation_chain()
    chain[contract_name][field] = value

    with pytest.raises(ValidationError, match=message):
        validate_chain(chain)


def test_rel_004_release_activation_binds_expected_ref_to_candidate_id() -> None:
    with pytest.raises(ValidationError, match="release_candidate_id"):
        validate_chain(release_activation_chain(), expected_candidate_ref="candidate-2")


@pytest.mark.parametrize(
    "manifest_field",
    [
        "agent_versions",
        "prompt_versions",
        "schema_versions",
        "model_route_versions",
        "capability_versions",
        "adapter_versions",
        "knowledge_index_versions",
        "memory_policy_versions",
        "policy_versions",
    ],
)
def test_rel_004_release_activation_binds_every_candidate_component_version(
    manifest_field: str,
) -> None:
    chain = release_activation_chain()
    chain["manifest"][manifest_field] = ["unreviewed-component@9.9.9"]

    with pytest.raises(ValidationError, match=manifest_field):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_duplicate_candidate_component_identity() -> None:
    chain = release_activation_chain()
    duplicate = chain["candidate"]["components"][0].copy()
    duplicate["digest"] = "sha256:different-content"
    chain["candidate"]["components"].append(duplicate)

    with pytest.raises(ValidationError, match="duplicate component identity"):
        validate_chain(chain)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("contract_version_ranges", {"EventEnvelope": ">=9.0.0,<10.0.0"}),
        ("compatibility_matrix_ref", "unreviewed-compatibility-matrix"),
        ("migration_refs", ["unreviewed-migration"]),
    ],
)
def test_rel_004_release_activation_binds_candidate_delivery_contract(
    field: str,
    invalid_value: object,
) -> None:
    chain = release_activation_chain()
    chain["manifest"][field] = invalid_value

    with pytest.raises(ValidationError, match=field):
        validate_chain(chain)


@pytest.mark.test_id("SEC-001")
def test_rel_004_release_activation_scope_tenant_must_match_canonical_tenant() -> None:
    chain = release_activation_chain()
    mismatched_scope = {"region": "cn", "tenant_id": "tenant-2"}
    for name in ("quality", "security", "operational", "release_decision"):
        chain[name]["scope"] = mismatched_scope.copy()

    with pytest.raises(ValidationError, match=r"scope\.tenant_id"):
        validate_chain(chain)


@pytest.mark.parametrize(
    ("separation_case", "message"),
    [
        ("builder_is_gate_authority", "builder must be separated"),
        ("release_is_gate_authority", "ReleaseDecision authority must be separated"),
        ("manifest_producer_is_builder", "ReleaseManifest producer must be separated"),
    ],
)
def test_rel_004_release_activation_enforces_authority_separation(
    separation_case: str,
    message: str,
) -> None:
    chain = release_activation_chain()
    if separation_case == "builder_is_gate_authority":
        chain["candidate"]["candidate_builder_ref"] = chain["quality"]["issued_by"]
    elif separation_case == "release_is_gate_authority":
        chain["release_decision"]["issued_by"] = chain["security"]["issued_by"]
    else:
        chain["manifest"]["meta"]["producer"] = chain["candidate"]["candidate_builder_ref"]

    with pytest.raises(ValidationError, match=message):
        validate_chain(chain)


def test_rel_004_release_activation_requires_distinct_gate_authorities() -> None:
    chain = release_activation_chain()
    chain["security"]["issued_by"] = chain["quality"]["issued_by"]

    with pytest.raises(ValidationError, match="Gate authorities must be pairwise distinct"):
        validate_chain(chain)


@pytest.mark.parametrize(
    ("contract_name", "issued_at", "expires_at", "message"),
    [
        (
            "quality",
            "2026-08-15T14:00:00Z",
            "2026-08-15T13:00:00Z",
            "issued_at must be earlier",
        ),
        (
            "release_decision",
            "2026-08-15T10:01:00Z",
            "2026-08-15T14:00:00Z",
            "before one or more gate",
        ),
    ],
)
def test_rel_004_release_activation_rejects_inverted_decision_time(
    contract_name: str,
    issued_at: str,
    expires_at: str,
    message: str,
) -> None:
    chain = release_activation_chain()
    chain[contract_name]["issued_at"] = issued_at
    chain[contract_name]["expires_at"] = expires_at

    with pytest.raises(ValidationError, match=message):
        validate_chain(chain)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "revoked", r"ReleaseDecision\.status must be active"),
        ("outcome", "rejected", r"ReleaseDecision\.outcome must be approved"),
    ],
)
def test_rel_004_release_activation_rejects_inactive_release_decision(
    field: str, value: str, message: str
) -> None:
    chain = release_activation_chain()
    chain["release_decision"][field] = value

    with pytest.raises(ValidationError, match=message):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_inactive_manifest() -> None:
    chain = release_activation_chain()
    chain["manifest"]["lifecycle_status"] = "approved"

    with pytest.raises(ValidationError, match=r"lifecycle_status must be active"):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_pre_signed_manifest() -> None:
    chain = release_activation_chain()
    chain["manifest"]["meta"]["created_at"] = "2026-08-15T10:59:59Z"

    with pytest.raises(ValidationError, match="created before ReleaseDecision"):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_expired_manifest() -> None:
    chain = release_activation_chain()
    chain["manifest"]["meta"]["expires_at"] = "2026-08-15T11:59:59Z"

    with pytest.raises(ValidationError, match="ReleaseManifest is expired"):
        validate_chain(chain)


def test_rel_004_release_activation_rejects_cross_tenant_contracts() -> None:
    chain = release_activation_chain()
    chain["manifest"]["meta"]["tenant_id"] = "tenant-2"

    with pytest.raises(ValidationError, match="must belong to one tenant"):
        validate_chain(chain)
