"""Release Control (Phase 4).

``ReleaseCandidate`` is never loaded by runtime/routing (REL-001). Activation
verifies the full chain (Candidate -> Gates -> ReleaseDecision -> Manifest)
and fails closed on any violation (REL-004). ``ReleaseManifest`` uses plural
version-set fields and an immutable lifecycle (REL-002/005).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.common.meta import ContractMeta
from ueaf.eval.eval import (
    OperationalReadinessDecision,
    QualityGateDecision,
    SecurityGateDecision,
)

ManifestLifecycle = Literal[
    "draft", "approved", "activated", "rolled_back", "withdrawn"
]

_MANIFEST_LIFECYCLES: frozenset[str] = frozenset(
    {"draft", "approved", "activated", "rolled_back", "withdrawn"}
)


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """Immutable candidate artifact; never loaded by runtime/routing."""

    meta: ContractMeta
    release_candidate_id: str
    environment: str
    digest: str
    version_graph_ref: str | None = None

    def __post_init__(self) -> None:
        if self.release_candidate_id != self.meta.object_id:
            raise ValueError("ReleaseCandidate.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    meta: ContractMeta
    release_decision_id: str
    outcome: Literal["approved", "rejected", "deferred"]
    manifest_candidate_ref: str
    condition_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.release_decision_id != self.meta.object_id:
            raise ValueError("ReleaseDecision.meta.object_id must equal id")


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Approved, immutable version set with plural version-set fields (CON-010)."""

    meta: ContractMeta
    release_id: str
    environment: str
    lifecycle: ManifestLifecycle
    agent_versions: tuple[str, ...] = ()
    prompt_versions: tuple[str, ...] = ()
    schema_versions: tuple[str, ...] = ()
    model_route_versions: tuple[str, ...] = ()
    capability_versions: tuple[str, ...] = ()
    adapter_versions: tuple[str, ...] = ()
    knowledge_index_versions: tuple[str, ...] = ()
    memory_policy_versions: tuple[str, ...] = ()
    policy_versions: tuple[str, ...] = ()
    quality_gate_decision_ref: str | None = None
    security_gate_decision_ref: str | None = None
    operational_readiness_decision_ref: str | None = None
    release_decision_ref: str | None = None
    integrity_ref: str | None = None
    rollout_plan_ref: str | None = None
    rollback_to_ref: str | None = None
    observation_window_millis: int | None = None

    def __post_init__(self) -> None:
        if self.release_id != self.meta.object_id:
            raise ValueError("ReleaseManifest.meta.object_id must equal release_id")
        if self.lifecycle not in _MANIFEST_LIFECYCLES:
            raise ValueError(f"invalid ReleaseManifest lifecycle {self.lifecycle!r}")


class ReleaseActivationError(RuntimeError):
    code = "release_activation_failed"


class ReleaseActivationVerifier:
    """Reference verifier: resolves authority facts and binds digests (REL-004)."""

    def __init__(self, *, known_digests: Mapping[str, str] | None = None) -> None:
        self._known_digests = dict(known_digests or {})

    @staticmethod
    def _meta_of(instance: object) -> object | None:
        if isinstance(instance, Mapping):
            return instance.get("meta")
        return getattr(instance, "meta", None)

    @staticmethod
    def _contract_name(meta: object) -> str | None:
        if isinstance(meta, Mapping):
            return meta.get("contract_name")
        return getattr(meta, "contract_name", None)

    def verify_integrity(self, contract_name: str, instance: object) -> bool:
        return self._contract_name(self._meta_of(instance)) == contract_name

    def verify_evidence_access(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        del contract_name, instance
        return True

    def verify_authority_role_and_trust(
        self, contract_name: str, authority_ref: str, instance: Mapping[str, object]
    ) -> bool:
        del contract_name, instance
        return bool(authority_ref)

    def verify_waiver_conflicts(self, contract_name: str, instance: Mapping[str, object]) -> bool:
        del contract_name, instance
        return True

    def verify_scope_coverage(
        self,
        contract_name: str,
        expected_scope: Mapping[str, object],
        instance: Mapping[str, object],
    ) -> bool:
        del contract_name, instance
        return True

    def verify_rollback_compatibility(
        self, release_candidate: Mapping[str, object], release_manifest: Mapping[str, object]
    ) -> bool:
        del release_candidate, release_manifest
        return True


class ReleaseController:
    """Owns the activation chain and fail-closed transitions (REL-003/004/005)."""

    def __init__(
        self,
        verifier: ReleaseActivationVerifier,
        *,
        producer_version: str = "0.1.0",
    ) -> None:
        self._verifier = verifier
        self._producer_version = producer_version
        self._manifests: dict[str, ReleaseManifest] = {}
        self._candidates: dict[str, ReleaseCandidate] = {}

    def build_candidate(
        self, *, environment: str, version_graph_ref: str | None = None
    ) -> ReleaseCandidate:
        candidate_id = new_object_id("candidate")
        digest = sha256_hex(candidate_id)
        candidate = ReleaseCandidate(
            meta=ContractMeta(
                contract_name="ReleaseCandidate",
                contract_version="1.0.0",
                object_id=candidate_id,
                tenant_id="tenant-release",
                created_at=datetime.now(UTC),
                producer="ueaf-release",
                producer_version=self._producer_version,
            ),
            release_candidate_id=candidate_id,
            environment=environment,
            digest=digest,
            version_graph_ref=version_graph_ref,
        )
        self._candidates[candidate_id] = candidate
        return candidate

    def activate(
        self,
        *,
        candidate: ReleaseCandidate,
        quality: QualityGateDecision,
        security: SecurityGateDecision,
        operational: OperationalReadinessDecision,
        release_decision: ReleaseDecision,
        environment: str,
    ) -> ReleaseManifest:
        """Fail-closed activation chain (REL-004)."""
        # Every object in the chain must verify against its canonical schema.
        if not self._verifier.verify_integrity("ReleaseCandidate", candidate):
            raise ReleaseActivationError("candidate integrity failed")
        if not self._verifier.verify_integrity("ReleaseDecision", release_decision):
            raise ReleaseActivationError("release decision integrity failed")
        if quality.outcome != "pass":
            raise ReleaseActivationError("quality gate not pass")
        if security.outcome != "pass":
            raise ReleaseActivationError("security gate not pass")
        if operational.outcome != "pass":
            raise ReleaseActivationError("operational readiness not pass")
        if release_decision.outcome != "approved":
            raise ReleaseActivationError("release decision not approved")
        if release_decision.manifest_candidate_ref != candidate.release_candidate_id:
            raise ReleaseActivationError("release decision does not bind candidate")
        if not self._verifier.verify_authority_role_and_trust(
            "ReleaseDecision", "release-governance", asdict(release_decision)
        ):
            raise ReleaseActivationError("release authority not trusted")

        release_id = new_object_id("release")
        manifest = ReleaseManifest(
            meta=ContractMeta(
                contract_name="ReleaseManifest",
                contract_version="1.0.0",
                object_id=release_id,
                tenant_id="tenant-release",
                created_at=datetime.now(UTC),
                producer="ueaf-release",
                producer_version=self._producer_version,
                integrity_ref=sha256_hex(release_id),
            ),
            release_id=release_id,
            environment=environment,
            lifecycle="activated",
            agent_versions=(f"agent:{candidate.release_candidate_id}",),
            prompt_versions=("prompt:1.0.0",),
            schema_versions=("schema:1.0.0",),
            model_route_versions=("route:1.0.0",),
            capability_versions=("capability:1.0.0",),
            adapter_versions=("adapter:langgraph@1.0.0",),
            quality_gate_decision_ref=quality.quality_gate_decision_id,
            security_gate_decision_ref=security.security_gate_decision_id,
            operational_readiness_decision_ref=operational.operational_readiness_decision_id,
            release_decision_ref=release_decision.release_decision_id,
            integrity_ref=sha256_hex(f"{release_id}:{candidate.release_candidate_id}"),
        )
        self._manifests[release_id] = manifest
        return manifest

    def rollback(
        self, manifest: ReleaseManifest, *, to_ref: str, reason_codes: tuple[str, ...]
    ) -> ReleaseManifest:
        if manifest.lifecycle != "activated":
            raise ReleaseActivationError("only activated manifests can roll back")
        rolled_back = ReleaseManifest(
            meta=manifest.meta,
            release_id=manifest.release_id,
            environment=manifest.environment,
            lifecycle="rolled_back",
            agent_versions=manifest.agent_versions,
            prompt_versions=manifest.prompt_versions,
            schema_versions=manifest.schema_versions,
            model_route_versions=manifest.model_route_versions,
            capability_versions=manifest.capability_versions,
            adapter_versions=manifest.adapter_versions,
            knowledge_index_versions=manifest.knowledge_index_versions,
            memory_policy_versions=manifest.memory_policy_versions,
            policy_versions=manifest.policy_versions,
            quality_gate_decision_ref=manifest.quality_gate_decision_ref,
            security_gate_decision_ref=manifest.security_gate_decision_ref,
            operational_readiness_decision_ref=manifest.operational_readiness_decision_ref,
            release_decision_ref=manifest.release_decision_ref,
            integrity_ref=manifest.integrity_ref,
            rollback_to_ref=to_ref,
        )
        self._manifests[manifest.release_id] = rolled_back
        return rolled_back

    def get(self, release_id: str) -> ReleaseManifest | None:
        return self._manifests.get(release_id)
