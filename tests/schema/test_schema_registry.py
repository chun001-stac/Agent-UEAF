from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from ueaf.common.schema_registry import (
    build_schema_registry,
    update_schema_lock,
    validate_instance,
    validate_schema_catalog,
    validate_schema_lock_history,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def write_schema(path: Path, **overrides: Any) -> None:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://ueaf.dev/test/{path.stem}",
        "x-ueaf-schema-version": "1.0.0",
        "title": path.stem,
        "type": "object",
        "additionalProperties": False,
    }
    schema.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema), encoding="utf-8")


def copy_schema_catalog(tmp_path: Path) -> Path:
    destination = tmp_path / "schemas"
    shutil.copytree(SCHEMAS, destination)
    return destination


def create_minimal_locked_catalog(tmp_path: Path) -> tuple[Path, Path]:
    schema_root = tmp_path / "schemas"
    registered_schema = schema_root / "registered.schema.json"
    write_schema(
        registered_schema,
        **{"$id": "https://ueaf.dev/test/registered.schema.json"},
    )
    lock = {
        "lock_version": "1.0.0",
        "schemas": [
            {
                "$id": "https://ueaf.dev/test/registered.schema.json",
                "x-ueaf-schema-version": "1.0.0",
                "sha256": hashlib.sha256(registered_schema.read_bytes()).hexdigest(),
            }
        ],
    }
    (schema_root / "schema-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return schema_root, registered_schema


def test_p0_sch_003_repository_catalog_is_machine_valid() -> None:
    assert validate_schema_catalog(SCHEMAS) >= 17


def test_p0_sch_003_rejects_duplicate_schema_id(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    duplicate_id = "https://ueaf.dev/test/duplicate"
    write_schema(schema_root / "first.schema.json", **{"$id": duplicate_id})
    write_schema(schema_root / "second.schema.json", **{"$id": duplicate_id})

    with pytest.raises(ValueError, match=r"duplicate schema \$id"):
        build_schema_registry(schema_root)


def test_p0_sch_003_requires_file_level_version(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    schema_path = schema_root / "missing-version.schema.json"
    write_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    del schema["x-ueaf-schema-version"]
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(ValueError, match="x-ueaf-schema-version"):
        build_schema_registry(schema_root)


def test_p0_sch_003_requires_explicit_draft_2020_12_dialect(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    schema_path = schema_root / "missing-dialect.schema.json"
    write_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    del schema["$schema"]
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(ValueError, match=r"must declare \$schema"):
        build_schema_registry(schema_root)


def test_p0_sch_003_rejects_draft_07_dialect(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    write_schema(
        schema_root / "draft-07.schema.json",
        **{"$schema": "http://json-schema.org/draft-07/schema#"},
    )

    with pytest.raises(ValueError, match=r"must declare \$schema"):
        build_schema_registry(schema_root)


def test_p0_sch_003_requires_schema_id(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    schema_path = schema_root / "missing-id.schema.json"
    write_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    del schema["$id"]
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing stable \$id"):
        build_schema_registry(schema_root)


def test_p0_sch_003_rejects_relative_schema_id(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    write_schema(schema_root / "relative.schema.json", **{"$id": "relative.schema.json"})

    with pytest.raises(ValueError, match="absolute URI"):
        build_schema_registry(schema_root)


def test_p0_sch_003_rejects_fragment_in_schema_id(tmp_path: Path) -> None:
    schema_root = tmp_path / "schemas"
    write_schema(
        schema_root / "fragment.schema.json",
        **{"$id": "https://ueaf.dev/test/fragment#identity"},
    )

    with pytest.raises(ValueError, match="must not contain a fragment"):
        build_schema_registry(schema_root)


def test_p0_sch_003_rejects_unresolved_local_ref(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    payload_path = schema_root / "events/payloads/run-created.schema.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["properties"]["run_id"] = {"$ref": "https://ueaf.dev/schemas/missing.schema.json"}
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"unresolved schema \$ref"):
        validate_schema_catalog(schema_root)


def test_p0_sch_003_rejects_unresolved_json_pointer(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    payload_path = schema_root / "events/payloads/run-phase-changed.schema.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["properties"]["from_phase"] = {"$ref": "#/$defs/missing"}
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"unresolved schema \$ref"):
        validate_schema_catalog(schema_root)


def test_con_004_event_catalog_rejects_duplicate_registration(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    catalog_path = schema_root / "events/event-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["events"].append(dict(catalog["events"][0]))
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate event catalog entry"):
        validate_schema_catalog(schema_root)


def test_con_004_event_catalog_self_validates_against_catalog_schema(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    catalog_path = schema_root / "events/event-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["unexpected"] = True
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValidationError, match="Additional properties"):
        validate_schema_catalog(schema_root)


def test_con_004_event_catalog_rejects_unresolvable_payload_schema(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    catalog_path = schema_root / "events/event-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["events"][0]["payload_schema_ref"] = "schema://missing/1.0.0"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="payload schema is not in the local registry"):
        validate_schema_catalog(schema_root)


def test_p0_sch_003_lock_rejects_raw_schema_tampering(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    schema_path = schema_root / "common/contract-meta.schema.json"
    schema_path.write_bytes(schema_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="schema digest mismatch"):
        validate_schema_catalog(schema_root)


def test_p0_sch_003_lock_rejects_new_unlocked_schema(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    write_schema(
        schema_root / "test/new-contract.schema.json",
        **{"$id": "https://ueaf.dev/test/new-contract.schema.json"},
    )

    with pytest.raises(ValueError, match="schema tuple is not locked"):
        validate_schema_catalog(schema_root)


def test_p0_sch_003_lock_rejects_duplicate_historical_tuple(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    lock_path = schema_root / "schema-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schemas"].append(dict(lock["schemas"][0]))
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate schema lock tuple"):
        validate_schema_catalog(schema_root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("$id", "relative.schema.json", "invalid schema lock \\$id"),
        ("x-ueaf-schema-version", "v1", "invalid schema lock version"),
        ("sha256", "not-a-digest", "invalid schema lock SHA256"),
    ],
)
def test_p0_sch_003_lock_rejects_malformed_historical_identity(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    lock_path = schema_root / "schema-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schemas"][0][field] = value
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_schema_catalog(schema_root)


def test_p0_sch_003_lock_update_refuses_same_tuple_rewrite(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    schema_path = schema_root / "common/contract-meta.schema.json"
    schema_path.write_bytes(schema_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="refusing to rewrite locked schema tuple"):
        update_schema_lock(schema_root)


def test_p0_sch_003_lock_update_appends_new_tuple_and_preserves_history(
    tmp_path: Path,
) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    initial_document_count = len(list(schema_root.rglob("*.schema.json")))
    lock_path = schema_root / "schema-lock.json"
    baseline_lock_path = tmp_path / "baseline-schema-lock.json"
    shutil.copy2(lock_path, baseline_lock_path)
    lock_before = json.loads(lock_path.read_text(encoding="utf-8"))
    baseline_tuple_count = len(lock_before["schemas"])
    historical_entry = {
        "$id": "https://ueaf.dev/schemas/history/retired.schema.json",
        "x-ueaf-schema-version": "0.9.0",
        "sha256": "0" * 64,
    }
    lock_before["schemas"].append(historical_entry)
    lock_path.write_text(json.dumps(lock_before), encoding="utf-8")
    write_schema(
        schema_root / "test/new-contract.schema.json",
        **{"$id": "https://ueaf.dev/test/new-contract.schema.json"},
    )

    document_count, appended_count = update_schema_lock(schema_root)

    lock_after = json.loads(lock_path.read_text(encoding="utf-8"))
    assert document_count == initial_document_count + 1
    assert appended_count == 1
    assert lock_after["schemas"][:-1] == lock_before["schemas"]
    assert historical_entry in lock_after["schemas"]
    assert lock_after["schemas"][-1]["$id"] == "https://ueaf.dev/test/new-contract.schema.json"
    assert validate_schema_catalog(schema_root) == initial_document_count + 1
    assert validate_schema_lock_history(lock_path, baseline_lock_path) == baseline_tuple_count


def test_p0_sch_003_lock_history_rejects_deleted_tuple(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    current_lock_path = schema_root / "schema-lock.json"
    baseline_lock_path = tmp_path / "baseline-schema-lock.json"
    shutil.copy2(current_lock_path, baseline_lock_path)
    current_lock = json.loads(current_lock_path.read_text(encoding="utf-8"))
    del current_lock["schemas"][0]
    current_lock_path.write_text(json.dumps(current_lock), encoding="utf-8")

    with pytest.raises(ValueError, match="historical schema lock tuple was removed"):
        validate_schema_lock_history(current_lock_path, baseline_lock_path)


def test_p0_sch_003_lock_history_rejects_changed_historical_digest(tmp_path: Path) -> None:
    schema_root = copy_schema_catalog(tmp_path)
    current_lock_path = schema_root / "schema-lock.json"
    baseline_lock_path = tmp_path / "baseline-schema-lock.json"
    shutil.copy2(current_lock_path, baseline_lock_path)
    current_lock = json.loads(current_lock_path.read_text(encoding="utf-8"))
    current_lock["schemas"][0]["sha256"] = "f" * 64
    current_lock_path.write_text(json.dumps(current_lock), encoding="utf-8")

    with pytest.raises(ValueError, match="historical schema lock digest was changed"):
        validate_schema_lock_history(current_lock_path, baseline_lock_path)


def test_p0_sch_003_validate_instance_rejects_path_outside_catalog_root(
    tmp_path: Path,
) -> None:
    schema_root, registered_schema = create_minimal_locked_catalog(tmp_path)
    outside_schema = tmp_path / "outside.schema.json"
    shutil.copy2(registered_schema, outside_schema)

    with pytest.raises(ValueError, match="schema path is outside schema root"):
        validate_instance({}, outside_schema, schema_root)


def test_p0_sch_003_validate_instance_rejects_same_id_shadow_path(tmp_path: Path) -> None:
    schema_root, registered_schema = create_minimal_locked_catalog(tmp_path)
    shadow_schema = schema_root / "shadow.json"
    shutil.copy2(registered_schema, shadow_schema)

    with pytest.raises(ValueError, match="schema path does not match registered path"):
        validate_instance({}, shadow_schema, schema_root)
