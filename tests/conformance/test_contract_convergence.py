from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from ueaf import ports
from ueaf.ports import RuntimeAdapter, TelemetryPort

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"

MANDATORY_SCHEMA_TITLES = {
    "ContractMeta",
    "CommandEnvelope",
    "EventEnvelope",
    "ProblemDetail",
    "PortResult",
    "PortError",
    "PrincipalContext",
    "RequestEnvelope",
    "TaskEnvelope",
    "TaskState",
    "BudgetEnvelope",
    "RunRecord",
    "RunAdmissionResult",
    "Checkpoint",
    "ContextManifest",
    "PromptContract",
    "ModelInvocation",
    "ModelRunResult",
    "StructuredDecision",
    "ToolIntent",
    "PolicyDecision",
    "ApprovalRequest",
    "ActionRecord",
    "ActionReceipt",
    "ToolResult",
    "HandoffEnvelope",
    "RunPhase",
    "WaitReason",
    "CompletionDisposition",
    "ActionPhase",
    "ActionDisposition",
    "ReleaseCandidate",
    "EvalCase",
    "EvalDataset",
    "EvalConfig",
    "EvalRun",
    "EvalResult",
    "QualityGateDecision",
    "SecurityGateDecision",
    "OperationalReadinessDecision",
    "ReleaseDecision",
    "ReleaseManifest",
    "EvolutionTrigger",
    "EvolutionRun",
    "GenomeManifest",
    "MutationProposal",
    "EvolutionAuthorityPolicy",
    "SubjectProfile",
    "EvolutionObjectiveProfile",
    "EvolutionStrategyProfile",
}

P0_PREREQUISITE_SCHEMA_TITLES = {
    "PromptCompileRequest",
    "ModelStreamEvent",
    "ValidationReport",
    "QueryIntent",
    "AuthorizationRequest",
}

CANONICAL_META_TITLES = {
    "RequestEnvelope",
    "TaskEnvelope",
    "TaskState",
    "BudgetEnvelope",
    "RunRecord",
    "RunAdmissionResult",
    "Checkpoint",
    "HandoffEnvelope",
    "AuditRecord",
    "ContextBuildRequest",
    "ContextManifest",
    "EvidencePack",
    "QueryIntent",
    "ModelInvocation",
    "ModelRunResult",
    "ModelStreamEvent",
    "PromptCompileRequest",
    "PromptContract",
    "StructuredDecision",
    "ValidationReport",
    "ApprovalRequest",
    "AuthorizationRequest",
    "PolicyDecision",
    "ActionReceipt",
    "ActionRecord",
    "CapabilityDescriptor",
    "ToolIntent",
    "ToolResult",
    "ReleaseCandidate",
    "EvalCase",
    "EvalDataset",
    "EvalConfig",
    "EvalRun",
    "EvalResult",
    "QualityGateDecision",
    "SecurityGateDecision",
    "OperationalReadinessDecision",
    "ReleaseDecision",
    "EvolutionTrigger",
    "EvolutionRun",
    "GenomeManifest",
    "MutationProposal",
    "EvolutionAuthorityPolicy",
    "PrincipalContext",
    "ReleaseManifest",
}

CORE_PORTS = (
    ports.RuntimeAdapter,
    ports.ContextBuildPort,
    ports.ModelStepPort,
    ports.ToolIntentPort,
    ports.HandoffPort,
    ports.TelemetryPort,
)


def public_methods(cls: type[object]) -> set[str]:
    return {
        name for name, value in cls.__dict__.items() if callable(value) and not name.startswith("_")
    }


def schema_titles() -> list[str]:
    titles: list[str] = []
    for path in SCHEMAS.rglob("*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        title = payload.get("title")
        if isinstance(title, str):
            titles.append(title)
    return titles


def test_con_002_single_event_envelope_schema() -> None:
    assert schema_titles().count("EventEnvelope") == 1


def test_con_001_existing_canonical_objects_require_contract_meta() -> None:
    schemas_by_title = {
        schema["title"]: schema
        for path in SCHEMAS.rglob("*.schema.json")
        if isinstance((schema := json.loads(path.read_text(encoding="utf-8"))).get("title"), str)
    }
    for title in CANONICAL_META_TITLES:
        assert "meta" in schemas_by_title[title]["required"]


def test_con_005_no_public_error_envelope_schema() -> None:
    assert "ErrorEnvelope" not in schema_titles()
    assert "ProblemDetail" in schema_titles()
    assert "PortError" in schema_titles()


def test_con_006_runtime_adapter_exact_minimum_spi() -> None:
    assert public_methods(RuntimeAdapter) == {
        "DescribeRuntime",
        "StartRun",
        "AdvanceRun",
        "SuspendRun",
        "ResumeRun",
        "CancelRun",
        "InspectRun",
    }


def test_con_007_telemetry_port_exact_public_methods() -> None:
    assert public_methods(TelemetryPort) == {"EmitTrace", "EmitMetric", "EmitLog", "EmitAudit"}


def test_con_008_single_principal_context_schema() -> None:
    assert schema_titles().count("PrincipalContext") == 1


def test_p0_sch_001_priority_wave_does_not_shrink_mandatory_schema_list() -> None:
    titles = set(schema_titles())
    assert MANDATORY_SCHEMA_TITLES <= titles
    assert {"AuditEvent", "AuditRecord"} & titles


def test_p0_sch_002_prerequisite_contract_schemas_exist() -> None:
    assert P0_PREREQUISITE_SCHEMA_TITLES <= set(schema_titles())


def test_con_005_port_result_and_port_error_contracts_exist() -> None:
    assert {"PortResult", "PortError"} <= set(schema_titles())


def test_p0_port_001_core_spi_uses_typed_request_and_result_contracts() -> None:
    for port in CORE_PORTS:
        for name, method in port.__dict__.items():
            if not callable(method) or (name.startswith("_") and name != "__call__"):
                continue
            signature = inspect.signature(method, eval_str=True)
            assert signature.return_annotation is not Any
            assert all(
                parameter.annotation is not Any
                for parameter_name, parameter in signature.parameters.items()
                if parameter_name != "self"
            )


def test_con_012_evolution_canonical_object_count_is_five() -> None:
    evolution_titles = {
        json.loads(path.read_text(encoding="utf-8"))["title"]
        for path in (SCHEMAS / "evolution").glob("*.schema.json")
    }
    assert evolution_titles == {
        "EvolutionTrigger",
        "EvolutionRun",
        "GenomeManifest",
        "MutationProposal",
        "EvolutionAuthorityPolicy",
    }


def test_con_011_mutation_proposal_requires_build_inputs() -> None:
    mutation_path = SCHEMAS / "evolution/mutation-proposal.schema.json"
    mutation = json.loads(mutation_path.read_text(encoding="utf-8"))
    required = set(mutation["required"])
    assert {"baseline_genome_ref", "changes", "trigger_ref", "subject_ref"} <= required


def test_con_011_evolution_build_chain_requires_genome_candidate() -> None:
    schemas_by_title = {
        schema["title"]: schema
        for path in SCHEMAS.rglob("*.schema.json")
        if isinstance((schema := json.loads(path.read_text(encoding="utf-8"))).get("title"), str)
    }
    assert {"MutationProposal", "GenomeManifest", "ReleaseCandidate"} <= set(schemas_by_title)
    assert "baseline_genome_ref" in schemas_by_title["MutationProposal"]["required"]
    assert "created_from_mutation_ref" in schemas_by_title["GenomeManifest"]["required"]
    assert {"genome_manifest_ref", "mutation_proposal_refs"} <= set(
        schemas_by_title["ReleaseCandidate"]["required"]
    )
