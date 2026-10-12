from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from infrasight.api.auth import require_admin
from infrasight.api.dependencies import result_response
from infrasight.api.operations import OperationsService
from infrasight.api.schemas import Envelope, RunParameters, TriggerEnvelope, TriggerRequest

router = APIRouter(prefix="/etl", tags=["ETL Operations"])
options = {"response_model": Envelope, "response_model_exclude_unset": True}


@router.get("/runs", summary="Paginated, sanitized ETL audit history", **options)
def runs(request: Request, params: Annotated[RunParameters, Query()]):
    return result_response(
        request,
        OperationsService(request.app.state.engine, request.app.state.settings).runs(params),
    )


@router.get("/runs/{run_id}", summary="ETL counters, window, and committed watermarks", **options)
def run(run_id: UUID, request: Request):
    return result_response(
        request, OperationsService(request.app.state.engine, request.app.state.settings).run(run_id)
    )


@router.post(
    "/run",
    summary="Execute one bounded ETL cycle synchronously",
    dependencies=[Depends(require_admin)],
    description=(
        "Requires both API keys. Returns HTTP 200 after completion; "
        "inspect status and error_code. No background queue."
    ),
    **{**options, "response_model": TriggerEnvelope},
)
def trigger(body: TriggerRequest, request: Request):
    return result_response(
        request,
        OperationsService(request.app.state.engine, request.app.state.settings).trigger(body),
    )
