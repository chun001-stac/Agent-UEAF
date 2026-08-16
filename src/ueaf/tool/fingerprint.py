"""规范的动作身份：参数规范化 + 指纹（ACT-007/008）。"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ueaf.common.identifiers import sha256_hex

# 凭据类参数键，其值绝不允许进入指纹（ACT-017）。哈希前对值进行脱敏处理。
_SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|"
    r"access[_-]?key|private[_-]?key|authorization|client[_-]?secret)",
    re.IGNORECASE,
)


def _redact_secret_values(arguments: dict[str, Any]) -> dict[str, Any]:
    """将凭据类键的值替换为稳定的占位符。"""
    return {
        key: ("[REDACTED]" if _SECRET_KEY_PATTERN.search(key) else value)
        for key, value in arguments.items()
    }


def canonicalize_argument(value: Any) -> Any:
    """规范化参数以获得稳定的指纹（顺序/数字/时区/Unicode）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        # 规范化尾随零并序列化为稳定字符串，使指纹可 JSON 序列化且数字稳定（ACT-007）。
        return str(value.normalize())
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {
            str(k): canonicalize_argument(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_argument(item) for item in value]
    if isinstance(value, set):
        return sorted(canonicalize_argument(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ActionFingerprint:
    """逻辑副作用的稳定身份（绑定租户/主体/能力）。"""

    tenant_id: str
    principal_id: str
    capability_ref: str
    capability_version: str
    resource: str
    arguments: dict[str, Any]
    purpose: str = "execution"
    trace_id: str | None = None

    @property
    def canonical_arguments(self) -> dict[str, Any]:
        canonical = {
            str(k): canonicalize_argument(v)
            for k, v in sorted(self.arguments.items())
        }
        # ACT-017：凭据值绝不允许进入指纹。
        return _redact_secret_values(canonical)

    @property
    def action_fingerprint(self) -> str:
        payload = json.dumps(
            {
                "tenant_id": self.tenant_id,
                "principal_id": self.principal_id,
                "capability_ref": self.capability_ref,
                "capability_version": self.capability_version,
                "resource": self.resource,
                "arguments": self.canonical_arguments,
                "purpose": self.purpose,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return sha256_hex(payload)

    @property
    def action_key(self) -> str:
        """逻辑副作用的稳定幂等身份（ACT-002）。"""
        return sha256_hex(f"action-key:{self.action_fingerprint}")
