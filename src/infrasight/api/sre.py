"""SRE reads use the public read key; every mutation also requires the admin key."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select

from infrasight.api.auth import require_admin
from infrasight.api.dependencies import sre_service
from infrasight.db.models.sre import (
    SREService,
)
from infrasight.sre.lifecycle import SREError
from infrasight.sre.queries import SREQueries
from infrasight.sre.schemas import (
    DiagnosticEvidence,
    EventView,
    ExerciseRequest,
    IncidentFilter,
    IncidentView,
    Metadata,
    RecoveryRequest,
    RecoveryView,
    RunView,
    ServiceView,
    SREEnvelope,
    StrictRequest,
)
from infrasight.sre.services import SREService as EngineService

router = APIRouter(prefix="/sre", tags=["SRE incidents"])
Service = Annotated[EngineService, Depends(sre_service)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


def read_service(request: Request):
    if not request.app.state.settings.sre_enabled:
        raise SREError("SRE_DISABLED", 503)
    return SREQueries(request.app.state.engine)


Reads = Annotated[SREQueries, Depends(read_service)]


def reject_query_parameters(request: Request):
    if request.query_params:
        raise SREError("SRE_PARAMETERS_NOT_ALLOWED", 422)


admin = [Depends(require_admin), Depends(reject_query_parameters)]


def envelope(request, data, **pagination):
    return {"data": data, "meta": Metadata(request_id=request.state.request_id, **pagination)}


@router.get("/services", response_model=SREEnvelope[list[ServiceView]])
def services(request: Request, service: Service):
    with service.repo.sessions() as session:
        rows = session.scalars(select(SREService).order_by(SREService.service_key)).all()
        return envelope(request, [ServiceView.model_validate(row) for row in rows])


@router.get("/incidents", response_model=SREEnvelope[list[IncidentView]])
def incidents(request: Request, service: Reads, params: Annotated[IncidentFilter, Query()]):
    rows, total = service.incidents(params)
    return envelope(request, rows, total=total, limit=params.limit, offset=params.offset)


@router.get("/incidents/{incident_id}", response_model=SREEnvelope[IncidentView])
def incident_detail(incident_id: UUID, request: Request, service: Reads):
    return envelope(request, service.incident(incident_id))


@router.get("/incidents/{incident_id}/events", response_model=SREEnvelope[list[EventView]])
def incident_events(incident_id: UUID, request: Request, service: Reads):
    return envelope(request, service.events(incident_id))


@router.get("/incidents/{incident_id}/evidence", response_model=SREEnvelope[DiagnosticEvidence])
def incident_evidence(incident_id: UUID, request: Request, service: Reads):
    return envelope(request, service.evidence(incident_id))


@router.get("/demo-runs/{run_id}", response_model=SREEnvelope[RunView])
def demo_run(run_id: UUID, request: Request, service: Service):
    return envelope(request, service.run_view(run_id))


@router.post("/demo-runs", dependencies=admin, response_model=SREEnvelope[RunView])
def start_exercise(body: ExerciseRequest, request: Request, service: Service, key: Key):
    """Admin-only baseline, controlled dependency fault, actual HTTP probes, and detection.
    Synchronous: returns after detection, not a background-job acknowledgement.
    """
    return envelope(request, service.start(key, UUID(request.state.request_id)))


@router.post("/demo-runs/{run_id}/probe", dependencies=admin, response_model=SREEnvelope[RunView])
def refresh_probes(run_id: UUID, body: StrictRequest, request: Request, service: Service):
    return envelope(request, service.refresh_detection(run_id, UUID(request.state.request_id)))


@router.post(
    "/incidents/{incident_id}/acknowledge",
    dependencies=admin,
    response_model=SREEnvelope[IncidentView],
)
def acknowledge(incident_id: UUID, body: StrictRequest, request: Request, service: Service):
    return envelope(request, service.acknowledge(incident_id, UUID(request.state.request_id)))


@router.post(
    "/incidents/{incident_id}/recover", dependencies=admin, response_model=SREEnvelope[RecoveryView]
)
def recover(incident_id: UUID, body: RecoveryRequest, request: Request, service: Service, key: Key):
    """Admin-only allowlisted action plus fresh HTTP verification. Inspect attempt status."""
    return envelope(request, service.recover(incident_id, key, UUID(request.state.request_id)))
