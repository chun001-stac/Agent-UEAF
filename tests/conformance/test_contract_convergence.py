from __future__ import annotations

import json
from pathlib import Path

from ueaf.ports import RuntimeAdapter, TelemetryPort

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def public_methods(cls: type[object]) -> set[str]:
    return {name for name, value in cls.__dict__.items() if callable(value) and not name.startswith("_")}


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


def test_evolution_canonical_object_count_is_five() -> None:
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


def test_con_011_mutation_schema_requires_genome_compatible_inputs() -> None:
    mutation = json.loads((SCHEMAS / "evolution/mutation-proposal.schema.json").read_text(encoding="utf-8"))
    required = set(mutation["required"])
    assert {"baseline_genome_ref", "changes", "trigger_ref", "subject_ref"} <= required
