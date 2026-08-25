"""In-memory task views and registry for controlled exploration."""

from ai_ui_explorer.task_management.evidence import (
    ExplorationEvidenceExport,
    TaskEvidenceCollector,
    TaskPageView,
)
from ai_ui_explorer.task_management.models import (
    ManagedTask,
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry

__all__ = [
    "ExplorationTaskRegistry",
    "ExplorationEvidenceExport",
    "ManagedTask",
    "TaskEvidenceCollector",
    "TaskEventView",
    "TaskPageView",
    "TaskResultSummary",
    "TaskSummary",
]
