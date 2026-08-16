"""冻结规范 dataclass 的通用 JSON 编解码器。

将完整对象（包括嵌套的 ``ContractMeta``）存入 ``payload`` JSON 列，使 ORM 行
在不丢失字段的情况下始终能重建规范对象（实现规范 03 §4）。``datetime`` ->
ISO-8601 字符串，元组 -> JSON 数组（解码时恢复为元组）。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

from ueaf.admission.controller import RunAdmissionResult
from ueaf.common.meta import ContractMeta, ProvenanceRef
from ueaf.memory.objects import MemoryRecord
from ueaf.runtime.objects import RunLease, RunRecord, TaskState
from ueaf.runtime.turn import TurnRecord
from ueaf.tool.action import ActionReceipt, ActionRecord

_CLASS_REGISTRY: dict[str, type[Any]] = {
    cls.__name__: cls
    for cls in (
        ContractMeta,
        ProvenanceRef,
        RunLease,
        RunRecord,
        TaskState,
        RunAdmissionResult,
        ActionRecord,
        ActionReceipt,
        TurnRecord,
        MemoryRecord,
    )
}

_DT = "$dt"
_TUPLE = "$tuple"
_CLASS = "$class"
_VALUE = "v"


def encode_value(value: Any) -> Any:
    """将 dataclass/容器树编码为 JSON 安全的结构。"""
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
    """将 JSON 安全的结构解码回规范 dataclass 树。"""
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
