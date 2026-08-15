"""Canonical action identity: argument canonicalization + fingerprint (ACT-007/008)."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ueaf.common.identifiers import sha256_hex

# Credential-like argument keys whose values must never enter the fingerprint
# (ACT-017). Values are redacted before hashing.
_SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|"
    r"access[_-]?key|private[_-]?key|authorization|client[_-]?secret)",
    re.IGNORECASE,
)


def _redact_secret_values(arguments: dict[str, Any]) -> dict[str, Any]:
    """Replace values of credential-like keys with a stable placeholder."""
    return {
        key: ("[REDACTED]" if _SECRET_KEY_PATTERN.search(key) else value)
        for key, value in arguments.items()
    }


def canonicalize_argument(value: Any) -> Any:
    """Normalize an argument for stable fingerprinting (order/digits/tz/unicode)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        # Normalize trailing zeros and serialize as a stable string so the
        # fingerprint is JSON-serializable and digit-stable (ACT-007).
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
    """Stable identity of a logical side effect (binds tenant/principal/capability)."""

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
        # ACT-017: credential values never enter the fingerprint.
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
        """Stable idempotency identity for the logical side effect (ACT-002)."""
        return sha256_hex(f"action-key:{self.action_fingerprint}")
