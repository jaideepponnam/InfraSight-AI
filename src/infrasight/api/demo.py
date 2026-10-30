from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from infrasight.api.auth import require_admin
from infrasight.api.dependencies import result_response
from infrasight.api.operations import OperationsService
from infrasight.api.schemas import TriggerEnvelope

router = APIRouter(prefix="/demo", tags=["Demo Operations"])


class DemoETLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post(
    "/etl/run",
    dependencies=[Depends(require_admin)],
    response_model=TriggerEnvelope,
    response_model_exclude_unset=True,
    summary="Run one controlled simulator ingestion cycle",
    description="Requires both read and admin API keys; fixed simulator source; current UTC window "
    "of at most 120 seconds. No client parameters. Synchronous result. Source lock "
    "prevents overlaps. General admin ETL authorization remains unchanged.",
)
def demo_etl(request: Request, body: Annotated[DemoETLRequest | None, Body()] = None):
    if request.query_params:
        raise HTTPException(422, "DEMO_PARAMETERS_NOT_ALLOWED")
    return result_response(
        request,
        OperationsService(request.app.state.engine, request.app.state.settings).demo_trigger(),
    )


@router.post(
    "/public-etl/run",
    response_model=TriggerEnvelope,
    response_model_exclude_unset=True,
    summary="Run the explicitly enabled public simulator demo",
    description="Requires the read API key and DEMO_PUBLIC_ETL_ENABLED. Only simulated-cloud "
    "and a server-selected window of at most 120 seconds are permitted. Synchronous result. "
    "The existing source lock prevents overlapping runs; there is no cooldown.",
)
def public_demo_etl(request: Request, body: Annotated[DemoETLRequest | None, Body()] = None):
    if not request.app.state.settings.demo_public_etl_enabled:
        raise HTTPException(503, "DEMO_PUBLIC_ETL_DISABLED")
    if request.query_params:
        raise HTTPException(422, "DEMO_PARAMETERS_NOT_ALLOWED")
    return result_response(
        request,
        OperationsService(request.app.state.engine, request.app.state.settings).demo_trigger(),
    )
