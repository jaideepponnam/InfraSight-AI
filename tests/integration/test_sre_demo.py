"""Real TCP HTTP exercise against a temporary Uvicorn server and disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from infrasight.db.models.sre import (
    SREDemoRun,
    SREIncident,
    SREIncidentEvent,
    SREProbeResult,
    SRERecoveryAttempt,
)
from infrasight.sre.probes import HTTPProbe
from infrasight.sre.repository import SRERepository, utcnow
from infrasight.sre.services import SREService

pytestmark = pytest.mark.integration
READ = {"X-API-Key": "sre-integration-read"}
ADMIN = {**READ, "X-Admin-Key": "sre-integration-admin"}


def start(client, key=None):
    response = client.post(
        "/api/v1/sre/demo-runs",
        headers={
            **ADMIN,
            "Idempotency-Key": str(key or uuid4()),
        },
        json={"scenario": "http-503"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def incident(client, run_id):
    response = client.get("/api/v1/sre/incidents", headers=READ)
    assert response.status_code == 200
    return next(row for row in response.json()["data"] if row["run_id"] == str(run_id))


def acknowledge(client, incident_id):
    response = client.post(
        f"/api/v1/sre/incidents/{incident_id}/acknowledge", headers=ADMIN, json={}
    )
    assert response.status_code == 200, response.text


def recover(client, incident_id, key=None):
    response = client.post(
        f"/api/v1/sre/incidents/{incident_id}/recover",
        headers={
            **ADMIN,
            "Idempotency-Key": str(key or uuid4()),
        },
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_actual_http_full_lifecycle_and_evidence(sre_http, sre_engine):
    client, _settings = sre_http
    key = uuid4()
    run = start(client, key)
    assert run["phase"] == "DETECTED" and run["status"] == "ACTIVE"
    assert start(client, key)["id"] == run["id"]
    row = incident(client, run["id"])
    assert row["state"] == "DETECTED"
    assert "not a storage outage" in row["title"]
    assert (
        client.post(
            f"/api/v1/sre/incidents/{row['id']}/recover",
            headers={**ADMIN, "Idempotency-Key": str(uuid4())},
            json={},
        ).status_code
        == 409
    )
    acknowledge(client, row["id"])
    acknowledge(client, row["id"])
    recovery_key = uuid4()
    attempt = recover(client, row["id"], recovery_key)
    assert attempt["status"] == "SUCCEEDED" and attempt["action_applied"]
    assert recover(client, row["id"], recovery_key)["id"] == attempt["id"]
    assert incident(client, run["id"])["state"] == "RESOLVED"
    assert (
        client.get(f"/api/v1/sre/demo-runs/{run['id']}", headers=READ).json()["data"]["status"]
        == "SUCCEEDED"
    )
    evidence = client.get(f"/api/v1/sre/incidents/{row['id']}/evidence", headers=READ).json()
    probes = evidence["data"]["probes"]
    assert len(probes) == 10
    assert probes[0]["http_status"] == 200 and probes[0]["phase"] == "BASELINE"
    assert [p["http_status"] for p in probes[1:7]] == [503] * 6
    assert [p["http_status"] for p in probes[-3:]] == [200] * 3
    assert all(p["target_request_id"] and p["request_id"] for p in probes)
    assert all(float(p["duration_ms"]) >= 0 for p in probes)
    assert all(p["evidence"]["fault_state"] == "cleared" for p in probes[-3:])
    assert not any(
        secret in str(evidence)
        for secret in (
            "probe_token",
            "idempotency_key",
            ADMIN["X-Admin-Key"],
            READ["X-API-Key"],
        )
    )
    events = client.get(f"/api/v1/sre/incidents/{row['id']}/events", headers=READ).json()["data"]
    assert [e["to_state"] for e in events] == [
        "DETECTED",
        "ACKNOWLEDGED",
        "INVESTIGATING",
        "MITIGATING",
        "MITIGATING",
        "VERIFYING",
        "RESOLVED",
    ]
    assert [e["sequence"] for e in events] == list(range(1, 8))
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    with sre_engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(SRERecoveryAttempt)) == 1


def test_detection_refresh_deduplicates_and_reads_do_not_probe(sre_http, sre_engine):
    client, _ = sre_http
    run = start(client)
    row = incident(client, run["id"])
    for _ in range(2):
        assert (
            client.post(
                f"/api/v1/sre/demo-runs/{run['id']}/probe", headers=ADMIN, json={}
            ).status_code
            == 200
        )
        assert incident(client, run["id"])["id"] == row["id"]
    with sre_engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(SREIncident)) == 1
        assert db.scalar(select(func.count()).select_from(SREIncidentEvent)) == 1
        assert db.scalar(select(func.count()).select_from(SREProbeResult)) == 10
    assert client.get(f"/_sre-demo/{run['id']}/dependency").status_code == 404
    assert (
        client.get(
            f"/_sre-demo/{run['id']}/dependency", headers={"X-SRE-Probe": ADMIN["X-Admin-Key"]}
        ).status_code
        == 404
    )


def test_concurrent_exercise_and_recovery_are_idempotent(sre_http, sre_engine):
    client, settings = sre_http
    key = uuid4()

    def create(_):
        return SREService(sre_engine, settings).start(key, uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(create, range(2)))
    assert runs[0].id == runs[1].id
    row = incident(client, runs[0].id)
    acknowledge(client, row["id"])
    recovery_key = uuid4()

    def apply(_):
        return SREService(sre_engine, settings).recover(UUID(row["id"]), recovery_key, uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(apply, range(2)))
    assert attempts[0].id == attempts[1].id
    with sre_engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(SRERecoveryAttempt)) == 1
    assert incident(client, runs[0].id)["state"] == "RESOLVED"


def test_failed_verification_stays_open_and_new_request_can_reverify(sre_http, sre_engine):
    client, settings = sre_http
    run = start(client)
    row = incident(client, run["id"])
    acknowledge(client, row["id"])
    real = HTTPProbe(settings)

    class VerificationFailure:
        def observe(self, run_id, token):
            value = real.observe(run_id, token)
            if value["evidence"].get("fault_state") == "cleared":
                value["outcome"] = "TIMEOUT"
            return value

    failed = SREService(sre_engine, settings, VerificationFailure()).recover(
        UUID(row["id"]),
        uuid4(),
        uuid4(),
    )
    assert failed.status == "FAILED" and failed.action_applied
    assert failed.error_code == "SRE_RECOVERY_VERIFICATION_FAILED"
    assert incident(client, run["id"])["state"] == "INVESTIGATING"
    attempt = recover(client, row["id"])
    assert attempt["status"] == "SUCCEEDED" and not attempt["action_applied"]
    assert incident(client, run["id"])["state"] == "RESOLVED"


def test_expired_fault_is_not_credited_as_recovery(sre_http, sre_engine):
    client, _ = sre_http
    run = start(client)
    row = incident(client, run["id"])
    acknowledge(client, row["id"])
    with sre_engine.begin() as db:
        db.execute(
            update(SREDemoRun)
            .where(SREDemoRun.id == UUID(run["id"]))
            .values(
                fault_expires_at=utcnow() - timedelta(seconds=1),
            )
        )
    attempt = recover(client, row["id"])
    assert attempt["status"] == "FAILED" and not attempt["action_applied"]
    assert attempt["error_code"] == "SRE_DIAGNOSTIC_PRECONDITION_FAILED"
    assert incident(client, run["id"])["state"] == "INVESTIGATING"


def test_restart_reconciles_expired_run_without_background_worker(sre_http, sre_engine):
    client, settings = sre_http
    run = start(client)
    row = incident(client, run["id"])
    with sre_engine.begin() as db:
        old = utcnow() - timedelta(seconds=120)
        db.execute(
            update(SREDemoRun)
            .where(SREDemoRun.id == UUID(run["id"]))
            .values(
                created_at=old,
                deadline_at=old + timedelta(seconds=60),
                fault_expires_at=old + timedelta(seconds=60),
            )
        )
    # Reads remain read-only; the next admin operation performs reconciliation.
    assert (
        client.get(f"/api/v1/sre/demo-runs/{run['id']}", headers=READ).json()["data"]["status"]
        == "ACTIVE"
    )
    SREService(sre_engine, settings).repo.reconcile(uuid4())
    with SRERepository(sre_engine).sessions() as session:
        stored = session.get(SREDemoRun, UUID(run["id"]))
        assert stored.status == "INTERRUPTED" and not stored.fault_enabled
        assert stored.probe_token_hash == ""
    events = client.get(f"/api/v1/sre/incidents/{row['id']}/events", headers=READ).json()["data"]
    assert events[-1]["event_type"] == "RUN_INTERRUPTED"
    assert events[-1]["evidence"]["recovery_verified"] is False
    assert start(client)["id"] != run["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"scenario": "storage-outage"},
        {"url": "http://169.254.169.254"},
        {"command": "restart"},
        {"timeout": 999},
        {"scenario": "http-503", "duration": 500},
    ],
)
def test_client_cannot_select_target_or_fault_parameters(sre_http, body):
    client, _ = sre_http
    response = client.post(
        "/api/v1/sre/demo-runs",
        headers={
            **ADMIN,
            "Idempotency-Key": str(uuid4()),
        },
        json=body,
    )
    assert response.status_code == 422


def test_active_run_conflict_and_invalid_filters(sre_http):
    client, _ = sre_http
    start(client)
    response = client.post(
        "/api/v1/sre/demo-runs",
        headers={
            **ADMIN,
            "Idempotency-Key": str(uuid4()),
        },
        json={},
    )
    assert response.status_code == 409
    for query in ("limit=101", "offset=-1", "state=FAKE", "url=http://example.com"):
        assert client.get("/api/v1/sre/incidents?" + query, headers=READ).status_code == 422
    assert client.get(f"/api/v1/sre/incidents/{uuid4()}", headers=READ).status_code == 404
