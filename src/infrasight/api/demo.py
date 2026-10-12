from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from infrasight.api.dependencies import result_response
from infrasight.api.operations import OperationsService
from infrasight.api.schemas import TriggerEnvelope

router = APIRouter(prefix="/demo", tags=["Demo Operations"])


class DemoETLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post(
    "/etl/run",
    response_model=TriggerEnvelope,
    response_model_exclude_unset=True,
    summary="Run one controlled simulator ingestion cycle",
    description="Read-key authorized; fixed simulator source; server-selected current UTC window "
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
