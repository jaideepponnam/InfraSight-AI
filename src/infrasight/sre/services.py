"""Admin-driven, bounded incident lifecycle. No scheduler or process-local incident state."""

import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from infrasight.db.models.sre import (
    SREDemoRun,
    SREIncident,
    SREIncidentEvent,
    SREProbeResult,
    SRERecoveryAttempt,
)
from infrasight.sre.lifecycle import SREError
from infrasight.sre.probes import HTTPProbe
from infrasight.sre.recovery import clear_fault
from infrasight.sre.repository import (
    SRERepository,
    active_run,
    event,
    get_incident,
    token_hash,
    utcnow,
)
from infrasight.sre.rules import (
    ACTION,
    FAILURE_SAMPLES,
    HEALTHY_SAMPLES,
    POLICY_VERSION,
    SERVICE_KEY,
    consecutive,
)
from infrasight.sre.schemas import IncidentView, RecoveryView, RunView

MAX_PROBES = 24
MAX_RECOVERY_ATTEMPTS = 3


class SREService:
    def __init__(self, engine, settings, probe=None):
        self.repo = SRERepository(engine)
        self.settings = settings
        self.probe = probe or HTTPProbe(settings)

    def run_view(self, run_id):
        with self.repo.sessions() as session:
            run = session.get(SREDemoRun, run_id)
            if run is None:
                raise SREError("SRE_RUN_NOT_FOUND", 404)
            return RunView.model_validate(run)

    def _batch(self, run_id, token, phase, count, request_id, attempt_id=None):
        results = []
        for _ in range(count):
            # Check the deadline before network work; commit only within the same run ownership.
            with self.repo.sessions() as session:
                active_run(session, run_id)
            values = self.probe.observe(run_id, token)
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                if run.probe_token_hash != token_hash(token):
                    raise SREError("SRE_OPERATION_OWNERSHIP_LOST")
                total = session.scalar(
                    select(func.count())
                    .select_from(SREProbeResult)
                    .where(
                        SREProbeResult.run_id == run_id,
                    )
                )
                if total >= MAX_PROBES:
                    raise SREError("SRE_PROBE_LIMIT", 429)
                evidence = {**values.pop("evidence")}
                if attempt_id:
                    evidence["attempt_id"] = str(attempt_id)
                result = SREProbeResult(
                    id=uuid4(),
                    run_id=run_id,
                    phase=phase,
                    request_id=request_id,
                    evidence=evidence,
                    **values,
                )
                session.add(result)
                session.flush()
                results.append(result)
        return results

    def _detect(self, session, run, request_id):
        probes = list(
            session.scalars(
                select(SREProbeResult)
                .where(
                    SREProbeResult.run_id == run.id,
                    SREProbeResult.phase == "DETECTION",
                )
                .order_by(SREProbeResult.observed_at.desc(), SREProbeResult.id.desc())
                .limit(FAILURE_SAMPLES)
            )
        )[::-1]
        if not consecutive(probes, "HTTP_503", FAILURE_SAMPLES, utcnow()):
            raise SREError("SRE_EXPECTED_503_NOT_OBSERVED")
        fingerprint = f"{SERVICE_KEY}:http-503:{run.id}"
        existing = session.scalar(
            select(SREIncident).where(
                SREIncident.fingerprint == fingerprint,
                SREIncident.state != "RESOLVED",
            )
        )
        if existing:
            return existing
        incident = SREIncident(
            id=uuid4(),
            service_id=run.service_id,
            run_id=run.id,
            fingerprint=fingerprint,
            title="Controlled application-dependency failure (HTTP 503); not a storage outage",
            severity="SEV3",
            state="DETECTED",
            policy_version=POLICY_VERSION,
            detected_at=utcnow(),
            version=1,
        )
        session.add(incident)
        session.flush()
        session.add(
            SREIncidentEvent(
                incident_id=incident.id,
                sequence=1,
                event_type="DETECTED",
                actor="admin-exercise-runner",
                from_state=None,
                to_state="DETECTED",
                request_id=request_id,
                evidence={
                    "probe_ids": [str(p.id) for p in probes],
                    "policy_version": POLICY_VERSION,
                    "controlled_failure": True,
                    "storage_outage": False,
                },
            )
        )
        return incident

    def start(self, idempotency_key, request_id):
        self.repo.reconcile(request_id)
        token = secrets.token_urlsafe(32)
        with self.repo.locked(initialize=True) as (session, service):
            existing = session.scalar(
                select(SREDemoRun).where(
                    SREDemoRun.service_id == service.id,
                    SREDemoRun.idempotency_key == str(idempotency_key),
                )
            )
            if existing:
                return RunView.model_validate(existing)
            latest = session.scalar(
                select(SREDemoRun)
                .where(
                    SREDemoRun.service_id == service.id,
                )
                .order_by(SREDemoRun.created_at.desc())
                .limit(1)
            )
            if latest and latest.status == "ACTIVE":
                raise SREError("SRE_EXERCISE_BUSY")
            now = utcnow()
            if latest and now - latest.created_at < timedelta(
                seconds=self.settings.sre_cooldown_seconds
            ):
                raise SREError("SRE_COOLDOWN", 429)
            run = SREDemoRun(
                id=uuid4(),
                service_id=service.id,
                scenario="http-503",
                idempotency_key=str(idempotency_key),
                status="ACTIVE",
                phase="BASELINE",
                probe_token_hash=token_hash(token),
                fault_enabled=False,
                created_at=now,
                deadline_at=now + timedelta(seconds=self.settings.sre_run_deadline_seconds),
            )
            session.add(run)
            run_id = run.id
        try:
            baseline = self._batch(run_id, token, "BASELINE", 1, request_id)
            if not consecutive(baseline, "HEALTHY", 1, utcnow()):
                raise SREError("SRE_BASELINE_UNHEALTHY", 503)
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                run.fault_enabled = True
                run.fault_expires_at = run.deadline_at
                run.phase = "FAULT"
            self._batch(run_id, token, "DETECTION", FAILURE_SAMPLES, request_id)
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                self._detect(session, run, request_id)
                run.phase = "DETECTED"
        except Exception as exc:
            code = exc.code if isinstance(exc, SREError) else "SRE_EXECUTION_FAILED"
            with self.repo.locked() as (session, _service):
                run = session.get(SREDemoRun, run_id)
                if run.status == "ACTIVE":
                    run.status, run.phase, run.error_code = "FAILED", "COMPLETE", code
                    run.finished_at, run.fault_enabled, run.probe_token_hash = utcnow(), False, ""
            if not isinstance(exc, SREError):
                raise SREError("SRE_EXECUTION_FAILED", 503) from exc
            raise
        return self.run_view(run_id)

    def refresh_detection(self, run_id, request_id):
        self.repo.reconcile(request_id)
        token = secrets.token_urlsafe(32)
        with self.repo.locked() as (session, _service):
            run = active_run(session, run_id)
            if run.phase != "DETECTED":
                raise SREError("SRE_EXERCISE_BUSY")
            run.phase, run.probe_token_hash = "FAULT", token_hash(token)
        try:
            self._batch(run_id, token, "DETECTION", FAILURE_SAMPLES, request_id)
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                self._detect(session, run, request_id)
        finally:
            with self.repo.locked() as (session, _service):
                run = session.get(SREDemoRun, run_id)
                if run.status == "ACTIVE" and run.probe_token_hash == token_hash(token):
                    run.phase = "DETECTED"
        return self.run_view(run_id)

    def acknowledge(self, incident_id, request_id):
        self.repo.reconcile(request_id)
        with self.repo.locked() as (session, _service):
            incident = get_incident(session, incident_id)
            active_run(session, incident.run_id)
            if incident.state == "ACKNOWLEDGED":
                return IncidentView.model_validate(incident)
            event(session, incident, "ACKNOWLEDGED", "admin-key", request_id, target="ACKNOWLEDGED")
            incident.acknowledged_at = utcnow()
            session.flush()
            return IncidentView.model_validate(incident)

    def recover(self, incident_id, idempotency_key, request_id):
        self.repo.reconcile(request_id)
        token = secrets.token_urlsafe(32)
        with self.repo.locked() as (session, _service):
            incident = get_incident(session, incident_id)
            previous = session.scalar(
                select(SRERecoveryAttempt).where(
                    SRERecoveryAttempt.incident_id == incident_id,
                    SRERecoveryAttempt.idempotency_key == str(idempotency_key),
                )
            )
            if previous:
                return RecoveryView.model_validate(previous)
            run = active_run(session, incident.run_id)
            if run.phase != "DETECTED":
                raise SREError("SRE_EXERCISE_BUSY")
            if incident.state == "ACKNOWLEDGED":
                event(
                    session,
                    incident,
                    "INVESTIGATING",
                    "admin-key",
                    request_id,
                    target="INVESTIGATING",
                )
            if incident.state != "INVESTIGATING":
                raise SREError("SRE_ACKNOWLEDGEMENT_REQUIRED")
            count = session.scalar(
                select(func.count())
                .select_from(SRERecoveryAttempt)
                .where(
                    SRERecoveryAttempt.incident_id == incident_id,
                )
            )
            if count >= MAX_RECOVERY_ATTEMPTS:
                raise SREError("SRE_RECOVERY_LIMIT", 429)
            attempt = SRERecoveryAttempt(
                id=uuid4(),
                incident_id=incident_id,
                idempotency_key=str(idempotency_key),
                action=ACTION,
                status="RUNNING",
                action_applied=False,
                evidence={"policy_version": POLICY_VERSION},
                request_id=request_id,
            )
            session.add(attempt)
            run.phase, run.probe_token_hash = "RECOVERY", token_hash(token)
            run_id, attempt_id, needs_clear = run.id, attempt.id, run.fault_enabled
        try:
            # Always gather new diagnostics immediately before acting.
            before = self._batch(
                run_id,
                token,
                "DETECTION" if needs_clear else "VERIFICATION",
                FAILURE_SAMPLES,
                request_id,
                attempt_id,
            )
            expected = "HTTP_503" if needs_clear else "HEALTHY"
            if not consecutive(
                before, expected, FAILURE_SAMPLES, utcnow(), cleared=not needs_clear
            ):
                raise SREError("SRE_DIAGNOSTIC_PRECONDITION_FAILED")
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                incident = get_incident(session, incident_id)
                attempt = session.get(SRERecoveryAttempt, attempt_id)
                event(
                    session,
                    incident,
                    "MITIGATING",
                    "admin-key",
                    request_id,
                    {"probe_ids": [str(p.id) for p in before]},
                    "MITIGATING",
                )
                attempt.action_applied = clear_fault(run)
                event(
                    session,
                    incident,
                    "FAULT_CLEARED" if attempt.action_applied else "PRIOR_ACTION_REVERIFICATION",
                    "admin-key",
                    request_id,
                    {"attempt_id": str(attempt_id), "action_applied": attempt.action_applied},
                )
                event(session, incident, "VERIFYING", "admin-key", request_id, target="VERIFYING")
            after = self._batch(
                run_id,
                token,
                "VERIFICATION",
                HEALTHY_SAMPLES,
                request_id,
                attempt_id,
            )
            if not consecutive(after, "HEALTHY", HEALTHY_SAMPLES, utcnow(), cleared=True):
                raise SREError("SRE_RECOVERY_VERIFICATION_FAILED")
            with self.repo.locked() as (session, _service):
                run = active_run(session, run_id)
                incident = get_incident(session, incident_id)
                attempt = session.get(SRERecoveryAttempt, attempt_id)
                now = utcnow()
                event(
                    session,
                    incident,
                    "RESOLVED",
                    "admin-key",
                    request_id,
                    {"probe_ids": [str(p.id) for p in after], "attempt_id": str(attempt_id)},
                    "RESOLVED",
                )
                incident.resolved_at = now
                attempt.status, attempt.finished_at = "SUCCEEDED", now
                attempt.evidence = {
                    "policy_version": POLICY_VERSION,
                    "before_probe_ids": [str(p.id) for p in before],
                    "verification_probe_ids": [str(p.id) for p in after],
                    "verified_recovery": True,
                }
                run.status, run.phase, run.finished_at = "SUCCEEDED", "COMPLETE", now
                run.probe_token_hash = ""
        except Exception as exc:
            code = exc.code if isinstance(exc, SREError) else "SRE_EXECUTION_FAILED"
            with self.repo.locked() as (session, _service):
                incident = get_incident(session, incident_id)
                run = session.get(SREDemoRun, run_id)
                attempt = session.get(SRERecoveryAttempt, attempt_id)
                if attempt.status == "RUNNING":
                    attempt.status, attempt.error_code, attempt.finished_at = (
                        "FAILED",
                        code,
                        utcnow(),
                    )
                    target = (
                        "INVESTIGATING" if incident.state in {"MITIGATING", "VERIFYING"} else None
                    )
                    event(
                        session,
                        incident,
                        "RECOVERY_FAILED",
                        "admin-key",
                        request_id,
                        {
                            "attempt_id": str(attempt_id),
                            "error_code": code,
                            "verified_recovery": False,
                        },
                        target,
                    )
                    if run.status == "ACTIVE":
                        run.phase = "DETECTED"
            if not isinstance(exc, SREError):
                raise SREError("SRE_EXECUTION_FAILED", 503) from exc
            # Failed recovery is a completed auditable attempt, not a claimed resolution.
        with self.repo.sessions() as session:
            return RecoveryView.model_validate(session.get(SRERecoveryAttempt, attempt_id))
