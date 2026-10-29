"""Database concurrency, interruption and rollback checks supplement real HTTP tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from test_sre_demo import acknowledge, incident, start

from infrasight.db.models.sre import SREDemoRun, SREIncident, SREProbeResult, SRERecoveryAttempt
from infrasight.sre.lifecycle import SREError
from infrasight.sre.repository import active_run, utcnow
from infrasight.sre.services import SREService

pytestmark = pytest.mark.integration


def test_concurrent_detection_is_one_incident(sre_http, sre_engine):
    client, settings = sre_http
    run = start(client)
    service = SREService(sre_engine, settings)

    def detect(_):
        with service.repo.locked() as (session, _):
            row = service._detect(session, active_run(session, UUID(run["id"])), uuid4())
            return row.id

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(detect, range(3)))
    assert len(set(ids)) == 1
    with sre_engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(SREIncident)) == 1


def test_recovery_error_rolls_back_action_and_preserves_attempt(sre_http, sre_engine, monkeypatch):
    client, settings = sre_http
    run = start(client)
    row = incident(client, run["id"])
    acknowledge(client, row["id"])

    def broken(target):
        target.fault_enabled = False
        raise RuntimeError("private-database-password")

    monkeypatch.setattr("infrasight.sre.services.clear_fault", broken)
    with pytest.raises(SREError, match="SRE_EXECUTION_FAILED"):
        SREService(sre_engine, settings).recover(UUID(row["id"]), uuid4(), uuid4())
    with SREService(sre_engine, settings).repo.sessions() as session:
        assert session.get(SREDemoRun, UUID(run["id"])).fault_enabled
        assert session.get(SREIncident, UUID(row["id"])).state == "INVESTIGATING"
        attempt = session.scalar(select(SRERecoveryAttempt))
        assert attempt.status == "FAILED" and not attempt.action_applied
        assert "private" not in str(attempt.evidence)


def test_reconcile_interrupted_verification_is_not_resolution(sre_http, sre_engine):
    client, settings = sre_http
    run = start(client)
    row = incident(client, run["id"])
    acknowledge(client, row["id"])
    service = SREService(sre_engine, settings)
    with service.repo.locked() as (session, _):
        stored = session.get(SREDemoRun, UUID(run["id"]))
        old = utcnow() - timedelta(seconds=120)
        stored.created_at, stored.deadline_at = old, old + timedelta(seconds=60)
        stored.fault_expires_at, stored.phase = stored.deadline_at, "RECOVERY"
        stored_incident = session.get(SREIncident, UUID(row["id"]))
        stored_incident.state = "VERIFYING"
        session.add(
            SRERecoveryAttempt(
                incident_id=stored_incident.id,
                idempotency_key=str(uuid4()),
                action="clear-controlled-dependency-fault",
                status="RUNNING",
                action_applied=True,
                evidence={},
                request_id=uuid4(),
            )
        )
    service.repo.reconcile(uuid4())
    with service.repo.sessions() as session:
        assert session.get(SREIncident, UUID(row["id"])).state == "INVESTIGATING"
        assert session.scalar(select(SRERecoveryAttempt)).status == "INTERRUPTED"


def test_database_rejects_invalid_probe_and_duplicate_active_incident(sre_http, sre_engine):
    client, _ = sre_http
    start(client)
    with sre_engine.begin() as db:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(update(SREProbeResult).values(duration_ms=-1))
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(update(SREDemoRun).values(scenario="storage-outage"))
        existing = db.execute(select(SREIncident.__table__)).mappings().one()
        duplicate = {**dict(existing), "id": uuid4()}
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(SREIncident.__table__.insert().values(**duplicate))


def test_probe_budget_cannot_be_bypassed_with_repeated_refresh(sre_http, sre_engine):
    client, _ = sre_http
    run = start(client)
    statuses = [
        client.post(
            f"/api/v1/sre/demo-runs/{run['id']}/probe",
            headers={
                "X-API-Key": "sre-integration-read",
                "X-Admin-Key": "sre-integration-admin",
            },
            json={},
        ).status_code
        for _ in range(8)
    ]
    assert 429 in statuses
    with sre_engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(SREProbeResult)) == 24
