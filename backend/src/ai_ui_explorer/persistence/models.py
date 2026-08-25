"""PostgreSQL tables containing only safe, terminal exploration projections."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative metadata used by Alembic and persistence repositories."""


class ExplorationTaskRecord(Base):
    __tablename__ = "exploration_tasks"
    __table_args__ = (Index("ix_exploration_tasks_state_updated_at", "state", "updated_at"),)

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    events_json: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'1.0'")
    )


class TaskEvidenceExportRecord(Base):
    __tablename__ = "task_evidence_exports"

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exploration_tasks.task_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)


class TaskWorkflowRecord(Base):
    __tablename__ = "task_workflows"

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exploration_tasks.task_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'1.0'")
    )


class PermissionComparisonRecord(Base):
    __tablename__ = "permission_comparisons"
    __table_args__ = (Index("ix_permission_comparisons_state_updated_at", "state", "updated_at"),)

    comparison_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    identities_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'1.0'")
    )


class ExplorationKnowledgeSourceRecord(Base):
    __tablename__ = "exploration_knowledge_sources"
    __table_args__ = (Index("ix_exploration_knowledge_sources_kind_state", "source_kind", "state"),)

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'1.0'")
    )
