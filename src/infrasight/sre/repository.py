"""Short database transactions; HTTP never runs while holding a connection."""

from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from infrasight.db.models.sre import (
    SREDemoRun,
    SREIncident,
    SREIncidentEvent,
    SRERecoveryAttempt,
    SREService,
)
from infrasight.sre.lifecycle import SREError, validate_transition
from infrasight.sre.rules import SERVICE_KEY


def utcnow():
    return datetime.now(UTC)


def token_hash(token):
    from hashlib import sha256

    return sha256(token.encode()).hexdigest()


def event(session, incident, event_type, actor, request_id, evidence=None, target=None):
    before = incident.state
    if target is not None:
        validate_transition(before, target)
        incident.state = target
    incident.version += 1
    session.add(
        SREIncidentEvent(
            incident_id=incident.id,
            sequence=incident.version,
            event_type=event_type,
            actor=actor,
            from_state=before,
            to_state=incident.state,
            request_id=request_id,
            evidence=evidence or {},
        )
    )


class SRERepository:
    def __init__(self, engine):
        self.sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def locked(self, *, initialize=False):
        with self.sessions.begin() as session:
            if initialize:
                session.execute(
                    insert(SREService)
                    .values(
                        service_key=SERVICE_KEY,
                        description="Controlled application-dependency HTTP 503 exercise; "
                        "not a storage outage.",
                    )
                    .on_conflict_do_nothing(constraint="uq_sre_services_key")
                )
            service = session.scalar(
                select(SREService).where(SREService.service_key == SERVICE_KEY).with_for_update()
            )
            if service is None:
                raise SREError("SRE_SERVICE_NOT_FOUND", 404)
            yield session, service

    def reconcile(self, request_id):
        # Admin operations call this explicitly; GET requests do not mutate state.
        with self.sessions() as session:
            exists = session.scalar(select(SREService.id).limit(1))
        if not exists:
            return
        with self.locked() as (session, service):
            now = utcnow()
            runs = session.scalars(
                select(SREDemoRun).where(
                    SREDemoRun.service_id == service.id,
                    SREDemoRun.status == "ACTIVE",
                    SREDemoRun.deadline_at <= now,
                )
            ).all()
            for run in runs:
                run.status, run.phase = "INTERRUPTED", "COMPLETE"
                run.error_code, run.finished_at = "SRE_RUN_EXPIRED", now
                run.fault_enabled, run.probe_token_hash = False, ""
                incident = session.scalar(
                    select(SREIncident).where(
                        SREIncident.run_id == run.id,
                        SREIncident.state != "RESOLVED",
                    )
                )
                if incident:
                    target = (
                        "INVESTIGATING" if incident.state in {"MITIGATING", "VERIFYING"} else None
                    )
                    event(
                        session,
                        incident,
                        "RUN_INTERRUPTED",
                        "system",
                        request_id,
                        {"reason": "deadline_expired", "recovery_verified": False},
                        target,
                    )
                    for attempt in session.scalars(
                        select(SRERecoveryAttempt).where(
                            SRERecoveryAttempt.incident_id == incident.id,
                            SRERecoveryAttempt.status == "RUNNING",
                        )
                    ):
                        attempt.status, attempt.finished_at = "INTERRUPTED", now
                        attempt.error_code = "SRE_RUN_EXPIRED"


def active_run(session, run_id):
    run = session.get(SREDemoRun, run_id)
    if run is None:
        raise SREError("SRE_RUN_NOT_FOUND", 404)
    if run.status != "ACTIVE" or run.deadline_at <= utcnow():
        raise SREError("SRE_RUN_NOT_ACTIVE")
    return run


def get_incident(session, incident_id):
    incident = session.get(SREIncident, incident_id)
    if incident is None:
        raise SREError("SRE_INCIDENT_NOT_FOUND", 404)
    return incident
