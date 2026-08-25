"""Safe projection bridge from process-local task evidence to PostgreSQL."""

from __future__ import annotations

from ai_ui_explorer.persistence.dtos import PersistedTaskPageEvidence
from ai_ui_explorer.persistence.repositories import SafeTaskRepository
from ai_ui_explorer.task_management.evidence import TaskEvidenceCollector
from ai_ui_explorer.task_management.models import TaskSummary

_TERMINAL_STATES = frozenset({"completed", "partial", "failed", "cancelled"})


class TaskProjectionPersistenceError(RuntimeError):
    """A task cannot be converted into a complete safe persistence projection."""


class PersistentTaskProjectionStore:
    """Persist terminal task summaries with only redacted evidence projections."""

    def __init__(self, *, repository: SafeTaskRepository) -> None:
        self._repository = repository

    def persist_terminal(
        self,
        *,
        summary: TaskSummary,
        collector: TaskEvidenceCollector,
    ) -> None:
        """Build all safe dependent views before a single repository transaction."""
        if str(summary.state) not in _TERMINAL_STATES:
            raise TaskProjectionPersistenceError("Task projection unavailable")
        page_views = collector.pages()
        pages: list[PersistedTaskPageEvidence] = []
        for page_view in page_views:
            page = collector.page_detail(page_view.page_id)
            if page is None:
                raise TaskProjectionPersistenceError("Task projection unavailable")
            pages.append(PersistedTaskPageEvidence(page_id=page_view.page_id, page=page))
        evidence = collector.export(
            task_id=summary.task_id,
            state=summary.state,
            result=summary.result,
        )
        workflow = collector.workflow(task_id=summary.task_id, state=summary.state)
        self._repository.persist_terminal_task(
            summary=summary,
            evidence=evidence,
            workflow=workflow,
            pages=pages,
        )
