"""Create safe terminal exploration projection tables.

Revision ID: 20260818_01
Revises:
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260818_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exploration_tasks",
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redaction_count", sa.Integer(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=False),
        sa.Column("events_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_exploration_tasks_state_updated_at",
        "exploration_tasks",
        ["state", "updated_at"],
    )
    op.create_table(
        "task_evidence_exports",
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["exploration_tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_table(
        "task_workflows",
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["exploration_tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_table(
        "permission_comparisons",
        sa.Column("comparison_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identities_json", postgresql.JSONB(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("comparison_id"),
    )
    op.create_index(
        "ix_permission_comparisons_state_updated_at",
        "permission_comparisons",
        ["state", "updated_at"],
    )
    op.create_table(
        "exploration_knowledge_sources",
        sa.Column("source_id", sa.String(length=40), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index(
        "ix_exploration_knowledge_sources_kind_state",
        "exploration_knowledge_sources",
        ["source_kind", "state"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exploration_knowledge_sources_kind_state",
        table_name="exploration_knowledge_sources",
    )
    op.drop_table("exploration_knowledge_sources")
    op.drop_index(
        "ix_permission_comparisons_state_updated_at",
        table_name="permission_comparisons",
    )
    op.drop_table("permission_comparisons")
    op.drop_table("task_workflows")
    op.drop_table("task_evidence_exports")
    op.drop_index(
        "ix_exploration_tasks_state_updated_at",
        table_name="exploration_tasks",
    )
    op.drop_table("exploration_tasks")
