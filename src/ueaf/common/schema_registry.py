from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from jsonschema import FormatChecker, validators
from jsonschema.exceptions import FormatError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from ueaf.ports import ReleaseActivationVerifier

type Schema = dict[str, Any]
type CanonicalInvariant = Callable[[Mapping[str, Any]], None]
type SchemaLockEntry = dict[str, str]

SCHEMA_VERSION_KEY = "x-ueaf-schema-version"
EVENT_CATALOG_RELATIVE_PATH = Path("events/event-catalog.json")
SCHEMA_LOCK_RELATIVE_PATH = Path("schema-lock.json")
DRAFT_2020_12_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_LOCK_VERSION = "1.0.0"
FORMAT_CHECKER = FormatChecker()
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXACT_RFC3339_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<offset>[Zz]|[+-]\d{2}:\d{2})$"
)

_COMPONENT_VERSION_FIELDS = {
    "agent": "agent_versions",
    "prompt": "prompt_versions",
    "schema": "schema_versions",
    "model_route": "model_route_versions",
    "capability": "capability_versions",
    "adapter": "adapter_versions",
    "knowledge_index": "knowledge_index_versions",
    "memory_policy": "memory_policy_versions",
    "policy": "policy_versions",
}

_CANONICAL_ID_FIELDS: dict[str, str] = {
    "RequestEnvelope": "request_id",
    "TaskEnvelope": "task_id",
    "TaskState": "task_id",
    "BudgetEnvelope": "budget_id",
    "RunRecord": "run_id",
    "RunAdmissionResult": "run_admission_result_id",
    "Checkpoint": "checkpoint_id",
    "HandoffEnvelope": "handoff_id",
    "AuditRecord": "audit_record_id",
    "ContextBuildRequest": "context_request_id",
    "ContextManifest": "context_manifest_id",
    "EvidencePack": "evidence_pack_id",
    "QueryIntent": "query_intent_id",
    "ModelInvocation": "model_invocation_id",
    "PromptContract": "prompt_contract_id",
    "StructuredDecision": "structured_decision_id",
    "ApprovalRequest": "approval_request_id",
    "AuthorizationRequest": "authorization_request_id",
    "PolicyDecision": "policy_decision_id",
    "ActionReceipt": "action_receipt_id",
    "ActionRecord": "action_id",
    "CapabilityDescriptor": "capability_id",
    "ToolIntent": "tool_intent_id",
    "ToolResult": "tool_result_id",
    "ReleaseCandidate": "release_candidate_id",
    "EvalCase": "eval_case_id",
    "EvalDataset": "eval_dataset_id",
    "EvalConfig": "eval_config_id",
    "EvalRun": "eval_run_id",
    "EvalResult": "eval_result_id",
    "QualityGateDecision": "quality_gate_decision_id",
    "SecurityGateDecision": "security_gate_decision_id",
    "OperationalReadinessDecision": "operational_readiness_decision_id",
    "ReleaseDecision": "release_decision_id",
    "EvolutionTrigger": "evolution_trigger_id",
    "EvolutionRun": "evolution_run_id",
    "GenomeManifest": "genome_id",
    "MutationProposal": "mutation_proposal_id",
    "EvolutionAuthorityPolicy": "evolution_authority_policy_id",
    "PrincipalContext": "principal_id",
    "ReleaseManifest": "release_id",
}
_CANONICAL_INVARIANTS: dict[str, list[CanonicalInvariant]] = defaultdict(list)


def load_json_object(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], raw)


def load_schema(path: Path) -> Schema:
    return load_json_object(path)


def register_canonical_id_field(contract_name: str, id_field: str) -> None:
    """Register the explicit object-id field for a canonical contract."""
    current = _CANONICAL_ID_FIELDS.get(contract_name)
    if current is not None and current != id_field:
        raise ValueError(f"canonical id field already registered for {contract_name}: {current}")
    _CANONICAL_ID_FIELDS[contract_name] = id_field


def register_canonical_invariant(contract_name: str, invariant: CanonicalInvariant) -> None:
    """Register an application-level invariant not expressible in JSON Schema."""
    _CANONICAL_INVARIANTS[contract_name].append(invariant)


def _require_schema_metadata(path: Path, schema: Schema) -> tuple[str, str]:
    dialect = schema.get("$schema")
    if dialect != DRAFT_2020_12_SCHEMA_URI:
        raise ValueError(f"schema must declare $schema={DRAFT_2020_12_SCHEMA_URI!r}: {path}")

    uri = schema.get("$id")
    if not isinstance(uri, str) or not uri:
        raise ValueError(f"schema missing stable $id: {path}")
    try:
        FORMAT_CHECKER.check(uri, "uri")
    except FormatError as error:
        raise ValueError(f"schema $id must be an absolute URI: {path}") from error
    if not urlsplit(uri).scheme:
        raise ValueError(f"schema $id must be an absolute URI: {path}")
    if "#" in uri:
        raise ValueError(f"schema $id must not contain a fragment: {path}")

    schema_version = schema.get(SCHEMA_VERSION_KEY)
    if not isinstance(schema_version, str) or not SEMVER_PATTERN.fullmatch(schema_version):
        raise ValueError(f"schema missing valid {SCHEMA_VERSION_KEY}: {path}")
    return uri, schema_version


def _load_schema_documents(schema_root: Path) -> dict[str, tuple[Path, Schema]]:
    documents: dict[str, tuple[Path, Schema]] = {}
    for path in sorted(schema_root.rglob("*.schema.json")):
        schema = load_schema(path)
        uri, _ = _require_schema_metadata(path, schema)
        previous = documents.get(uri)
        if previous is not None:
            raise ValueError(f"duplicate schema $id {uri}: {previous[0]} and {path}")
        validators.validator_for(schema).check_schema(schema)
        documents[uri] = (path, schema)
    return documents


def _schema_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_schema_lock_file(
    lock_path: Path, *, required: bool
) -> tuple[list[SchemaLockEntry], dict[tuple[str, str], SchemaLockEntry]]:
    if not lock_path.is_file():
        if required:
            raise ValueError(f"schema lock not found: {lock_path}")
        return [], {}

    raw = load_json_object(lock_path)
    if set(raw) != {"lock_version", "schemas"}:
        raise ValueError(f"schema lock has invalid top-level fields: {lock_path}")
    if raw.get("lock_version") != SCHEMA_LOCK_VERSION:
        raise ValueError(f"unsupported schema lock version: {lock_path}")

    raw_entries = raw.get("schemas")
    if not isinstance(raw_entries, list):
        raise ValueError(f"schema lock schemas must be an array: {lock_path}")

    entries: list[SchemaLockEntry] = []
    index: dict[tuple[str, str], SchemaLockEntry] = {}
    for position, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "$id",
            SCHEMA_VERSION_KEY,
            "sha256",
        }:
            raise ValueError(f"invalid schema lock entry at index {position}: {lock_path}")
        schema_id = raw_entry.get("$id")
        schema_version = raw_entry.get(SCHEMA_VERSION_KEY)
        digest = raw_entry.get("sha256")
        if not all(isinstance(value, str) for value in (schema_id, schema_version, digest)):
            raise ValueError(f"non-string schema lock entry at index {position}: {lock_path}")
        locked_id = cast(str, schema_id)
        locked_version = cast(str, schema_version)
        try:
            FORMAT_CHECKER.check(locked_id, "uri")
        except FormatError as error:
            raise ValueError(f"invalid schema lock $id at index {position}: {lock_path}") from error
        if not urlsplit(locked_id).scheme or "#" in locked_id:
            raise ValueError(f"invalid schema lock $id at index {position}: {lock_path}")
        if not SEMVER_PATTERN.fullmatch(locked_version):
            raise ValueError(f"invalid schema lock version at index {position}: {lock_path}")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise ValueError(f"invalid schema lock SHA256 at index {position}: {lock_path}")

        entry = cast(SchemaLockEntry, dict(raw_entry))
        key = cast(tuple[str, str], (schema_id, schema_version))
        if key in index:
            raise ValueError(f"duplicate schema lock tuple: {key[0]}@{key[1]}")
        entries.append(entry)
        index[key] = entry
    return entries, index


def _load_schema_lock(
    schema_root: Path, *, required: bool
) -> tuple[list[SchemaLockEntry], dict[tuple[str, str], SchemaLockEntry]]:
    return _load_schema_lock_file(
        schema_root / SCHEMA_LOCK_RELATIVE_PATH,
        required=required,
    )


def _validate_schema_lock(schema_root: Path, documents: Mapping[str, tuple[Path, Schema]]) -> None:
    _, lock_index = _load_schema_lock(schema_root, required=True)
    for schema_id, (path, schema) in documents.items():
        _, schema_version = _require_schema_metadata(path, schema)
        entry = lock_index.get((schema_id, schema_version))
        if entry is None:
            raise ValueError(f"schema tuple is not locked: {schema_id}@{schema_version}")
        digest = _schema_sha256(path)
        if entry["sha256"] != digest:
            raise ValueError(
                f"schema digest mismatch for locked tuple {schema_id}@{schema_version}"
            )


def validate_schema_lock_history(current_lock: Path, baseline_lock: Path) -> int:
    """Require every baseline identity/version tuple and digest to remain unchanged."""
    _, current_index = _load_schema_lock_file(current_lock, required=True)
    baseline_entries, _ = _load_schema_lock_file(baseline_lock, required=True)
    for baseline_entry in baseline_entries:
        key = (
            baseline_entry["$id"],
            baseline_entry[SCHEMA_VERSION_KEY],
        )
        current_entry = current_index.get(key)
        if current_entry is None:
            raise ValueError(f"historical schema lock tuple was removed: {key[0]}@{key[1]}")
        if current_entry["sha256"] != baseline_entry["sha256"]:
            raise ValueError(f"historical schema lock digest was changed: {key[0]}@{key[1]}")
    return len(baseline_entries)


def _registry_from_documents(
    documents: Mapping[str, tuple[Path, Schema]],
) -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for uri, (_, schema) in documents.items():
        registry = registry.with_resource(uri, Resource.from_contents(schema))
    return registry


def build_schema_registry(schema_root: Path) -> Registry[Any]:
    documents = _load_schema_documents(schema_root)
    registry = _registry_from_documents(documents)
    _validate_local_refs(documents, registry)
    _validate_schema_lock(schema_root, documents)
    return registry


def _iter_schema_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            yield ref
        for child in value.values():
            yield from _iter_schema_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_schema_refs(child)


def _validate_local_refs(
    documents: Mapping[str, tuple[Path, Schema]], registry: Registry[Any]
) -> None:
    for schema_id, (path, schema) in documents.items():
        for ref in _iter_schema_refs(schema):
            try:
                registry.resolver(base_uri=schema_id).lookup(ref)
            except Unresolvable as error:
                raise ValueError(f"unresolved schema $ref {ref!r} in {path}") from error


def _validate_with_schema(instance: Any, schema: Schema, registry: Registry[Any]) -> None:
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(
        schema,
        registry=registry,
        format_checker=FORMAT_CHECKER,
    )
    validator.validate(instance)


def _parse_exact_rfc3339_instant(
    instance: Mapping[str, Any],
    field: str,
    label: str,
) -> tuple[int, Decimal]:
    """Return an exact UTC-second/fraction key without microsecond truncation."""
    value = instance.get(field)
    if not isinstance(value, str):
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp")
    match = EXACT_RFC3339_PATTERN.fullmatch(value)
    if match is None:
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp")

    second = int(match.group("second"))
    if second > 60:
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp")
    normalized_second = min(second, 59)
    try:
        local_second = datetime.fromisoformat(
            f"{match.group('date')}T{match.group('hour')}:"
            f"{match.group('minute')}:{normalized_second:02d}"
        )
    except ValueError as error:
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp") from error

    offset_text = match.group("offset")
    if offset_text == "-00:00":
        raise ValidationError(f"{label}.{field} must use a known RFC 3339 timezone offset")
    offset_seconds = 0
    if offset_text not in {"Z", "z"}:
        offset_hour = int(offset_text[1:3])
        offset_minute = int(offset_text[4:6])
        if offset_hour > 23 or offset_minute > 59:
            raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp")
        offset_seconds = offset_hour * 3_600 + offset_minute * 60
        if offset_text[0] == "-":
            offset_seconds = -offset_seconds

    local_whole_seconds = (
        (local_second.toordinal() - 1) * 86_400
        + local_second.hour * 3_600
        + local_second.minute * 60
        + local_second.second
    )
    whole_seconds = local_whole_seconds - offset_seconds + int(second == 60)
    fraction_digits = match.group("fraction")
    fraction = Decimal(0) if fraction_digits is None else Decimal(f"0.{fraction_digits}")
    return whole_seconds, fraction


def _action_record_receipt_invariant(instance: Mapping[str, Any]) -> None:
    """Validate only ActionRecord-local receipt shape, not referenced fact existence.

    Passing this invariant is not proof that PolicyDecision, reservation, or receipt
    references exist, remain active, or authorize a consumable side effect. Those
    cross-object checks belong to the Phase 3 execution gate.
    """
    receipt_refs = instance.get("receipt_refs")
    if not isinstance(receipt_refs, list):
        raise ValidationError("ActionRecord.receipt_refs must be an array")

    latest_receipt_ref = instance.get("latest_receipt_ref")
    if not receipt_refs and latest_receipt_ref is not None:
        raise ValidationError(
            "ActionRecord.latest_receipt_ref must be null when receipt_refs is empty"
        )
    if receipt_refs and latest_receipt_ref != receipt_refs[-1]:
        raise ValidationError(
            "ActionRecord.latest_receipt_ref must equal the last receipt_refs entry"
        )

    disposition = instance.get("disposition")
    if disposition in {"executed", "failed", "unresolved"} and not receipt_refs:
        raise ValidationError("ActionRecord execution terminal dispositions require receipt_refs")

    if instance.get("phase") == "terminal":
        if disposition == "invalid":
            forbidden_refs = (
                "policy_decision_ref",
                "approval_request_ref",
                "idempotency_reservation_ref",
            )
            if any(instance.get(field) is not None for field in forbidden_refs):
                raise ValidationError(
                    "ActionRecord invalid cannot retain policy, approval, or reservation refs"
                )
        elif (
            disposition in {"denied", "approval_rejected"}
            and instance.get("idempotency_reservation_ref") is not None
        ):
            raise ValidationError(
                "ActionRecord denied/approval_rejected cannot retain a reservation"
            )
        if disposition in {
            "denied",
            "approval_rejected",
            "invalid",
            "cancelled",
        } and (latest_receipt_ref is not None or receipt_refs):
            raise ValidationError(
                "ActionRecord non-executed terminal disposition cannot retain execution receipts"
            )
        if disposition in {
            "denied",
            "approval_rejected",
            "invalid",
            "cancelled",
        } and (
            instance.get("lease_fencing_token") is not None
            or instance.get("reconciliation_state") is not None
        ):
            raise ValidationError(
                "ActionRecord non-executed terminal disposition cannot retain "
                "execution lease or reconciliation state"
            )


def _run_record_lease_invariant(instance: Mapping[str, Any]) -> None:
    """Validate RunLease internal ordering without asserting wall-clock freshness."""
    lease = instance.get("lease")
    if lease is None:
        return
    if not isinstance(lease, Mapping):
        raise ValidationError("RunRecord.lease must be an object or null")

    acquired_at = _parse_exact_rfc3339_instant(
        lease,
        "acquired_at",
        "RunRecord.lease",
    )
    heartbeat_at = _parse_exact_rfc3339_instant(
        lease,
        "heartbeat_at",
        "RunRecord.lease",
    )
    expires_at = _parse_exact_rfc3339_instant(
        lease,
        "expires_at",
        "RunRecord.lease",
    )
    if acquired_at > heartbeat_at:
        raise ValidationError(
            "RunRecord.lease acquired_at must be earlier than or equal to heartbeat_at"
        )
    if heartbeat_at >= expires_at:
        raise ValidationError("RunRecord.lease heartbeat_at must be earlier than expires_at")


register_canonical_invariant("ActionRecord", _action_record_receipt_invariant)
register_canonical_invariant("RunRecord", _run_record_lease_invariant)


def validate_canonical_invariants(instance: Any, schema: Schema) -> None:
    if not isinstance(instance, Mapping):
        return

    title = schema.get("title")
    if not isinstance(title, str):
        return

    meta = instance.get("meta")
    if isinstance(meta, Mapping):
        if meta.get("contract_name") != title:
            raise ValidationError(f"meta.contract_name must equal {title}")

        schema_version = schema.get(SCHEMA_VERSION_KEY)
        if isinstance(schema_version, str) and meta.get("contract_version") != schema_version:
            raise ValidationError(
                f"meta.contract_version must equal current schema version {schema_version}"
            )

        id_field = _CANONICAL_ID_FIELDS.get(title)
        if id_field is not None and instance.get(id_field) != meta.get("object_id"):
            raise ValidationError(f"{id_field} must equal meta.object_id")

        properties = schema.get("properties")
        if (
            isinstance(properties, Mapping)
            and "tenant_id" in properties
            and "meta" in properties
            and instance.get("tenant_id") != meta.get("tenant_id")
        ):
            raise ValidationError(f"{title}.tenant_id must equal meta.tenant_id")

    for invariant in _CANONICAL_INVARIANTS.get(title, ()):
        invariant(instance)


def _load_event_catalog(
    schema_root: Path,
    documents: Mapping[str, tuple[Path, Schema]],
    registry: Registry[Any],
) -> dict[tuple[str, str], str]:
    catalog_path = schema_root / EVENT_CATALOG_RELATIVE_PATH
    if not catalog_path.is_file():
        raise ValueError(f"event catalog not found: {catalog_path}")

    catalog = load_json_object(catalog_path)
    catalog_schema_ref = catalog.get("$schema")
    if not isinstance(catalog_schema_ref, str) or catalog_schema_ref not in documents:
        raise ValueError(f"event catalog has unresolved $schema: {catalog_schema_ref!r}")
    _validate_with_schema(catalog, documents[catalog_schema_ref][1], registry)

    index: dict[tuple[str, str], str] = {}
    events = catalog.get("events")
    if not isinstance(events, list):
        raise ValueError(f"event catalog events must be an array: {catalog_path}")
    for entry in events:
        if not isinstance(entry, Mapping):
            raise ValueError(f"event catalog entry must be an object: {catalog_path}")
        event_name = entry.get("event_name")
        event_version = entry.get("event_version")
        payload_schema_ref = entry.get("payload_schema_ref")
        if not all(
            isinstance(value, str) for value in (event_name, event_version, payload_schema_ref)
        ):
            raise ValueError(f"event catalog entry contains non-string fields: {entry!r}")

        key = cast(tuple[str, str], (event_name, event_version))
        if key in index:
            raise ValueError(f"duplicate event catalog entry: {key[0]}@{key[1]}")
        payload_ref = cast(str, payload_schema_ref)
        if payload_ref not in documents:
            raise ValueError(
                f"event catalog payload schema is not in the local registry: {payload_ref}"
            )
        index[key] = payload_ref
    return index


def _validate_registered_event(
    instance: Mapping[str, Any],
    schema_root: Path,
    documents: Mapping[str, tuple[Path, Schema]],
    registry: Registry[Any],
) -> None:
    catalog = _load_event_catalog(schema_root, documents, registry)
    event_name = instance.get("event_name")
    event_version = instance.get("event_version")
    payload_schema_ref = instance.get("payload_schema_ref")
    key = cast(tuple[str, str], (event_name, event_version))
    expected_payload_ref = catalog.get(key)
    if expected_payload_ref is None:
        raise ValidationError(f"event is not registered: {event_name}@{event_version}")
    if payload_schema_ref != expected_payload_ref:
        raise ValidationError(
            "event payload_schema_ref does not match the registered event contract"
        )

    payload_schema = documents[expected_payload_ref][1]
    _validate_with_schema(instance.get("payload"), payload_schema, registry)


def validate_schema_catalog(schema_root: Path) -> int:
    documents = _load_schema_documents(schema_root)
    registry = _registry_from_documents(documents)
    _validate_local_refs(documents, registry)
    _load_event_catalog(schema_root, documents, registry)
    _validate_schema_lock(schema_root, documents)
    return len(documents)


def update_schema_lock(schema_root: Path) -> tuple[int, int]:
    """Append new schema identity/version tuples without rewriting existing tuples."""
    documents = _load_schema_documents(schema_root)
    registry = _registry_from_documents(documents)
    _validate_local_refs(documents, registry)
    _load_event_catalog(schema_root, documents, registry)

    entries, lock_index = _load_schema_lock(schema_root, required=False)
    appended: list[SchemaLockEntry] = []
    for schema_id, (path, schema) in sorted(documents.items()):
        _, schema_version = _require_schema_metadata(path, schema)
        key = (schema_id, schema_version)
        digest = _schema_sha256(path)
        existing = lock_index.get(key)
        if existing is not None:
            if existing["sha256"] != digest:
                raise ValueError(
                    f"refusing to rewrite locked schema tuple {schema_id}@{schema_version}"
                )
            continue

        entry: SchemaLockEntry = {
            "$id": schema_id,
            SCHEMA_VERSION_KEY: schema_version,
            "sha256": digest,
        }
        entries.append(entry)
        appended.append(entry)
        lock_index[key] = entry

    if appended or not (schema_root / SCHEMA_LOCK_RELATIVE_PATH).is_file():
        lock_payload = {"lock_version": SCHEMA_LOCK_VERSION, "schemas": entries}
        lock_path = schema_root / SCHEMA_LOCK_RELATIVE_PATH
        lock_path.write_text(
            json.dumps(lock_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return len(documents), len(appended)


def _load_registered_schema_path(
    schema_path: Path,
    schema_root: Path,
    documents: Mapping[str, tuple[Path, Schema]],
) -> Schema:
    resolved_root = schema_root.resolve()
    resolved_path = schema_path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"schema path is outside schema root: {schema_path}") from error

    schema = load_schema(resolved_path)
    schema_id, _ = _require_schema_metadata(resolved_path, schema)
    registered = documents.get(schema_id)
    if registered is None:
        raise ValueError(f"schema is not registered in the local catalog: {schema_id}")
    registered_path, _ = registered
    if registered_path.resolve() != resolved_path:
        raise ValueError(
            f"schema path does not match registered path for {schema_id}: {schema_path}"
        )
    return schema


def _validate_instance_from_catalog(
    instance: Any,
    schema_path: Path,
    schema_root: Path,
    documents: Mapping[str, tuple[Path, Schema]],
    registry: Registry[Any],
) -> None:
    schema = _load_registered_schema_path(schema_path, schema_root, documents)
    _validate_with_schema(instance, schema, registry)
    validate_canonical_invariants(instance, schema)

    if schema.get("title") == "EventEnvelope" and isinstance(instance, Mapping):
        _validate_registered_event(instance, schema_root, documents, registry)


def validate_instance(instance: Any, schema_path: Path, schema_root: Path) -> None:
    """Validate one registered object, without resolving cross-object facts.

    Success proves only that this instance satisfies its machine Schema and local
    canonical invariants. It does not prove referenced Policy, Approval, Receipt,
    reservation, Evidence, Gate, or Release facts exist or are consumable.
    """
    documents = _load_schema_documents(schema_root)
    registry = _registry_from_documents(documents)
    _validate_local_refs(documents, registry)
    _validate_schema_lock(schema_root, documents)
    _validate_instance_from_catalog(instance, schema_path, schema_root, documents, registry)


def _parse_aware_timestamp(instance: Mapping[str, Any], field: str, label: str) -> datetime:
    value = instance.get(field)
    if not isinstance(value, str):
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{label}.{field} must be an RFC 3339 timestamp") from error
    if parsed.utcoffset() is None:
        raise ValidationError(f"{label}.{field} must include a timezone offset")
    return parsed.astimezone(UTC)


def _activation_time(now: datetime | None) -> datetime:
    current = now or datetime.now(UTC)
    if current.utcoffset() is None:
        raise ValidationError("release activation time must include a timezone offset")
    return current.astimezone(UTC)


def _validate_active_decision(
    label: str,
    decision: Mapping[str, Any],
    *,
    required_outcome: str,
    now: datetime,
) -> tuple[datetime, datetime]:
    if decision.get("status") != "active":
        raise ValidationError(f"{label}.status must be active")
    if decision.get("outcome") != required_outcome:
        raise ValidationError(f"{label}.outcome must be {required_outcome}")

    issued_at = _parse_aware_timestamp(decision, "issued_at", label)
    expires_at = _parse_aware_timestamp(decision, "expires_at", label)
    if issued_at >= expires_at:
        raise ValidationError(f"{label}.issued_at must be earlier than expires_at")
    if issued_at > now:
        raise ValidationError(f"{label} is not yet effective")
    if expires_at <= now:
        raise ValidationError(f"{label} is expired")
    return issued_at, expires_at


def _validate_manifest_time(manifest: Mapping[str, Any], now: datetime) -> datetime:
    meta = manifest.get("meta")
    if not isinstance(meta, Mapping):
        raise ValidationError("ReleaseManifest.meta must be an object")
    created_at = _parse_aware_timestamp(meta, "created_at", "ReleaseManifest.meta")
    if created_at > now:
        raise ValidationError("ReleaseManifest is not yet effective")
    expires_value = meta.get("expires_at")
    if expires_value is None:
        return created_at
    expires_at = _parse_aware_timestamp(meta, "expires_at", "ReleaseManifest.meta")
    if created_at >= expires_at:
        raise ValidationError("ReleaseManifest.meta.created_at must be earlier than expires_at")
    if expires_at <= now:
        raise ValidationError("ReleaseManifest is expired")
    return created_at


def _require_same_value(
    label: str,
    expected: Any,
    actual: Any,
) -> None:
    if actual != expected:
        raise ValidationError(f"{label} does not match the release activation chain")


def _require_verifier_true(label: str, result: bool) -> None:
    if result is not True:
        raise ValidationError(f"release activation verifier rejected {label}")


def _validate_candidate_manifest_binding(
    release_candidate: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
) -> None:
    expected_versions: dict[str, set[str]] = {
        field: set() for field in _COMPONENT_VERSION_FIELDS.values()
    }
    components = release_candidate.get("components")
    if not isinstance(components, list):
        raise ValidationError("ReleaseCandidate.components must be an array")

    for component in components:
        if not isinstance(component, Mapping):
            raise ValidationError("ReleaseCandidate.components entries must be objects")
        component_type = component.get("component_type")
        component_ref = component.get("component_ref")
        version = component.get("version")
        if (
            not isinstance(component_type, str)
            or component_type not in _COMPONENT_VERSION_FIELDS
            or not isinstance(component_ref, str)
            or not isinstance(version, str)
        ):
            raise ValidationError("ReleaseCandidate contains an invalid component identity")
        field = _COMPONENT_VERSION_FIELDS[component_type]
        version_ref = f"{component_ref}@{version}"
        if version_ref in expected_versions[field]:
            raise ValidationError(
                "ReleaseCandidate contains a duplicate component identity: "
                f"{component_type}:{version_ref}"
            )
        expected_versions[field].add(version_ref)

    for field, expected in expected_versions.items():
        actual = release_manifest.get(field)
        if not isinstance(actual, list) or set(actual) != expected:
            raise ValidationError(
                f"ReleaseManifest.{field} does not exactly match ReleaseCandidate.components"
            )

    _require_same_value(
        "ReleaseManifest.contract_version_ranges",
        release_candidate.get("contract_version_ranges"),
        release_manifest.get("contract_version_ranges"),
    )
    _require_same_value(
        "ReleaseManifest.compatibility_matrix_ref",
        release_candidate.get("compatibility_matrix_ref"),
        release_manifest.get("compatibility_matrix_ref"),
    )

    candidate_migrations = release_candidate.get("migration_refs")
    manifest_migrations = release_manifest.get("migration_refs")
    if (
        not isinstance(candidate_migrations, list)
        or not isinstance(manifest_migrations, list)
        or set(candidate_migrations) != set(manifest_migrations)
    ):
        raise ValidationError(
            "ReleaseManifest.migration_refs does not exactly match ReleaseCandidate.migration_refs"
        )


def _validate_release_authority_separation(
    release_candidate: Mapping[str, Any],
    gates: tuple[tuple[str, Mapping[str, Any]], ...],
    release_decision: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
) -> None:
    builder_ref = release_candidate.get("candidate_builder_ref")
    gate_authorities = {gate.get("issued_by") for _, gate in gates}
    release_authority = release_decision.get("issued_by")
    manifest_meta = release_manifest.get("meta")
    manifest_producer = (
        manifest_meta.get("producer") if isinstance(manifest_meta, Mapping) else None
    )

    if len(gate_authorities) != len(gates):
        raise ValidationError("release Gate authorities must be pairwise distinct")
    if builder_ref in gate_authorities or builder_ref == release_authority:
        raise ValidationError(
            "ReleaseCandidate builder must be separated from gate and release authorities"
        )
    if release_authority in gate_authorities:
        raise ValidationError("ReleaseDecision authority must be separated from gate authorities")
    if manifest_producer == builder_ref:
        raise ValidationError(
            "ReleaseManifest producer must be separated from ReleaseCandidate builder"
        )


def _canonical_json_snapshot(
    label: str,
    instance: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    try:
        canonical_json = json.dumps(
            instance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        snapshot = json.loads(canonical_json)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{label} must be a canonical JSON object") from error
    if not isinstance(snapshot, dict):
        raise ValidationError(f"{label} must be a canonical JSON object")
    return cast(dict[str, Any], snapshot), canonical_json


def _fresh_verifier_copy(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Return a disposable JSON copy that a verifier may never use to mutate master state."""
    copied = json.loads(
        json.dumps(
            instance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return cast(dict[str, Any], copied)


def _require_caller_inputs_unchanged(
    caller_snapshots: tuple[tuple[str, Mapping[str, Any], str], ...],
) -> None:
    for contract_name, caller_instance, entry_json in caller_snapshots:
        _, current_json = _canonical_json_snapshot(contract_name, caller_instance)
        if current_json != entry_json:
            raise ValidationError(f"{contract_name} caller input changed during release activation")


def _run_release_activation_verifier(
    verifier: ReleaseActivationVerifier,
    contracts: tuple[tuple[str, Mapping[str, Any], Path], ...],
    expected_scope: Mapping[str, object],
    release_candidate: Mapping[str, Any],
    gates: tuple[tuple[str, Mapping[str, Any]], ...],
    release_decision: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
) -> None:
    authority_refs: dict[str, Any] = {
        "ReleaseCandidate": release_candidate.get("candidate_builder_ref"),
        **{label: gate.get("issued_by") for label, gate in gates},
        "ReleaseDecision": release_decision.get("issued_by"),
        "ReleaseManifest": (
            release_manifest.get("meta", {}).get("producer")
            if isinstance(release_manifest.get("meta"), Mapping)
            else None
        ),
    }

    for contract_name, instance, _ in contracts:
        authority_ref = authority_refs.get(contract_name)
        if not isinstance(authority_ref, str) or not authority_ref:
            raise ValidationError(f"{contract_name} has no activation authority reference")
        _require_verifier_true(
            f"{contract_name} integrity",
            verifier.verify_integrity(
                contract_name,
                _fresh_verifier_copy(instance),
            ),
        )
        _require_verifier_true(
            f"{contract_name} evidence accessibility",
            verifier.verify_evidence_access(
                contract_name,
                _fresh_verifier_copy(instance),
            ),
        )
        _require_verifier_true(
            f"{contract_name} authority role and trust",
            verifier.verify_authority_role_and_trust(
                contract_name,
                authority_ref,
                _fresh_verifier_copy(instance),
            ),
        )
        _require_verifier_true(
            f"{contract_name} waiver conflicts",
            verifier.verify_waiver_conflicts(
                contract_name,
                _fresh_verifier_copy(instance),
            ),
        )
        _require_verifier_true(
            f"{contract_name} scope coverage",
            verifier.verify_scope_coverage(
                contract_name,
                _fresh_verifier_copy(expected_scope),
                _fresh_verifier_copy(instance),
            ),
        )

    _require_verifier_true(
        "rollback compatibility",
        verifier.verify_rollback_compatibility(
            _fresh_verifier_copy(release_candidate),
            _fresh_verifier_copy(release_manifest),
        ),
    )


def validate_release_activation(
    release_candidate: Mapping[str, Any],
    quality_gate_decision: Mapping[str, Any],
    security_gate_decision: Mapping[str, Any],
    operational_readiness_decision: Mapping[str, Any],
    release_decision: Mapping[str, Any],
    release_manifest: Mapping[str, Any],
    schema_root: Path,
    *,
    expected_candidate_ref: str,
    verifier: ReleaseActivationVerifier | None,
    now: datetime | None = None,
) -> None:
    """Fail closed unless a trusted verifier accepts a complete activation chain.

    ``verifier`` is a required Phase 4 integration dependency. This module only
    defines and invokes that trust boundary; it does not implement production
    integrity, authority, evidence, waiver, scope, or rollback resolution. Callers
    must activate from a content-addressed immutable store or equivalent CAS. A
    mutable caller object after return is never activation proof.
    """
    caller_contracts: tuple[tuple[str, Mapping[str, Any], Path], ...] = (
        (
            "ReleaseCandidate",
            release_candidate,
            Path("release/release-candidate.schema.json"),
        ),
        (
            "QualityGateDecision",
            quality_gate_decision,
            Path("eval/quality-gate-decision.schema.json"),
        ),
        (
            "SecurityGateDecision",
            security_gate_decision,
            Path("release/security-gate-decision.schema.json"),
        ),
        (
            "OperationalReadinessDecision",
            operational_readiness_decision,
            Path("release/operational-readiness-decision.schema.json"),
        ),
        (
            "ReleaseDecision",
            release_decision,
            Path("release/release-decision.schema.json"),
        ),
        (
            "ReleaseManifest",
            release_manifest,
            Path("release/release-manifest.schema.json"),
        ),
    )
    master_contracts: list[tuple[str, Mapping[str, Any], Path]] = []
    caller_snapshot_items: list[tuple[str, Mapping[str, Any], str]] = []
    for contract_name, caller_instance, relative_path in caller_contracts:
        master_snapshot, entry_json = _canonical_json_snapshot(
            contract_name,
            caller_instance,
        )
        master_contracts.append((contract_name, master_snapshot, relative_path))
        caller_snapshot_items.append((contract_name, caller_instance, entry_json))
    contracts = tuple(master_contracts)
    caller_snapshots = tuple(caller_snapshot_items)

    release_candidate = contracts[0][1]
    quality_gate_decision = contracts[1][1]
    security_gate_decision = contracts[2][1]
    operational_readiness_decision = contracts[3][1]
    release_decision = contracts[4][1]
    release_manifest = contracts[5][1]

    if verifier is None:
        raise ValidationError("release activation requires a trusted verifier")

    documents = _load_schema_documents(schema_root)
    registry = _registry_from_documents(documents)
    _validate_local_refs(documents, registry)
    _load_event_catalog(schema_root, documents, registry)
    _validate_schema_lock(schema_root, documents)

    for _, instance, relative_path in contracts:
        _validate_instance_from_catalog(
            instance,
            schema_root / relative_path,
            schema_root,
            documents,
            registry,
        )

    current = _activation_time(now)
    if not expected_candidate_ref:
        raise ValidationError("expected_candidate_ref must not be empty")
    _require_same_value(
        "ReleaseCandidate.release_candidate_id",
        expected_candidate_ref,
        release_candidate.get("release_candidate_id"),
    )

    candidate_built_at = _parse_aware_timestamp(release_candidate, "built_at", "ReleaseCandidate")
    if candidate_built_at > current:
        raise ValidationError("ReleaseCandidate is not yet built")

    gates: tuple[tuple[str, Mapping[str, Any]], ...] = (
        ("QualityGateDecision", quality_gate_decision),
        ("SecurityGateDecision", security_gate_decision),
        ("OperationalReadinessDecision", operational_readiness_decision),
    )
    gate_issued_at: list[datetime] = []
    expected_environment = quality_gate_decision.get("environment")
    expected_scope = quality_gate_decision.get("scope")
    if not isinstance(expected_scope, Mapping):
        raise ValidationError("QualityGateDecision.scope must be an object")

    tenants = {
        meta.get("tenant_id")
        for _, instance, _ in contracts
        if isinstance((meta := instance.get("meta")), Mapping)
    }
    if len(tenants) != 1:
        raise ValidationError("release activation contracts must belong to one tenant")
    canonical_tenant = next(iter(tenants))
    if expected_scope.get("tenant_id") != canonical_tenant:
        raise ValidationError("release activation scope.tenant_id must equal the canonical tenant")

    for label, gate in gates:
        issued_at, _ = _validate_active_decision(
            label,
            gate,
            required_outcome="pass",
            now=current,
        )
        gate_issued_at.append(issued_at)
        if label in {"QualityGateDecision", "SecurityGateDecision"} and gate.get(
            "hard_failure_refs"
        ):
            raise ValidationError(f"{label}.hard_failure_refs must be empty for pass")
        if issued_at < candidate_built_at:
            raise ValidationError(f"{label} was issued before the candidate was built")
        _require_same_value(
            f"{label}.candidate_ref",
            expected_candidate_ref,
            gate.get("candidate_ref"),
        )
        _require_same_value(
            f"{label}.environment",
            expected_environment,
            gate.get("environment"),
        )
        _require_same_value(f"{label}.scope", expected_scope, gate.get("scope"))

    release_issued_at, _ = _validate_active_decision(
        "ReleaseDecision",
        release_decision,
        required_outcome="approved",
        now=current,
    )
    if any(issued_at > release_issued_at for issued_at in gate_issued_at):
        raise ValidationError("ReleaseDecision was issued before one or more gate decisions")
    _require_same_value(
        "ReleaseDecision.candidate_ref",
        expected_candidate_ref,
        release_decision.get("candidate_ref"),
    )
    _require_same_value(
        "ReleaseDecision.environment",
        expected_environment,
        release_decision.get("environment"),
    )
    _require_same_value(
        "ReleaseDecision.scope",
        expected_scope,
        release_decision.get("scope"),
    )

    gate_refs = (
        (
            "ReleaseDecision.quality_gate_decision_ref",
            quality_gate_decision.get("quality_gate_decision_id"),
            release_decision.get("quality_gate_decision_ref"),
        ),
        (
            "ReleaseDecision.security_gate_decision_ref",
            security_gate_decision.get("security_gate_decision_id"),
            release_decision.get("security_gate_decision_ref"),
        ),
        (
            "ReleaseDecision.operational_readiness_decision_ref",
            operational_readiness_decision.get("operational_readiness_decision_id"),
            release_decision.get("operational_readiness_decision_ref"),
        ),
    )
    for label, expected, actual in gate_refs:
        _require_same_value(label, expected, actual)

    if release_manifest.get("lifecycle_status") != "active":
        raise ValidationError("ReleaseManifest.lifecycle_status must be active")
    manifest_created_at = _validate_manifest_time(release_manifest, current)
    if manifest_created_at < release_issued_at:
        raise ValidationError("ReleaseManifest was created before ReleaseDecision was issued")
    _require_same_value(
        "ReleaseManifest.environment",
        expected_environment,
        release_manifest.get("environment"),
    )

    manifest_refs = (
        (
            "ReleaseManifest.quality_gate_decision_ref",
            quality_gate_decision.get("quality_gate_decision_id"),
            release_manifest.get("quality_gate_decision_ref"),
        ),
        (
            "ReleaseManifest.security_gate_decision_ref",
            security_gate_decision.get("security_gate_decision_id"),
            release_manifest.get("security_gate_decision_ref"),
        ),
        (
            "ReleaseManifest.operational_readiness_decision_ref",
            operational_readiness_decision.get("operational_readiness_decision_id"),
            release_manifest.get("operational_readiness_decision_ref"),
        ),
        (
            "ReleaseManifest.release_decision_ref",
            release_decision.get("release_decision_id"),
            release_manifest.get("release_decision_ref"),
        ),
    )
    for label, expected, actual in manifest_refs:
        _require_same_value(label, expected, actual)

    _validate_candidate_manifest_binding(release_candidate, release_manifest)
    _validate_release_authority_separation(
        release_candidate,
        gates,
        release_decision,
        release_manifest,
    )
    _run_release_activation_verifier(
        verifier,
        contracts,
        cast(Mapping[str, object], expected_scope),
        release_candidate,
        gates,
        release_decision,
        release_manifest,
    )
    _require_caller_inputs_unchanged(caller_snapshots)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the UEAF machine schema catalog")
    parser.add_argument("schema_root", type=Path)
    parser.add_argument(
        "--update-lock",
        action="store_true",
        help="append previously unseen schema identity/version tuples to schema-lock.json",
    )
    parser.add_argument(
        "--baseline-lock",
        type=Path,
        help="validate append-only history against a schema-lock.json from the base revision",
    )
    args = parser.parse_args()
    if args.update_lock:
        count, appended = update_schema_lock(args.schema_root)
        print(f"locked {count} schema documents ({appended} appended tuples)")
    else:
        count = validate_schema_catalog(args.schema_root)
        print(f"validated {count} schema documents")
    if args.baseline_lock is not None:
        historical_count = validate_schema_lock_history(
            args.schema_root / SCHEMA_LOCK_RELATIVE_PATH,
            args.baseline_lock,
        )
        print(f"validated {historical_count} historical schema lock tuples")


if __name__ == "__main__":
    main()
