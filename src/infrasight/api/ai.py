from typing import Annotated

from fastapi import APIRouter, Depends, Request

from infrasight.ai.harness import AnalyticsHarness
from infrasight.ai.provider import GroqProvider
from infrasight.ai.schemas import QueryRequest, QueryResponse
from infrasight.analytics.services import AnalyticsService

router = APIRouter(prefix="/ai", tags=["AI Analyst"])


def harness(request: Request):
    settings = request.app.state.settings
    return AnalyticsHarness(
        GroqProvider(settings), AnalyticsService(request.app.state.engine, settings), settings
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask a natural-language question using approved read-only analytics tools",
    description=(
        "Groq selects a fixed analytics tool; PostgreSQL-backed evidence accompanies "
        "the explanation. No SQL or execution tools."
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
