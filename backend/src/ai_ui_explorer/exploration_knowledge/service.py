"""Terminal-only, process-local coordination for unified knowledge exports."""

from __future__ import annotations

from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from ai_ui_explorer.exploration_knowledge.builder import ExplorationKnowledgeBuilder
from ai_ui_explorer.exploration_knowledge.models import (
    ComparisonKnowledgeSource,
    ExplorationKnowledgePackageV2,
    ExplorationKnowledgeSource,
    TaskKnowledgeSource,
)
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel


class ExplorationKnowledgeExportError(RuntimeError):
    """Fixed, non-sensitive error for unavailable export sources."""


class ExplorationSourceView(DeepFrozenModel):
    """One safe terminal source available to the current process."""

    source_id: str = Field(pattern=r"^(task|comparison)-[0-9]{1,20}$")
    source_kind: Literal["task", "comparison"]
    state: Literal["completed", "partial", "failed", "cancelled"]
    page_count: int = Field(ge=0)
    identity_count: int = Field(ge=0)


class ExplorationKnowledgeExportRequest(DeepFrozenModel):
    """A bounded selection of terminal task and comparison sources."""

    task_ids: list[str] = Field(default_factory=list, max_length=5)
    comparison_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_bounded_sources(self) -> Self:
        source_ids = [*self.task_ids, *self.comparison_ids]
        if not source_ids:
            raise ValueError("knowledge export requires one source")
        if len(set(source_ids)) > 5:
            raise ValueError("knowledge export source limit exceeded")
        return self


class _TaskSourceService(Protocol):
    def list_summaries(self) -> list[object]:
        """Return safe public task views."""

    def knowledge_source(self, task_id: str) -> TaskKnowledgeSource | None:
        """Return a terminal redacted task source."""


class _ComparisonSourceService(Protocol):
    def list_views(self) -> list[object]:
        """Return safe public comparison views."""

    def knowledge_source(
        self,
        comparison_id: str,
    ) -> ComparisonKnowledgeSource | None:
        """Return a terminal redacted comparison source."""


class ExplorationKnowledgeExportService:
    """Build downloads on demand from safe terminal service projections only."""

    def __init__(
        self,
        *,
        task_service: _TaskSourceService,
        comparison_service: _ComparisonSourceService,
        builder: ExplorationKnowledgeBuilder | None = None,
    ) -> None:
        self._task_service = task_service
        self._comparison_service = comparison_service
        self._builder = builder or ExplorationKnowledgeBuilder()

    def sources(self) -> list[ExplorationSourceView]:
        """List only sources whose terminal safe projection is currently available."""
        sources: list[ExplorationSourceView] = []
        for summary in self._task_service.list_summaries():
            task_id = getattr(summary, "task_id", None)
            if isinstance(task_id, str):
                source = self._task_service.knowledge_source(task_id)
                if source is not None:
                    sources.append(_task_view(source))
        for view in self._comparison_service.list_views():
            comparison_id = getattr(view, "comparison_id", None)
            if isinstance(comparison_id, str):
                comparison_source = self._comparison_service.knowledge_source(
                    comparison_id
                )
                if comparison_source is not None:
                    sources.append(_comparison_view(comparison_source))
        return sorted(sources, key=lambda item: item.source_id)

    def export(
        self,
        request: ExplorationKnowledgeExportRequest,
    ) -> ExplorationKnowledgePackageV2:
        """Resolve exactly the requested safe sources and build no cached artifact."""
        sources = self._resolve_sources(request)
        return self._builder.build(sources)

    def _resolve_sources(
        self,
        request: ExplorationKnowledgeExportRequest,
    ) -> list[ExplorationKnowledgeSource]:
        sources: list[ExplorationKnowledgeSource] = []
        for task_id in sorted(set(request.task_ids)):
            source = self._task_service.knowledge_source(task_id)
            if source is None:
                raise ExplorationKnowledgeExportError("source unavailable")
            sources.append(source)
        for comparison_id in sorted(set(request.comparison_ids)):
            comparison_source = self._comparison_service.knowledge_source(comparison_id)
            if comparison_source is None:
                raise ExplorationKnowledgeExportError("source unavailable")
            sources.append(comparison_source)
        return sources


def _task_view(source: TaskKnowledgeSource) -> ExplorationSourceView:
    return ExplorationSourceView(
        source_id=source.source_id,
        source_kind="task",
        state=source.state,
        page_count=len(source.pages),
        identity_count=0,
    )


def _comparison_view(source: ComparisonKnowledgeSource) -> ExplorationSourceView:
    return ExplorationSourceView(
        source_id=source.source_id,
        source_kind="comparison",
        state=source.result.status,
        page_count=sum(len(identity.pages) for identity in source.result.identities),
        identity_count=len(source.result.identities),
    )
