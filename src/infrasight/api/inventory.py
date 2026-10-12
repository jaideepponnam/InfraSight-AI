from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from infrasight.analytics.schemas import Scope
from infrasight.api.dependencies import result_response
from infrasight.api.operations import OperationsService
from infrasight.api.schemas import Envelope, InventoryParameters

router = APIRouter(prefix="/servers", tags=["Servers"])
options = {"response_model": Envelope, "response_model_exclude_unset": True}


@router.get("", summary="Paginated server inventory", **options)
def servers(request: Request, params: Annotated[InventoryParameters, Query()]):
    service = OperationsService(request.app.state.engine, request.app.state.settings)
    return result_response(request, service.servers(params))


@router.get(
    "/{server_id}", summary="Server metadata and latest freshness-aware telemetry", **options
)
def server(server_id: UUID, request: Request, params: Annotated[Scope, Query()]):
    service = OperationsService(request.app.state.engine, request.app.state.settings)
    return result_response(request, service.server(server_id, params))
