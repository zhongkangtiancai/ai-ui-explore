"""Process-local, redacted page evidence retained for one exploration task."""

from __future__ import annotations

from threading import RLock

from pydantic import Field, field_validator

from ai_ui_explorer.exploration.queue import ExplorationTarget
from ai_ui_explorer.exploration.runner import ExplorationEvidenceSink, ExplorationRunResult
from ai_ui_explorer.exploration.task import ExplorationTaskState
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.evidence import project_snapshot
from ai_ui_explorer.permission_comparison.models import EvidenceReference, PageEvidence
from ai_ui_explorer.snapshot.models import SnapshotDocument
from ai_ui_explorer.snapshot.redaction import Redactor
from ai_ui_explorer.task_management.models import TaskResultSummary

_SAFE_STOP_REASONS = frozenset({"collector_failure", "duplicate_state", "cancelled"})


class TaskPageView(DeepFrozenModel):
    """A bounded index entry for one already-redacted task evidence page."""

    page_id: str = Field(pattern=r"^page-[0-9]{1,20}$")
    page_key: str = Field(min_length=1, max_length=2_048)
    frame_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    status: str = Field(pattern=r"^observed$")
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=12)

    @field_validator("reason_codes")
    @classmethod
    def require_safe_reason_codes(cls, values: list[str]) -> list[str]:
        if any(value not in _SAFE_STOP_REASONS for value in values):
            raise ValueError("task page reason code is not allowed")
        return values


class ExplorationEvidenceExport(DeepFrozenModel):
    """A versioned, process-local export without Snapshot or browser handles."""

    schema_version: str = Field(pattern=r"^1\.0$")
    task_id: str = Field(pattern=r"^task-[0-9]{1,20}$")
    state: ExplorationTaskState
    result: TaskResultSummary | None = None
    pages: list[TaskPageView] = Field(default_factory=list, max_length=100)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)


class TaskEvidenceCollector(ExplorationEvidenceSink):
    """Project snapshots immediately and retain no raw browser observations."""

    def __init__(self, *, downstream: ExplorationEvidenceSink | None = None) -> None:
        self._lock = RLock()
        self._redactor = Redactor()
        self._downstream = downstream
        self._pages: dict[str, PageEvidence] = {}
        self._reason_codes: list[str] = []
        self._next_page_number = 1

    def record(self, target: ExplorationTarget, snapshot: SnapshotDocument) -> None:
        page = project_snapshot(target=target, snapshot=snapshot, redactor=self._redactor)
        with self._lock:
            page_id = f"page-{self._next_page_number}"
            self._next_page_number += 1
            self._pages[page_id] = page
        if self._downstream is not None:
            self._downstream.record(target, snapshot)

    def complete(self, result: ExplorationRunResult) -> None:
        reasons = sorted(set(result.stop_reasons).intersection(_SAFE_STOP_REASONS))
        with self._lock:
            self._reason_codes = reasons
        if self._downstream is not None:
            self._downstream.complete(result)

    def pages(self) -> list[TaskPageView]:
        with self._lock:
            return [
                _page_view(page_id, page, self._reason_codes)
                for page_id, page in self._pages.items()
            ]

    def page_detail(self, page_id: str) -> PageEvidence | None:
        with self._lock:
            return self._pages.get(page_id)

    def export(
        self,
        *,
        task_id: str,
        state: ExplorationTaskState,
        result: TaskResultSummary | None = None,
    ) -> ExplorationEvidenceExport:
        with self._lock:
            export = ExplorationEvidenceExport(
                schema_version="1.0",
                task_id=task_id,
                state=state,
                result=result,
                pages=[
                    _page_view(page_id, page, self._reason_codes)
                    for page_id, page in self._pages.items()
                ],
                reason_codes=list(self._reason_codes),
            )
        export.model_json_schema()
        return export


def _page_view(
    page_id: str,
    page: PageEvidence,
    reason_codes: list[str],
) -> TaskPageView:
    return TaskPageView(
        page_id=page_id,
        page_key=page.page_key,
        frame_count=len({element.frame_path for element in page.elements}),
        element_count=len(page.elements),
        link_count=sum(element.href is not None for element in page.elements),
        status="observed",
        reason_codes=list(reason_codes),
        evidence_refs=list(page.evidence_refs),
    )
