"""创建 RAG 索引元数据表。

Revision ID: 20260816_0004
Revises: 20260816_0003
Create Date: 2026-08-16

表：``rag_index_sources``、``rag_index_projections``、``rag_index_chunks``。

沿用 0003 模式：每行保留完整的 ``payload`` JSON 列，用于重建索引元数据；
标量列支持按租户/用途范围查询。向量不存储在 SQL 中 —— 它们存放在 Qdrant
按（tenant, purpose）隔离的 collection 中；本迁移只跟踪
source/version/projection/chunk_refs 元数据，使 SQL 层能回答
"索引了什么、来自哪个源版本、在哪个策略下"。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0004"
down_revision: str | None = "20260816_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    _create_rag_index_sources()
    _create_rag_index_projections()
    _create_rag_index_chunks()


def _create_rag_index_sources() -> None:
    op.create_table(
        "rag_index_sources",
        sa.Column("source_ref", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index(
        "ix_rag_index_sources_tenant_purpose", "rag_index_sources", ["tenant_id", "purpose"]
    )
    op.create_index("ix_rag_index_sources_status", "rag_index_sources", ["status"])


def _create_rag_index_projections() -> None:
    op.create_table(
        "rag_index_projections",
        sa.Column("projection_id", sa.String(), primary_key=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("chunk_version", sa.String(), nullable=False),
        sa.Column("embedding_version", sa.String(), nullable=True),
        sa.Column("index_version", sa.String(), nullable=False),
        sa.Column("projection_digest", sa.String(), nullable=False),
        sa.Column("chunk_refs", JSON_COLUMN, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_rag_index_projections_source_ref", "rag_index_projections", ["source_ref"])
    op.create_index(
        "ix_rag_index_projections_digest", "rag_index_projections", ["projection_digest"]
    )


def _create_rag_index_chunks() -> None:
    op.create_table(
        "rag_index_chunks",
        sa.Column("chunk_id", sa.String(), primary_key=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("source_version", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("locator", sa.String(), nullable=False),
        sa.Column("embedding_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_rag_index_chunks_source_ref", "rag_index_chunks", ["source_ref"])
    op.create_index(
        "ix_rag_index_chunks_tenant_purpose", "rag_index_chunks", ["tenant_id", "purpose"]
    )
    op.create_index("ix_rag_index_chunks_embedding_ref", "rag_index_chunks", ["embedding_ref"])


def downgrade() -> None:
    op.drop_table("rag_index_chunks")
    op.drop_table("rag_index_projections")
    op.drop_table("rag_index_sources")
