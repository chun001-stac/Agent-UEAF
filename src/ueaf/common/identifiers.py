"""Deterministic identifier / reference helpers for canonical objects."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware RFC 3339 UTC timestamp used across the implementation."""
    return datetime.now(UTC)


def new_object_id(prefix: str) -> str:
    """Generate a collision-resistant canonical object id."""
    if not prefix:
        raise ValueError("prefix must not be empty")
    return f"{prefix}:{secrets.token_hex(12)}"


def sha256_hex(text: str) -> str:
    """Stable sha256 hex digest used for integrity/evidence references."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_ref(parts: tuple[str, ...]) -> str:
    """Stable colon-joined reference; never trusts caller-provided ordering."""
    return ":".join(parts)
