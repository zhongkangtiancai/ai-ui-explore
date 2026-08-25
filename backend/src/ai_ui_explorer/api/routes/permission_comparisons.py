"""Allowlisted HTTP routes for process-local permission comparisons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from jsonschema import Draft202012Validator

from ai_ui_explorer.api.routes.exploration_tasks import TaskApiError
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import (
    PageEvidence,
    PermissionComparisonExport,
    VisibilityDifference,
)
from ai_ui_explorer.permission_comparison.service import (
    CreatePermissionComparisonCommand,
    PermissionComparisonService,
    PermissionComparisonServiceError,
    PermissionComparisonView,
)

router = APIRouter(prefix="/permission-comparisons", tags=["permission-comparisons"])


class _PermissionComparisonPort(Protocol):
    def create(
        self,
        command: CreatePermissionComparisonCommand,
    ) -> PermissionComparisonView:
        """Create one comparison."""

    def get(self, comparison_id: str) -> PermissionComparisonView:
        """Read a safe comparison view."""

    def pages(self, comparison_id: str, identity_id: str) -> list[PageEvidence]:
        """Read one identity's projected pages."""

    def page_detail(
        self,
        comparison_id: str,
        identity_id: str,
        page_key: str,
    ) -> PageEvidence:
        """Read one projected page."""

    def differences(self, comparison_id: str) -> list[VisibilityDifference]:
        """Read safe differences."""

    def export(self, comparison_id: str) -> PermissionComparisonExport:
        """Build the versioned export."""

    def confirm_login(
        self,
        comparison_id: str,
        identity_id: str,
    ) -> PermissionComparisonView:
        """Signal an explicit confirmation."""

    def cancel(self, comparison_id: str) -> PermissionComparisonView:
        """Cancel the current comparison."""


class CreatePermissionComparisonRequest(DeepFrozenModel):
    """Allowlisted request fields; credentials cannot be supplied here."""

    module_entry: object
    allowed_origins: list[str]
    authentication_origins: list[str] = []
    budget: object
    identities: object
    allow_local_http: bool = False

    def to_command(self) -> CreatePermissionComparisonCommand:
        return CreatePermissionComparisonCommand.model_validate(
            self.model_dump(mode="python")
        )


class ComparisonOperationRequest(DeepFrozenModel):
    """An explicitly empty body for comparison operations."""


def get_permission_comparison_service(request: Request) -> _PermissionComparisonPort:
    """Return the app's one process-local comparison service."""
    service = getattr(request.app.state, "permission_comparison_service", None)
    if isinstance(service, PermissionComparisonService):
        return service
    raise RuntimeError("Permission comparison service is unavailable.")


@router.post("", status_code=202, response_model=PermissionComparisonView)
def create_permission_comparison(
    payload: CreatePermissionComparisonRequest,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> PermissionComparisonView:
    try:
        return service.create(payload.to_command())
    except (PermissionComparisonServiceError, ValueError):
        raise _invalid_request() from None


@router.get("/{comparison_id}", response_model=PermissionComparisonView)
def get_permission_comparison(
    comparison_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> PermissionComparisonView:
    return _get_comparison(service, comparison_id)


@router.get(
    "/{comparison_id}/identities/{identity_id}/pages",
    response_model=list[PageEvidence],
)
def get_identity_pages(
    comparison_id: str,
    identity_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> list[PageEvidence]:
    try:
        return service.pages(comparison_id, identity_id)
    except (PermissionComparisonServiceError, StopIteration):
        raise _not_found() from None


@router.get("/{comparison_id}/pages/{page_key:path}", response_model=PageEvidence)
def get_identity_page(
    comparison_id: str,
    page_key: str,
    identity_id: Annotated[str, Query(min_length=1, max_length=32)],
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> PageEvidence:
    try:
        return service.page_detail(comparison_id, identity_id, page_key)
    except (PermissionComparisonServiceError, StopIteration):
        raise _not_found() from None


@router.get("/{comparison_id}/differences", response_model=list[VisibilityDifference])
def get_differences(
    comparison_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> list[VisibilityDifference]:
    try:
        return service.differences(comparison_id)
    except PermissionComparisonServiceError:
        raise _not_found() from None


@router.get("/{comparison_id}/export")
def export_permission_comparison(
    comparison_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
) -> Response:
    try:
        export = service.export(comparison_id)
    except PermissionComparisonServiceError:
        raise _invalid_state() from None
    payload = export.model_dump(mode="json")
    Draft202012Validator(_export_schema()).validate(payload)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="permission-comparison.json"'
        },
    )


@router.post(
    "/{comparison_id}/identities/{identity_id}/confirm-login",
    response_model=PermissionComparisonView,
)
def confirm_identity_login(
    comparison_id: str,
    identity_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
    _payload: ComparisonOperationRequest | None = None,
) -> PermissionComparisonView:
    try:
        return service.confirm_login(comparison_id, identity_id)
    except PermissionComparisonServiceError:
        raise _invalid_state() from None


@router.post("/{comparison_id}/cancel", response_model=PermissionComparisonView)
def cancel_permission_comparison(
    comparison_id: str,
    service: Annotated[_PermissionComparisonPort, Depends(get_permission_comparison_service)],
    _payload: ComparisonOperationRequest | None = None,
) -> PermissionComparisonView:
    try:
        return service.cancel(comparison_id)
    except PermissionComparisonServiceError:
        raise _invalid_state() from None


def _get_comparison(
    service: _PermissionComparisonPort,
    comparison_id: str,
) -> PermissionComparisonView:
    try:
        return service.get(comparison_id)
    except PermissionComparisonServiceError:
        raise _not_found() from None


def _export_schema() -> dict[str, object]:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "permission_comparison"
        / "schema"
        / "permission-comparison-v1.schema.json"
    )
    return cast(
        dict[str, object],
        json.loads(schema_path.read_text(encoding="utf-8")),
    )


def _not_found() -> TaskApiError:
    return TaskApiError(
        status_code=404,
        code="comparison_not_found",
        message="Comparison not found",
    )


def _invalid_state() -> TaskApiError:
    return TaskApiError(
        status_code=409,
        code="comparison_state_invalid",
        message="Comparison operation is not allowed",
    )


def _invalid_request() -> TaskApiError:
    return TaskApiError(
        status_code=422,
        code="invalid_request",
        message="Request validation failed",
    )
