"""Safe HTTP download routes for unified exploration knowledge packages."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from jsonschema import Draft202012Validator

from ai_ui_explorer.api.routes.exploration_tasks import TaskApiError
from ai_ui_explorer.exploration_knowledge.builder import (
    ExplorationKnowledgePackageTooLargeError,
)
from ai_ui_explorer.exploration_knowledge.models import ExplorationKnowledgePackageV2
from ai_ui_explorer.exploration_knowledge.service import (
    ExplorationKnowledgeExportError,
    ExplorationKnowledgeExportRequest,
    ExplorationKnowledgeExportService,
    ExplorationSourceView,
)

router = APIRouter(
    prefix="/exploration-knowledge-packages",
    tags=["exploration-knowledge-packages"],
)


def get_export_service(request: Request) -> ExplorationKnowledgeExportService:
    """Return the application's one process-local knowledge export service."""
    service = getattr(request.app.state, "exploration_knowledge_export_service", None)
    if not isinstance(service, ExplorationKnowledgeExportService):
        raise RuntimeError("Exploration knowledge export service is unavailable.")
    return service


@router.get("/sources", response_model=list[ExplorationSourceView])
def list_sources(
    service: Annotated[ExplorationKnowledgeExportService, Depends(get_export_service)],
) -> list[ExplorationSourceView]:
    """List terminal-only, safe sources available to this process."""
    return service.sources()


@router.post("/export")
def export_knowledge(
    payload: ExplorationKnowledgeExportRequest,
    service: Annotated[ExplorationKnowledgeExportService, Depends(get_export_service)],
) -> Response:
    """Create one schema-validated package without persisting it."""
    try:
        package = service.export(payload)
        return _knowledge_download_response(package)
    except ExplorationKnowledgeExportError:
        raise _source_not_found() from None
    except ExplorationKnowledgePackageTooLargeError:
        raise _knowledge_export_unavailable() from None
    except Exception:
        raise _knowledge_export_unavailable() from None


def _knowledge_download_response(package: ExplorationKnowledgePackageV2) -> Response:
    payload = package.model_dump(mode="json")
    Draft202012Validator(ExplorationKnowledgePackageV2.to_schema()).validate(payload)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                'attachment; filename="exploration-knowledge-package.json"'
            )
        },
    )


def _source_not_found() -> TaskApiError:
    return TaskApiError(
        status_code=404,
        code="source_not_found",
        message="Knowledge source not found",
    )


def _knowledge_export_unavailable() -> TaskApiError:
    return TaskApiError(
        status_code=409,
        code="knowledge_export_unavailable",
        message="Knowledge export is unavailable",
    )
