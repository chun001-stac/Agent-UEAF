"""ToolResult projection: minimal safe summaries (ACT-016/017, module 05).

The Result Projector turns a raw tool/provider response into a minimal
``ToolResult`` whose status uses only the public outcome vocabulary
(``succeeded|failed|unknown`` — ACT-010). Large or high-sensitivity payloads
are routed to a controlled artifact store, and credential-like fields are
scrubbed so their values never enter arguments, summaries, receipts or traces
(ACT-017).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ueaf.common.identifiers import new_object_id

PublicToolStatus = Literal["succeeded", "failed", "unknown"]

# Public outcome vocabulary exposed by Tool/Gateway (ACT-010). Anything else
# (e.g. "definite_not_executed") is an internal condition, never public.
PUBLIC_STATUS_VALUES: frozenset[str] = frozenset({"succeeded", "failed", "unknown"})

# Credential-like keys that must never have their values projected (ACT-017).
DEFAULT_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "access_key",
        "secret_key",
        "private_key",
        "authorization",
        "cookie",
        "session_id",
        "client_secret",
    }
)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Minimal safe projection of a tool side-effect (never carries credentials)."""

    tool_result_id: str
    action_key: str
    status: PublicToolStatus
    summary: str
    content_schema_ref: str
    artifact_ref: str | None = None
    citations: tuple[str, ...] = ()
    excluded_secret_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in PUBLIC_STATUS_VALUES:
            raise ValueError(f"invalid ToolResult.status {self.status!r}")


class ResultProjector:
    """Builds minimal, secret-free ``ToolResult`` projections (ACT-016/017)."""

    def __init__(
        self,
        *,
        secret_keys: frozenset[str] | None = None,
        large_threshold: int = 4096,
        artifact_store: Any | None = None,
    ) -> None:
        self._secret_keys = (
            frozenset(secret_keys) if secret_keys is not None else DEFAULT_SECRET_KEYS
        )
        self._large_threshold = large_threshold
        self._artifact_store = artifact_store

    def project(
        self,
        *,
        action_key: str,
        status: PublicToolStatus,
        raw: Mapping[str, Any],
        content_schema_ref: str,
        summary: str | None = None,
        citations: tuple[str, ...] = (),
    ) -> ToolResult:
        """Scrub secrets from ``raw`` and produce a safe ToolResult."""
        _scrubbed, excluded = _scrub_secrets(raw, self._secret_keys)
        size = _encoded_size(_scrubbed)

        artifact_ref: str | None = None
        if size > self._large_threshold and self._artifact_store is not None:
            artifact_ref = self._store_artifact(action_key, _scrubbed)

        return ToolResult(
            tool_result_id=new_object_id("tool_result"),
            action_key=action_key,
            status=status,
            summary=summary or _default_summary(raw),
            content_schema_ref=content_schema_ref,
            artifact_ref=artifact_ref,
            citations=citations,
            excluded_secret_keys=excluded,
        )

    def _store_artifact(self, action_key: str, scrubbed: Mapping[str, Any]) -> str:
        import json

        key = f"{action_key}/result"
        data = json.dumps(scrubbed, sort_keys=True, default=str).encode("utf-8")
        # Structural protocol: put(key, data, content_type=...) -> ArtifactRef
        ref = self._artifact_store.put(  # type: ignore[union-attr]
            key, data, content_type="application/json"
        )
        return str(ref.key)


def _scrub_secrets(
    value: Any, secret_keys: frozenset[str], path: str = ""
) -> tuple[Any, tuple[str, ...]]:
    """Recursively replace secret values with a placeholder; never leaks them."""
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        excluded: list[str] = []
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            is_secret = str(key).lower() in secret_keys or any(
                marker in str(key).lower() for marker in ("password", "secret", "token", "key")
            )
            if is_secret:
                scrubbed[str(key)] = "[REDACTED]"
                excluded.append(str(key))
            else:
                sub_value, sub_excluded = _scrub_secrets(item, secret_keys, key_path)
                scrubbed[str(key)] = sub_value
                excluded.extend(sub_excluded)
        return scrubbed, tuple(excluded)
    if isinstance(value, list):
        items: list[Any] = []
        excluded_l: list[str] = []
        for item in value:
            sub_value, sub_excluded = _scrub_secrets(item, secret_keys, path)
            items.append(sub_value)
            excluded_l.extend(sub_excluded)
        return items, tuple(excluded_l)
    return value, ()


def _encoded_size(value: Any) -> int:
    import json

    return len(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))


def _default_summary(raw: Mapping[str, Any]) -> str:
    keys = sorted(str(k) for k in raw.keys())[:5]
    return f"result:{','.join(keys) or 'empty'}"


__all__ = ["ToolResult", "ResultProjector", "PUBLIC_STATUS_VALUES", "DEFAULT_SECRET_KEYS"]
