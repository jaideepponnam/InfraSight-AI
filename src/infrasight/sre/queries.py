"""Shared persisted reads. No reconciliation, HTTP probes, locks, or write service."""

from contextlib import contextmanager

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from infrasight.db.models.sre import (
    SREDemoRun,
    SREIncident,
    SREIncidentEvent,
    SREProbeResult,
    SRERecoveryAttempt,
)
from infrasight.sre.lifecycle import SREError
from infrasight.sre.schemas import (
    DiagnosticEvidence,
    EventView,
    IncidentView,
    ProbeView,
    RecoveryView,
    RunView,
)


class SREQueries:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def session(self):
        # The database enforces read-only even though the application's shared role
        # also supports admin operations. Each read gets an independent snapshot.
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                with Session(conn, autoflush=False) as session:
                    yield session

    def incidents(self, params):
        where = [] if params.state is None else [SREIncident.state == params.state]
        with self.session() as session:
            total = session.scalar(select(func.count()).select_from(SREIncident).where(*where))
            rows = session.scalars(
                select(SREIncident)
                .where(*where)
                .order_by(SREIncident.detected_at.desc(), SREIncident.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            ).all()
            return [IncidentView.model_validate(row) for row in rows], total

    @staticmethod
    def _incident(session, incident_id):
        row = session.get(SREIncident, incident_id)
        if row is None:
            raise SREError("SRE_INCIDENT_NOT_FOUND", 404)
        return IncidentView.model_validate(row)

    @staticmethod
    def _events(session, incident_id, limit=None):
        query = (
            select(SREIncidentEvent)
            .where(SREIncidentEvent.incident_id == incident_id)
            .order_by(SREIncidentEvent.sequence)
        )
        rows = session.scalars(query.limit(limit) if limit else query).all()
        return [EventView.model_validate(row) for row in rows]

    @staticmethod
    def _evidence(session, incident, bounded=False):
        probes = (
            select(SREProbeResult)
            .where(SREProbeResult.run_id == incident.run_id)
            .order_by(SREProbeResult.observed_at, SREProbeResult.id)
        )
        attempts = (
            select(SRERecoveryAttempt)
            .where(SRERecoveryAttempt.incident_id == incident.id)
            .order_by(SRERecoveryAttempt.started_at, SRERecoveryAttempt.id)
        )
        return DiagnosticEvidence(
            run=RunView.model_validate(session.get(SREDemoRun, incident.run_id)),
            probes=[
                ProbeView.model_validate(row)
                for row in session.scalars(probes.limit(25) if bounded else probes)
            ],
            recovery_attempts=[
                RecoveryView.model_validate(row)
                for row in session.scalars(attempts.limit(4) if bounded else attempts)
            ],
        )

    def incident(self, incident_id):
        with self.session() as session:
            return self._incident(session, incident_id)

    def events(self, incident_id):
        with self.session() as session:
            self._incident(session, incident_id)
            return self._events(session, incident_id)

    def evidence(self, incident_id):
        with self.session() as session:
            return self._evidence(session, self._incident(session, incident_id))

    def snapshot(self, incident_id):
        """Bounded, consistent investigation snapshot; never silently truncate proof."""
        with self.session() as session:
            incident = self._incident(session, incident_id)
            events = self._events(session, incident_id, 65)
            evidence = self._evidence(session, incident, bounded=True)
            if len(events) > 64 or len(evidence.probes) > 24 or len(evidence.recovery_attempts) > 3:
                raise SREError("SRE_EVIDENCE_LIMIT_EXCEEDED", 503)
            return incident, events, evidence
