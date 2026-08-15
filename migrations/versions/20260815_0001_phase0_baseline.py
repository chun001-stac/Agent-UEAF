"""Establish the empty Phase 0 database baseline.

Revision ID: 20260815_0001
Revises:
Create Date: 2026-08-15
"""

from collections.abc import Sequence

revision: str = "20260815_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the baseline without inventing domain tables."""


def downgrade() -> None:
    """Remove the empty baseline without changing database objects."""
