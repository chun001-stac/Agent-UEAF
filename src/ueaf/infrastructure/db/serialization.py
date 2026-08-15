"""Generic JSON codec for frozen canonical dataclasses.

Stores full objects (including nested ``ContractMeta``) in a ``payload`` JSON
column so the ORM row can always rebuild the canonical object without losing
fields (implementation spec 03 §4). ``datetime`` -> ISO-8601 string, tuples ->
JSON arrays (restored as tuples on decode).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

from ueaf.admission.controller import RunAdmissionResult
from ueaf.common.meta import ContractMeta, ProvenanceRef
from ueaf.runtime.objects import RunLease, RunRecord, TaskState

_CLASS_REGISTRY: dict[str, type[Any]] = {
    cls.__name__: cls
    for cls in (
        ContractMeta,
        ProvenanceRef,
        RunLease,
        RunRecord,
        TaskState,
        RunAdmissionResult,
    )
}

_DT = "$dt"
_TUPLE = "$tuple"
_CLASS = "$class"
_VALUE = "v"


def encode_value(value: Any) -> Any:
    """Encode a dataclass/container tree into a JSON-safe structure."""
    if isinstance(value, datetime):
        return {_DT: value.isoformat()}
    if isinstance(value, tuple):
        return {_TUPLE: [encode_value(item) for item in value]}
    if isinstance(value, list):
        return [encode_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_value(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            _CLASS: type(value).__name__,
            _VALUE: {
                field.name: encode_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot encode {type(value).__name__}")


def decode_value(value: Any) -> Any:
    """Decode a JSON-safe structure back into the canonical dataclass tree."""
    if isinstance(value, dict):
        if _DT in value:
            parsed = datetime.fromisoformat(value[_DT])
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        if _TUPLE in value:
            return tuple(decode_value(item) for item in value[_TUPLE])
        if _CLASS in value:
            cls = _CLASS_REGISTRY.get(value[_CLASS])
            if cls is None:
                raise ValueError(f"unknown serialized class {value[_CLASS]!r}")
            kwargs = {key: decode_value(item) for key, item in value[_VALUE].items()}
            return cls(**kwargs)
        return {str(key): decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    return value
