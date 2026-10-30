from typing import Annotated

from fastapi import APIRouter, Depends, Request

from infrasight.ai.harness import AnalyticsHarness
from infrasight.ai.provider import GroqProvider
from infrasight.ai.schemas import QueryRequest, QueryResponse
from infrasight.analytics.services import AnalyticsService
from infrasight.sre.queries import SREQueries

router = APIRouter(prefix="/ai", tags=["AI Analyst"])


def harness(request: Request):
    settings = request.app.state.settings
    return AnalyticsHarness(
        GroqProvider(settings),
        AnalyticsService(request.app.state.engine, settings),
        settings,
        sre_queries=SREQueries(request.app.state.engine) if settings.sre_enabled else None,
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask Scout using approved read-only analytics or incident tools",
    description=(
        "Groq selects allowlisted tools; PostgreSQL-backed evidence accompanies the explanation. "
        "Incident scope is available only when SRE is enabled. No SQL or execution tools."
    ),
    responses={
        429: {"description": "Provider rate limit"},
        502: {"description": "Invalid provider/tool response"},
        504: {"description": "Provider or request timeout"},
    },
)
async def query(
    body: QueryRequest, request: Request, service: Annotated[AnalyticsHarness, Depends(harness)]
):
    return await service.query(body, request.state.request_id)
