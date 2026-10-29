"""SRE reads use the public read key; every mutation also requires the admin key."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select

from infrasight.api.auth import require_admin
from infrasight.api.dependencies import sre_service
from infrasight.db.models.sre import (
    SREDemoRun,
    SREIncident,
    SREIncidentEvent,
    SREProbeResult,
    SRERecoveryAttempt,
    SREService,
)
from infrasight.sre.lifecycle import SREError
from infrasight.sre.schemas import (
    EventView,
    ExerciseRequest,
    IncidentFilter,
    IncidentView,
    Metadata,
    ProbeView,
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
def incidents(request: Request, service: Service, params: Annotated[IncidentFilter, Query()]):
    where = [] if params.state is None else [SREIncident.state == params.state]
    with service.repo.sessions() as session:
        total = session.scalar(select(func.count()).select_from(SREIncident).where(*where))
        rows = session.scalars(
            select(SREIncident)
            .where(*where)
            .order_by(SREIncident.detected_at.desc(), SREIncident.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        ).all()
        return envelope(
            request,
            [IncidentView.model_validate(row) for row in rows],
            total=total,
            limit=params.limit,
            offset=params.offset,
        )


@router.get("/incidents/{incident_id}", response_model=SREEnvelope[IncidentView])
def incident_detail(incident_id: UUID, request: Request, service: Service):
    with service.repo.sessions() as session:
        row = session.get(SREIncident, incident_id)
        if row is None:
            raise SREError("SRE_INCIDENT_NOT_FOUND", 404)
        return envelope(request, IncidentView.model_validate(row))


@router.get("/incidents/{incident_id}/events", response_model=SREEnvelope[list[EventView]])
def incident_events(incident_id: UUID, request: Request, service: Service):
    with service.repo.sessions() as session:
        if session.get(SREIncident, incident_id) is None:
            raise SREError("SRE_INCIDENT_NOT_FOUND", 404)
        rows = session.scalars(
            select(SREIncidentEvent)
            .where(
                SREIncidentEvent.incident_id == incident_id,
            )
            .order_by(SREIncidentEvent.sequence)
        ).all()
        return envelope(request, [EventView.model_validate(row) for row in rows])


class DiagnosticEvidence(StrictRequest):
    run: RunView
    probes: list[ProbeView]
    recovery_attempts: list[RecoveryView]


@router.get("/incidents/{incident_id}/evidence", response_model=SREEnvelope[DiagnosticEvidence])
def incident_evidence(incident_id: UUID, request: Request, service: Service):
    with service.repo.sessions() as session:
        row = session.get(SREIncident, incident_id)
        if row is None:
            raise SREError("SRE_INCIDENT_NOT_FOUND", 404)
        probes = session.scalars(
            select(SREProbeResult)
            .where(
                SREProbeResult.run_id == row.run_id,
            )
            .order_by(SREProbeResult.observed_at, SREProbeResult.id)
        ).all()
        attempts = session.scalars(
            select(SRERecoveryAttempt)
            .where(
                SRERecoveryAttempt.incident_id == incident_id,
            )
            .order_by(SRERecoveryAttempt.started_at, SRERecoveryAttempt.id)
        ).all()
        return envelope(
            request,
            DiagnosticEvidence(
                run=RunView.model_validate(session.get(SREDemoRun, row.run_id)),
                probes=[ProbeView.model_validate(p) for p in probes],
                recovery_attempts=[RecoveryView.model_validate(a) for a in attempts],
            ),
        )


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
