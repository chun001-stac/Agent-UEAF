"""Credential scanning: no credential material in content domains (SEC-003).

Prompts, tool args, ordinary logs/traces/event payloads and the Evolution
Working Set must never carry credential material. ``CredentialScanner`` applies
conservative patterns and raises ``CredentialScanError`` when a scan domain
contains a match.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Conservative credential markers (avoid noisy false positives on ordinary text).
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:password|passwd)\s*[=:]\s*[^\s,;]{4,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?key)\s*[=:]\s*[^\s,;]{8,}"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT-ish
)


class CredentialScanError(RuntimeError):
    """Raised when credential material is found in a content domain (SEC-003)."""


class CredentialScanner:
    """Scans named content domains for credential material."""

    def __init__(self, patterns: tuple[re.Pattern[str], ...] | None = None) -> None:
        self._patterns = patterns or _CREDENTIAL_PATTERNS

    def find_in(self, text: str) -> list[str]:
        """Return redacted pattern names matched in ``text`` (never the value)."""
        found: list[str] = []
        for pattern in self._patterns:
            match = pattern.search(text)
            if match is not None:
                found.append(f"{pattern.pattern[:24]}…")
        return found

    def scan(
        self,
        *,
        prompt: str | None = None,
        tool_args: Mapping[str, Any] | None = None,
        log: str | None = None,
        trace: Mapping[str, Any] | None = None,
        event_payload: Mapping[str, Any] | None = None,
        working_set: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Scan every provided domain; returns a list of domain names with hits."""
        hits: list[str] = []
        domains: dict[str, str] = {
            "prompt": prompt or "",
            "log": log or "",
        }
        for name, mapping in (
            ("tool_args", tool_args),
            ("trace", trace),
            ("event_payload", event_payload),
            ("working_set", working_set),
        ):
            if mapping is not None:
                domains[name] = _flatten(mapping)
        for domain, text in domains.items():
            if self.find_in(text):
                hits.append(domain)
        return hits

    def assert_clean(self, **domains: Any) -> None:
        """Raise ``CredentialScanError`` if any domain contains credentials."""
        hits = self.scan(**domains)
        if hits:
            raise CredentialScanError(
                f"credential material detected in: {', '.join(hits)}"
            )


def _flatten(value: Any, prefix: str = "") -> str:
    if isinstance(value, Mapping):
        return " ".join(
            f"{prefix}.{k}={_flatten(v, f'{prefix}.{k}')}" for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v, prefix) for v in value)
    return str(value)


__all__ = ["CredentialScanner", "CredentialScanError"]
