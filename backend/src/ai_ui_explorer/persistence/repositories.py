"""Repository codecs for strictly validated safe task projections."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_ui_explorer.exploration.workflows import TaskWorkflowExport
from ai_ui_explorer.exploration_knowledge.models import TaskKnowledgeSource
from ai_ui_explorer.permission_comparison.models import PageEvidence
from ai_ui_explorer.permission_comparison.service import PermissionComparisonView
from ai_ui_explorer.persistence.database import session_scope
from ai_ui_explorer.persistence.dtos import (
    PersistedTaskPageEvidence,
    TaskEvidencePersistencePayload,
)
from ai_ui_explorer.persistence.models import (
    ExplorationKnowledgeSourceRecord,
    ExplorationTaskRecord,
    PermissionComparisonRecord,
    TaskEvidenceExportRecord,
    TaskWorkflowRecord,
)
from ai_ui_explorer.task_management.evidence import ExplorationEvidenceExport, TaskPageView
from ai_ui_explorer.task_management.models import TaskSummary

_TASK_PROJECTION_SCHEMA_VERSION = "1.0"
_TERMINAL_TASK_STATES = frozenset({"completed", "partial", "failed", "cancelled"})


class PersistenceProjectionError(RuntimeError):
    """A persisted projection cannot be safely exposed to a caller."""


class SafeTaskRepository:
    """Transactional persistence operations over safe task projections only."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def interrupt_nonterminal_tasks(self, *, occurred_at: datetime) -> list[str]:
        """Safely terminate records that lost their process-local runtime on restart."""
        with session_scope(self._session_factory) as session:
            records = session.scalars(
                select(ExplorationTaskRecord).where(
                    ExplorationTaskRecord.state.not_in(_TERMINAL_TASK_STATES)
                )
            ).all()
            for record in records:
                record.state = "failed"
                record.phase = "interrupted"
                record.updated_at = occurred_at
                record.events_json = [
                    *record.events_json,
                    {
                        "event_type": "process_restarted",
                        "reason_code": "process_restarted",
                        "checkpoint_id": None,
                        "occurred_at": _utc_timestamp(occurred_at),
                    },
                ]
            return [record.task_id for record in records]

    def persist_task_summary(self, summary: TaskSummary) -> None:
        """Persist only the safe lifecycle index for a task that may still be running."""
        with session_scope(self._session_factory) as session:
            session.merge(task_record_from_summary(summary))

    def interrupt_nonterminal_comparisons(self, *, occurred_at: datetime) -> list[str]:
        """Fail stale comparison indexes without producing an access conclusion."""
        with session_scope(self._session_factory) as session:
            records = session.scalars(
                select(PermissionComparisonRecord).where(
                    PermissionComparisonRecord.state.not_in(_TERMINAL_TASK_STATES)
                )
            ).all()
            for record in records:
                record.state = "failed"
                record.updated_at = occurred_at
                record.identities_json = {
                    identity_id: "failed" for identity_id in record.identities_json
                }
                record.result_json = None
            return [record.comparison_id for record in records]

    def get_terminal_task_summary(self, task_id: str) -> TaskSummary | None:
        """Read one terminal public summary without exposing nonterminal runtime state."""
        session = self._session_factory()
        try:
            record = session.get(ExplorationTaskRecord, task_id)
            if record is None or record.state not in _TERMINAL_TASK_STATES:
                return None
            try:
                return task_summary_from_record(record)
            except PersistenceProjectionError:
                return None
        finally:
            session.close()

    def get_terminal_task_knowledge_source(
        self,
        task_id: str,
    ) -> TaskKnowledgeSource | None:
        """Rebuild one complete terminal task source from safe persisted projections."""
        session = self._session_factory()
        try:
            task_record = session.get(ExplorationTaskRecord, task_id)
            evidence_record = session.get(TaskEvidenceExportRecord, task_id)
            workflow_record = session.get(TaskWorkflowRecord, task_id)
            if (
                task_record is None
                or evidence_record is None
                or workflow_record is None
                or task_record.state not in _TERMINAL_TASK_STATES
            ):
                return None
            try:
                summary = task_summary_from_record(task_record)
                evidence_payload = task_evidence_payload_from_record(evidence_record)
                workflow = task_workflow_from_record(workflow_record)
            except PersistenceProjectionError:
                return None
            if (
                evidence_payload.export.task_id != summary.task_id
                or str(evidence_payload.export.state) != str(summary.state)
                or workflow.task_id != summary.task_id
                or workflow.state != str(summary.state)
            ):
                return None
            return TaskKnowledgeSource(
                source_id=summary.task_id,
                state=cast(
                    Literal["completed", "partial", "failed", "cancelled"],
                    str(summary.state),
                ),
                pages=[entry.page for entry in evidence_payload.pages],
                reason_codes=list(evidence_payload.export.reason_codes),
                workflow=workflow,
            )
        finally:
            session.close()

    def get_terminal_task_evidence_export(
        self,
        task_id: str,
    ) -> ExplorationEvidenceExport | None:
        """Read a schema-validated terminal evidence export without runtime state."""
        payload = self._get_terminal_task_evidence_payload(task_id)
        return payload.export if payload is not None else None

    def get_terminal_task_pages(self, task_id: str) -> list[TaskPageView] | None:
        """Read the bounded terminal page index from the safe evidence payload."""
        payload = self._get_terminal_task_evidence_payload(task_id)
        return list(payload.export.pages) if payload is not None else None

    def get_terminal_task_page_detail(
        self,
        task_id: str,
        page_id: str,
    ) -> PageEvidence | None:
        """Read one redacted page detail, never an underlying snapshot."""
        payload = self._get_terminal_task_evidence_payload(task_id)
        if payload is None:
            return None
        return next(
            (entry.page for entry in payload.pages if entry.page_id == page_id),
            None,
        )

    def get_terminal_task_workflow(
        self,
        task_id: str,
    ) -> TaskWorkflowExport | None:
        """Read a schema-validated readonly workflow for one terminal task."""
        session = self._session_factory()
        try:
            task_record = session.get(ExplorationTaskRecord, task_id)
            workflow_record = session.get(TaskWorkflowRecord, task_id)
            if (
                task_record is None
                or workflow_record is None
                or task_record.state not in _TERMINAL_TASK_STATES
            ):
                return None
            try:
                task_summary_from_record(task_record)
                workflow = task_workflow_from_record(workflow_record)
            except PersistenceProjectionError:
                return None
            return workflow if workflow.task_id == task_id else None
        finally:
            session.close()

    def get_terminal_comparison_view(
        self,
        comparison_id: str,
    ) -> PermissionComparisonView | None:
        """Read one complete terminal comparison without re-running any identity."""
        session = self._session_factory()
        try:
            record = session.get(PermissionComparisonRecord, comparison_id)
            if record is None or record.state not in _TERMINAL_TASK_STATES:
                return None
            try:
                return comparison_view_from_record(record)
            except PersistenceProjectionError:
                return None
        finally:
            session.close()

    def list_terminal_task_summaries(self) -> list[TaskSummary]:
        """List only complete, schema-valid public task projections."""
        session = self._session_factory()
        try:
            records = session.scalars(
                select(ExplorationTaskRecord)
                .where(ExplorationTaskRecord.state.in_(_TERMINAL_TASK_STATES))
                .order_by(ExplorationTaskRecord.task_id)
            ).all()
            summaries: list[TaskSummary] = []
            for record in records:
                if record.state not in _TERMINAL_TASK_STATES:
                    continue
                try:
                    summaries.append(task_summary_from_record(record))
                except PersistenceProjectionError:
                    continue
            return sorted(summaries, key=lambda summary: summary.task_id)
        finally:
            session.close()

    def list_terminal_comparison_views(self) -> list[PermissionComparisonView]:
        """List only complete, schema-valid persisted comparison projections."""
        session = self._session_factory()
        try:
            records = session.scalars(
                select(PermissionComparisonRecord)
                .where(PermissionComparisonRecord.state.in_(_TERMINAL_TASK_STATES))
                .order_by(PermissionComparisonRecord.comparison_id)
            ).all()
            views: list[PermissionComparisonView] = []
            for record in records:
                if record.state not in _TERMINAL_TASK_STATES:
                    continue
                try:
                    views.append(comparison_view_from_record(record))
                except PersistenceProjectionError:
                    continue
            return sorted(views, key=lambda view: view.comparison_id)
        finally:
            session.close()

    def _get_terminal_task_evidence_payload(
        self,
        task_id: str,
    ) -> TaskEvidencePersistencePayload | None:
        session = self._session_factory()
        try:
            task_record = session.get(ExplorationTaskRecord, task_id)
            evidence_record = session.get(TaskEvidenceExportRecord, task_id)
            if (
                task_record is None
                or evidence_record is None
                or task_record.state not in _TERMINAL_TASK_STATES
            ):
                return None
            try:
                task_summary_from_record(task_record)
                payload = task_evidence_payload_from_record(evidence_record)
            except PersistenceProjectionError:
                return None
            if (
                payload.export.task_id != task_id
                or str(payload.export.state) != task_record.state
            ):
                return None
            return payload
        finally:
            session.close()

    def persist_terminal_task(
        self,
        *,
        summary: TaskSummary,
        evidence: ExplorationEvidenceExport,
        workflow: TaskWorkflowExport,
        pages: list[PersistedTaskPageEvidence] | None = None,
    ) -> None:
        """Atomically persist one fully projected, terminal task result."""
        if (
            str(summary.state) not in _TERMINAL_TASK_STATES
            or evidence.task_id != summary.task_id
            or str(evidence.state) != str(summary.state)
            or workflow.task_id != summary.task_id
            or workflow.state != str(summary.state)
        ):
            raise PersistenceProjectionError("Persistence projection unavailable")
        try:
            evidence_payload = TaskEvidencePersistencePayload(
                export=evidence,
                pages=pages or [],
            )
        except ValidationError as error:
            raise PersistenceProjectionError("Persistence projection unavailable") from error
        with session_scope(self._session_factory) as session:
            session.merge(task_record_from_summary(summary))
            session.merge(
                TaskEvidenceExportRecord(
                    task_id=summary.task_id,
                    payload=evidence_payload.model_dump(mode="json"),
                    schema_version=evidence.schema_version,
                )
            )
            session.merge(
                TaskWorkflowRecord(
                    task_id=summary.task_id,
                    payload=workflow.model_dump(mode="json"),
                    schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
                )
            )
            session.merge(
                ExplorationKnowledgeSourceRecord(
                    source_id=summary.task_id,
                    source_kind="task",
                    state=str(summary.state),
                    updated_at=summary.updated_at,
                    schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
                )
            )

    def persist_terminal_comparison(
        self,
        *,
        view: PermissionComparisonView,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        """Atomically persist a terminal comparison and its export source index."""
        if view.result is None or view.state not in _TERMINAL_TASK_STATES:
            raise PersistenceProjectionError("Persistence projection unavailable")
        record = comparison_record_from_view(
            view,
            created_at=created_at,
            updated_at=updated_at,
        )
        with session_scope(self._session_factory) as session:
            session.merge(record)
            session.merge(
                ExplorationKnowledgeSourceRecord(
                    source_id=view.comparison_id,
                    source_kind="comparison",
                    state=view.state,
                    updated_at=updated_at,
                    schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
                )
            )

    def persist_comparison_view(
        self,
        *,
        view: PermissionComparisonView,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        """Persist a minimal comparison lifecycle index without a conclusion."""
        with session_scope(self._session_factory) as session:
            session.merge(
                PermissionComparisonRecord(
                    comparison_id=view.comparison_id,
                    state=view.state,
                    created_at=created_at,
                    updated_at=updated_at,
                    identities_json=view.identities,
                    result_json=None,
                    schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
                )
            )


def task_record_from_summary(summary: TaskSummary) -> ExplorationTaskRecord:
    """Project a public task summary into ORM fields without runtime handles."""
    return ExplorationTaskRecord(
        task_id=summary.task_id,
        state=str(summary.state),
        phase=summary.phase,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        redaction_count=summary.redaction_count,
        result_json=summary.result.model_dump(mode="json"),
        events_json=[event.model_dump(mode="json") for event in summary.events],
        schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
    )


def task_summary_from_record(record: ExplorationTaskRecord) -> TaskSummary:
    """Re-validate an untrusted database row before returning its public DTO."""
    if record.schema_version != _TASK_PROJECTION_SCHEMA_VERSION:
        raise PersistenceProjectionError("Persistence projection unavailable")
    try:
        return TaskSummary.model_validate(
            {
                "task_id": record.task_id,
                "state": record.state,
                "phase": record.phase,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "redaction_count": record.redaction_count,
                "events": record.events_json,
                "result": record.result_json,
            }
        )
    except ValidationError as error:
        raise PersistenceProjectionError("Persistence projection unavailable") from error


def task_evidence_payload_from_record(
    record: TaskEvidenceExportRecord,
) -> TaskEvidencePersistencePayload:
    """Decode and validate a stored evidence payload before it becomes a source."""
    if record.schema_version != _TASK_PROJECTION_SCHEMA_VERSION:
        raise PersistenceProjectionError("Persistence projection unavailable")
    try:
        return TaskEvidencePersistencePayload.model_validate(record.payload)
    except ValidationError as error:
        raise PersistenceProjectionError("Persistence projection unavailable") from error


def task_workflow_from_record(record: TaskWorkflowRecord) -> TaskWorkflowExport:
    """Decode and validate a stored readonly workflow projection."""
    if record.schema_version != _TASK_PROJECTION_SCHEMA_VERSION:
        raise PersistenceProjectionError("Persistence projection unavailable")
    try:
        return TaskWorkflowExport.model_validate(record.payload)
    except ValidationError as error:
        raise PersistenceProjectionError("Persistence projection unavailable") from error


def comparison_record_from_view(
    view: PermissionComparisonView,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> PermissionComparisonRecord:
    """Project a completed comparison without retaining runtime or login inputs."""
    if view.result is None:
        raise PersistenceProjectionError("Persistence projection unavailable")
    return PermissionComparisonRecord(
        comparison_id=view.comparison_id,
        state=view.state,
        created_at=created_at,
        updated_at=updated_at,
        identities_json=view.identities,
        result_json=view.result.model_dump(mode="json"),
        schema_version=_TASK_PROJECTION_SCHEMA_VERSION,
    )


def comparison_view_from_record(
    record: PermissionComparisonRecord,
) -> PermissionComparisonView:
    """Re-validate a terminal comparison row before exposing a conclusion."""
    if record.schema_version != _TASK_PROJECTION_SCHEMA_VERSION or record.result_json is None:
        raise PersistenceProjectionError("Persistence projection unavailable")
    try:
        return PermissionComparisonView.model_validate(
            {
                "comparison_id": record.comparison_id,
                "state": record.state,
                "identities": record.identities_json,
                "result": record.result_json,
            }
        )
    except ValidationError as error:
        raise PersistenceProjectionError("Persistence projection unavailable") from error


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
