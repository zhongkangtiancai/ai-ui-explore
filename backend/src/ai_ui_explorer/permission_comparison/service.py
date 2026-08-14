"""Process-local, serial orchestration for permission comparison runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

from pydantic import Field, model_validator

from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.exploration_knowledge.models import ComparisonKnowledgeSource
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.comparator import PermissionComparator
from ai_ui_explorer.permission_comparison.evidence import IdentityEvidenceCollector
from ai_ui_explorer.permission_comparison.models import (
    IdentityEvidenceBundle,
    IdentityProfile,
    IdentityRunState,
    PageEvidence,
    PermissionComparisonExport,
    PermissionComparisonResult,
    VisibilityDifference,
)
from ai_ui_explorer.task_management.models import TaskSummary
from ai_ui_explorer.task_management.service import (
    CreateExplorationTaskCommand,
    ExplorationTaskService,
)


class PermissionComparisonServiceError(RuntimeError):
    """Fixed, non-sensitive comparison service error surface."""


class CreatePermissionComparisonCommand(DeepFrozenModel):
    """One common bounded exploration configuration for two to five identities."""

    module_entry: ModuleEntry
    allowed_origins: list[str] = Field(min_length=1)
    authentication_origins: list[str] = Field(default_factory=list)
    budget: ExplorationBudget
    identities: list[IdentityProfile] = Field(min_length=2, max_length=5)
    allow_local_http: bool = False

    @model_validator(mode="after")
    def require_unique_identity_ids(self) -> CreatePermissionComparisonCommand:
        identity_ids = [identity.identity_id for identity in self.identities]
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("comparison identity IDs must be unique")
        return self


class PermissionComparisonView(DeepFrozenModel):
    """Safe progress view without task runtime handles or authentication plans."""

    comparison_id: str = Field(pattern=r"^comparison-[0-9]{1,20}$")
    state: str = Field(
        pattern=r"^(created|paused_for_human|collecting|completed|partial|cancelled)$"
    )
    identities: dict[str, str] = Field(min_length=2, max_length=5)
    result: PermissionComparisonResult | None = None


class _ChildTaskService(Protocol):
    def create(
        self,
        command: CreateExplorationTaskCommand,
        *,
        evidence_sink: IdentityEvidenceCollector,
        on_terminal: Callable[[TaskSummary], None],
    ) -> TaskSummary:
        """Create one identity task."""

    def get(self, task_id: str) -> TaskSummary | None:
        """Read the safe task state."""

    def confirm_login(self, task_id: str) -> TaskSummary:
        """Signal an explicit login confirmation."""

    def cancel(self, task_id: str) -> TaskSummary:
        """Cancel a running child task."""


@dataclass
class _IdentityExecution:
    profile: IdentityProfile
    collector: IdentityEvidenceCollector
    task_id: str | None = None
    state: str = "created"
    bundle: IdentityEvidenceBundle | None = None


@dataclass
class _ComparisonHandle:
    command: CreatePermissionComparisonCommand
    identities: dict[str, _IdentityExecution]
    next_identity_index: int = 0
    state: str = "created"
    result: PermissionComparisonResult | None = None
    cancelled: bool = False
    lock: RLock = field(default_factory=RLock)


class PermissionComparisonService:
    """Run identity tasks one-at-a-time and compare their bounded evidence."""

    def __init__(
        self,
        *,
        task_service: _ChildTaskService | ExplorationTaskService,
        comparator: PermissionComparator | None = None,
    ) -> None:
        self._task_service = task_service
        self._comparator = comparator or PermissionComparator()
        self._lock = RLock()
        self._comparisons: dict[str, _ComparisonHandle] = {}
        self._next_comparison_number = 1

    def create(
        self,
        command: CreatePermissionComparisonCommand,
    ) -> PermissionComparisonView:
        comparison_id = self._allocate_comparison_id()
        handle = _ComparisonHandle(
            command=command,
            identities={
                profile.identity_id: _IdentityExecution(
                    profile=profile,
                    collector=IdentityEvidenceCollector(identity_id=profile.identity_id),
                )
                for profile in command.identities
            },
        )
        with self._lock:
            self._comparisons[comparison_id] = handle
        self._start_next(comparison_id)
        return self.get(comparison_id)

    def get(self, comparison_id: str) -> PermissionComparisonView:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            return _view(comparison_id, handle)

    def list_views(self) -> list[PermissionComparisonView]:
        """List copied public comparison views in stable public-ID order."""
        with self._lock:
            comparison_ids = sorted(self._comparisons)
        return [self.get(comparison_id) for comparison_id in comparison_ids]

    def knowledge_source(
        self,
        comparison_id: str,
    ) -> ComparisonKnowledgeSource | None:
        """Return a terminal result projection without task or browser handles."""
        handle = self._require_handle(comparison_id)
        with handle.lock:
            result = handle.result
            if result is None or handle.state not in {
                "completed",
                "partial",
                "failed",
                "cancelled",
            }:
                return None
            return ComparisonKnowledgeSource(
                source_id=comparison_id,
                result=result.model_copy(deep=True),
                identity_labels={
                    identity_id: execution.profile.label
                    for identity_id, execution in handle.identities.items()
                },
            )

    def confirm_login(
        self,
        comparison_id: str,
        identity_id: str,
    ) -> PermissionComparisonView:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            execution = handle.identities.get(identity_id)
            if execution is None or execution.state != "paused_for_human":
                raise PermissionComparisonServiceError("Identity cannot confirm login.")
            task_id = execution.task_id
        if task_id is None:
            raise PermissionComparisonServiceError("Identity cannot confirm login.")
        self._task_service.confirm_login(task_id)
        return self.get(comparison_id)

    def cancel(self, comparison_id: str) -> PermissionComparisonView:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            if handle.state in {"completed", "partial", "cancelled"}:
                raise PermissionComparisonServiceError("Comparison cannot be cancelled.")
            handle.cancelled = True
            active = next(
                (
                    execution
                    for execution in handle.identities.values()
                    if execution.state in {"paused_for_human", "collecting"}
                ),
                None,
            )
            if active is None or active.task_id is None:
                handle.state = "cancelled"
                return _view(comparison_id, handle)
        self._task_service.cancel(active.task_id)
        return self.get(comparison_id)

    def pages(
        self,
        comparison_id: str,
        identity_id: str,
    ) -> list[PageEvidence]:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            bundle = _require_bundle(handle, identity_id)
            return list(bundle.pages)

    def page_detail(
        self,
        comparison_id: str,
        identity_id: str,
        page_key: str,
    ) -> PageEvidence:
        return next(
            page
            for page in self.pages(comparison_id, identity_id)
            if page.page_key == page_key
        )

    def differences(self, comparison_id: str) -> list[VisibilityDifference]:
        result = self.get(comparison_id).result
        return list(result.differences) if result is not None else []

    def export(self, comparison_id: str) -> PermissionComparisonExport:
        result = self.get(comparison_id).result
        if result is None:
            raise PermissionComparisonServiceError("Comparison is not complete.")
        return PermissionComparisonExport(**result.model_dump(mode="json"))

    def _start_next(self, comparison_id: str) -> None:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            if handle.cancelled:
                handle.state = "cancelled"
                return
            ordered = list(handle.identities.values())
            if handle.next_identity_index >= len(ordered):
                self._finalize(comparison_id, handle)
                return
            execution = ordered[handle.next_identity_index]
            handle.next_identity_index += 1
            command = CreateExplorationTaskCommand(
                module_entry=handle.command.module_entry,
                allowed_origins=handle.command.allowed_origins,
                authentication_origins=handle.command.authentication_origins,
                budget=handle.command.budget,
                authentication_plan=execution.profile.authentication_plan,
                allow_local_http=handle.command.allow_local_http,
            )

            def on_terminal(summary: TaskSummary) -> None:
                self._handle_identity_terminal(
                    comparison_id,
                    execution.profile.identity_id,
                    summary,
                )

            summary = self._task_service.create(
                command,
                evidence_sink=execution.collector,
                on_terminal=on_terminal,
            )
            execution.task_id = summary.task_id
            execution.state = str(summary.state)
            handle.state = execution.state

    def _handle_identity_terminal(
        self,
        comparison_id: str,
        identity_id: str,
        summary: TaskSummary,
    ) -> None:
        handle = self._require_handle(comparison_id)
        with handle.lock:
            execution = handle.identities[identity_id]
            execution.state = str(summary.state)
            execution.bundle = execution.collector.bundle(state=execution.state)
            if handle.cancelled:
                handle.state = "cancelled"
                return
        self._start_next(comparison_id)

    def _finalize(self, comparison_id: str, handle: _ComparisonHandle) -> None:
        bundles = [
            execution.bundle
            or execution.collector.bundle(state=execution.state)
            for execution in handle.identities.values()
        ]
        result = self._comparator.compare(bundles)
        if any(bundle.state != IdentityRunState.COMPLETED for bundle in bundles):
            result = result.model_copy(update={"status": "partial"})
        handle.result = result
        handle.state = result.status

    def _require_handle(self, comparison_id: str) -> _ComparisonHandle:
        with self._lock:
            handle = self._comparisons.get(comparison_id)
        if handle is None:
            raise PermissionComparisonServiceError("Comparison was not found.")
        return handle

    def _allocate_comparison_id(self) -> str:
        with self._lock:
            comparison_id = f"comparison-{self._next_comparison_number}"
            self._next_comparison_number += 1
            return comparison_id


def _view(comparison_id: str, handle: _ComparisonHandle) -> PermissionComparisonView:
    return PermissionComparisonView(
        comparison_id=comparison_id,
        state=handle.state,
        identities={
            identity_id: execution.state
            for identity_id, execution in handle.identities.items()
        },
        result=handle.result,
    )


def _require_bundle(
    handle: _ComparisonHandle,
    identity_id: str,
) -> IdentityEvidenceBundle:
    execution = handle.identities.get(identity_id)
    if execution is None or execution.bundle is None:
        raise PermissionComparisonServiceError("Identity evidence is not available.")
    return execution.bundle
