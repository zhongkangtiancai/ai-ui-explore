"""Safe HTTP routes for process-local controlled exploration tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ai_ui_explorer.exploration.authentication import AuthenticationPlan
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.task_management.models import (
    TaskEventView,
    TaskResultSummary,
    TaskSummary,
)
from ai_ui_explorer.task_management.service import (
    CreateExplorationTaskCommand,
    ExplorationTaskService,
    TaskServiceError,
)

router = APIRouter(prefix="/exploration-tasks", tags=["exploration-tasks"])


class TaskApiError(Exception):
    """A fixed HTTP error that cannot include runtime exception details."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class CreateExplorationTaskRequest(DeepFrozenModel):
    """Allowlisted task-creation fields, deliberately excluding credentials."""

    module_entry: ModuleEntry
    allowed_origins: list[str]
    authentication_origins: list[str] = []
    budget: ExplorationBudget
    authentication_plan: AuthenticationPlan | None = None
    allow_local_http: bool = False

    def to_command(self) -> CreateExplorationTaskCommand:
        return CreateExplorationTaskCommand(
            module_entry=self.module_entry,
            allowed_origins=list(self.allowed_origins),
            authentication_origins=list(self.authentication_origins),
            budget=self.budget,
            authentication_plan=self.authentication_plan,
            allow_local_http=self.allow_local_http,
        )


class TaskEventsResponse(DeepFrozenModel):
    events: list[TaskEventView]


class TaskOperationRequest(DeepFrozenModel):
    """An explicitly empty body for state-changing task operations."""


def get_task_service(request: Request) -> ExplorationTaskService:
    """Return the application's one process-local task service."""
    service = getattr(request.app.state, "exploration_task_service", None)
    if not isinstance(service, ExplorationTaskService):
        raise RuntimeError("Exploration task service is unavailable.")
    return service


@router.post("", status_code=202, response_model=TaskSummary)
def create_task(
    payload: CreateExplorationTaskRequest,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
) -> TaskSummary:
    try:
        return service.create(payload.to_command())
    except (TaskServiceError, ValueError):
        raise _invalid_request() from None


@router.get("/{task_id}", response_model=TaskSummary)
def get_task(
    task_id: str,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
) -> TaskSummary:
    return _require_summary(service, task_id)


@router.get("/{task_id}/events", response_model=TaskEventsResponse)
def get_task_events(
    task_id: str,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
) -> TaskEventsResponse:
    events = service.events(task_id)
    if events is None:
        raise _task_not_found()
    return TaskEventsResponse(events=events)


@router.post("/{task_id}/confirm-login", response_model=TaskSummary)
def confirm_login(
    task_id: str,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
    _payload: TaskOperationRequest | None = None,
) -> TaskSummary:
    _require_summary(service, task_id)
    try:
        return service.confirm_login(task_id)
    except TaskServiceError:
        raise _invalid_task_state() from None


@router.post("/{task_id}/cancel", response_model=TaskSummary)
def cancel_task(
    task_id: str,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
    _payload: TaskOperationRequest | None = None,
) -> TaskSummary:
    _require_summary(service, task_id)
    try:
        return service.cancel(task_id)
    except TaskServiceError:
        raise _invalid_task_state() from None


@router.get("/{task_id}/result", response_model=TaskResultSummary)
def get_task_result(
    task_id: str,
    service: Annotated[ExplorationTaskService, Depends(get_task_service)],
) -> TaskResultSummary:
    result = service.result(task_id)
    if result is None:
        raise _task_not_found()
    return result


def _require_summary(service: ExplorationTaskService, task_id: str) -> TaskSummary:
    summary = service.get(task_id)
    if summary is None:
        raise _task_not_found()
    return summary


def _task_not_found() -> TaskApiError:
    return TaskApiError(
        status_code=404,
        code="task_not_found",
        message="Task not found",
    )


def _invalid_task_state() -> TaskApiError:
    return TaskApiError(
        status_code=409,
        code="task_state_invalid",
        message="Task operation is not allowed",
    )


def _invalid_request() -> TaskApiError:
    return TaskApiError(
        status_code=422,
        code="invalid_request",
        message="Request validation failed",
    )
