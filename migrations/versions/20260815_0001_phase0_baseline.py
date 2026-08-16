"""建立空的 Phase 0 数据库基线。

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
    """记录基线，不创建任何领域表。"""


def downgrade() -> None:
    """移除空基线，不改变任何数据库对象。"""
