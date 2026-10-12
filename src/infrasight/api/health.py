from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrasight.db.session import get_session

router = APIRouter(tags=["health"])
logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]
    service: str
    database: Literal["available", "unavailable"] | None = None


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", service=request.app.state.settings.app_name)


@router.get(
    "/health/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}}
)
def readiness(request: Request, session: Annotated[Session, Depends(get_session)]):
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning("database_not_ready", error_type=type(exc).__name__)
        response = HealthResponse(
            status="not_ready", service=request.app.state.settings.app_name, database="unavailable"
        )
        return JSONResponse(status_code=503, content=response.model_dump())
    return HealthResponse(
        status="ready", service=request.app.state.settings.app_name, database="available"
    )
