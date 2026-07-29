from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai_ui_explorer.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "ai-ui-explorer-backend"
    version: str = "0.1.0"
    environment: str


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(environment=settings.environment)
