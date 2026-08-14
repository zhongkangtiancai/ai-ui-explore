from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_ui_explorer.api.router import api_router
from ai_ui_explorer.api.routes.exploration_tasks import TaskApiError
from ai_ui_explorer.core.config import get_settings
from ai_ui_explorer.exploration.authentication import AuthenticationPlan
from ai_ui_explorer.exploration.collector_adapter import SnapshotCollectorAdapter
from ai_ui_explorer.exploration.login_runtime import HumanLoginSession
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget
from ai_ui_explorer.exploration.runner import (
    ExplorationCancellationToken,
    ExplorationRunner,
)
from ai_ui_explorer.exploration_knowledge.service import ExplorationKnowledgeExportService
from ai_ui_explorer.permission_comparison.service import PermissionComparisonService
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession, PlaywrightBrowserSource
from ai_ui_explorer.snapshot.collector import SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.task_management.registry import ExplorationTaskRegistry
from ai_ui_explorer.task_management.service import (
    ExplorationTaskService,
    _TaskRuntimeContext,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI UI Explorer", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    task_service = _create_task_service()
    app.state.exploration_task_service = task_service
    comparison_service = PermissionComparisonService(
        task_service=task_service
    )
    app.state.permission_comparison_service = comparison_service
    app.state.exploration_knowledge_export_service = ExplorationKnowledgeExportService(
        task_service=task_service,
        comparison_service=comparison_service,
    )
    app.include_router(api_router)

    @app.exception_handler(TaskApiError)
    async def handle_task_api_error(
        _request: Request,
        exception: TaskApiError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exception.status_code,
            content={
                "error": {
                    "code": exception.code,
                    "message": exception.message,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        _exception: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed",
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request,
        exception: StarletteHTTPException,
    ) -> JSONResponse:
        if exception.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "not_found",
                        "message": "Resource not found",
                    }
                },
            )
        return JSONResponse(
            status_code=exception.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": "Request failed",
                }
            },
        )

    return app


def _create_task_service() -> ExplorationTaskService:
    return ExplorationTaskService(
        registry=ExplorationTaskRegistry(),
        runtime_factory=_create_login_runtime,
        runner_factory=_create_runner,
        collector_factory=_create_snapshot_collector,
    )


def _create_login_runtime(
    context: _TaskRuntimeContext,
    plan: AuthenticationPlan,
    policy: NavigationPolicy,
) -> HumanLoginSession:
    browser = PlaywrightBrowserSession.open(headless=False)
    collector = context.create_session_collector(
        session=browser,
        limits=SnapshotLimits(),
    )
    return context.create_human_login_session(
        plan=plan,
        policy=policy,
        browser=browser,
        collector=collector,
    )


def _create_runner(
    context: _TaskRuntimeContext,
    policy: NavigationPolicy,
    budget: ExplorationBudget,
    collector: object,
    cancellation_token: ExplorationCancellationToken,
) -> ExplorationRunner:
    return context.create_runner(
        policy=policy,
        budget=budget,
        collector=collector,
        cancellation_token=cancellation_token,
    )


def _create_snapshot_collector(
    _context: _TaskRuntimeContext,
) -> SnapshotCollectorAdapter:
    return SnapshotCollectorAdapter(
        collector=SnapshotCollector(source=PlaywrightBrowserSource(headless=True)),
        limits=SnapshotLimits(),
    )


app = create_app()
