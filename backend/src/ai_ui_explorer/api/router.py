from fastapi import APIRouter

from ai_ui_explorer.api.routes.exploration_knowledge import (
    router as exploration_knowledge_router,
)
from ai_ui_explorer.api.routes.exploration_tasks import router as exploration_tasks_router
from ai_ui_explorer.api.routes.health import router as health_router
from ai_ui_explorer.api.routes.permission_comparisons import (
    router as permission_comparisons_router,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(exploration_tasks_router)
api_router.include_router(permission_comparisons_router)
api_router.include_router(exploration_knowledge_router)
