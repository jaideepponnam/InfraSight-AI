from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from infrasight.api import operations
from infrasight.ingestion.errors import SourceBusyError
from infrasight.ingestion.schemas import RunCounts, RunResult
from infrasight.main import create_app

READ = {"X-API-Key": "demo-read-test"}
ADMIN = {**READ, "X-Admin-Key": "admin-test-only"}


@pytest.fixture
def demo_app(settings, monkeypatch):
    settings.api_read_key = SecretStr("demo-read-test")
    settings.api_admin_key = SecretStr("admin-test-only")
    pipeline = Mock()

    def cycle(source, start, end):
        return RunResult(
            uuid4(),
            source.source_id,
            "SUCCEEDED",
            start,
            end,
            RunCounts(300, 297, 297, 0, 3),
            None,
            end,
        )

    pipeline.run_cycle.side_effect = cycle
    constructor = Mock(return_value=pipeline)
    monkeypatch.setattr(operations, "ETLPipeline", constructor)
    host = Mock(side_effect=AssertionError("Host source must never be constructed"))
    monkeypatch.setattr(operations, "HostMetricsSource", host)
    return create_app(settings), pipeline, constructor, host


def test_demo_admin_keys_fixed_simulator_window(demo_app, settings):
    app, pipeline, constructor, host = demo_app
    before = datetime.now(UTC)
    with TestClient(app) as client:
        response = client.post("/api/v1/demo/etl/run", headers=ADMIN, json={})
    after = datetime.now(UTC)
    assert response.status_code == 200
    source, start, end = pipeline.run_cycle.call_args.args
    assert source.source_id == "simulated-cloud"
    assert start.tzinfo == UTC and end.tzinfo == UTC
    assert 0 < (end - start).total_seconds() <= 120
    assert end <= after
    assert (before - end).total_seconds() < settings.telemetry_interval_seconds + 1
    assert source.completed_until(start) == start
    assert source.completed_until(end) == end
    assert constructor.call_args.args[1].simulator_seed == settings.simulator_seed
    assert constructor.call_args.args[1].simulator_server_count == settings.simulator_server_count
    assert response.json()["data"]["counts"] == dict(
        extracted=300, accepted=297, inserted=297, duplicated=0, rejected=3
    )
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
    host.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        READ,
        {"X-API-Key": "wrong"},
        {"X-Admin-Key": "admin-test-only"},
        {**ADMIN, "X-API-Key": "wrong"},
        {**READ, "X-Admin-Key": "wrong"},
    ],
)
def test_demo_auth(demo_app, headers):
    app, pipeline, constructor, host = demo_app
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/etl/run", headers=headers, json={}).status_code == 401
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()
    host.assert_not_called()


def test_demo_unconfigured_admin_fails_closed(demo_app, settings):
    app, pipeline, constructor, host = demo_app
    settings.api_admin_key = None
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/etl/run", headers=READ, json={}).status_code == 503
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()
    host.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"source": "host"},
        {"source_id": "other"},
        {"duration": 86400},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
        {"server_count": 10000},
        {"seed": 123},
        {"sql": "DROP TABLE servers"},
    ],
)
def test_demo_rejects_client_parameters(demo_app, body):
    app, pipeline, _, _ = demo_app
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/etl/run", headers=ADMIN, json=body).status_code == 422
        assert client.post("/api/v1/demo/etl/run?source=host", headers=ADMIN).status_code == 422
    pipeline.run_cycle.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    [
        (SourceBusyError("private-lock-detail"), 409),
        (OperationalError("private-sql", {}, Exception("private-db-error")), 503),
    ],
)
def test_demo_safe_failures(demo_app, error, status):
    app, pipeline, _, _ = demo_app
    pipeline.run_cycle.side_effect = error
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/demo/etl/run", headers=ADMIN)
    assert response.status_code == status
    assert "private" not in response.text


def test_demo_invalid_interval_fails_closed(demo_app, settings):
    app, pipeline, _, _ = demo_app
    settings.telemetry_interval_seconds = 180
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/etl/run", headers=ADMIN).status_code == 503
    pipeline.run_cycle.assert_not_called()


def test_demo_failed_run_is_auditable(demo_app):
    app, pipeline, _, _ = demo_app

    def failed(source, start, end):
        return RunResult(
            uuid4(),
            source.source_id,
            "FAILED",
            start,
            end,
            RunCounts(),
            None,
            None,
            "DATABASE_ERROR",
        )

    pipeline.run_cycle.side_effect = failed
    with TestClient(app) as client:
        response = client.post("/api/v1/demo/etl/run", headers=ADMIN)
        assert (
            client.post(
                "/api/v1/etl/run", headers={"X-API-Key": "demo-read-test"}, json={}
            ).status_code
            == 401
        )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "FAILED"


PUBLIC_ETL = "/api/v1/demo/public-etl/run"


@pytest.fixture
def public_demo_app(demo_app, settings):
    settings.demo_public_etl_enabled = True
    return demo_app


def test_public_demo_is_disabled_without_explicit_enablement(demo_app, settings):
    app, pipeline, constructor, host = demo_app
    settings.demo_public_etl_enabled = False
    with TestClient(app) as client:
        response = client.post(PUBLIC_ETL, headers=READ, json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEMO_PUBLIC_ETL_DISABLED"
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()
    host.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "wrong"},
        {"X-Admin-Key": "admin-test-only"},
        {**ADMIN, "X-API-Key": "wrong"},
    ],
)
def test_public_demo_requires_the_read_key(public_demo_app, headers):
    app, pipeline, constructor, host = public_demo_app
    with TestClient(app) as client:
        assert client.post(PUBLIC_ETL, headers=headers, json={}).status_code == 401
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()
    host.assert_not_called()


def test_public_demo_unconfigured_read_key_fails_closed(public_demo_app, settings):
    app, pipeline, constructor, _ = public_demo_app
    settings.api_read_key = None
    with TestClient(app) as client:
        assert client.post(PUBLIC_ETL, headers=READ, json={}).status_code == 503
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()


@pytest.mark.parametrize("request_options", [{}, {"json": {}}])
def test_public_demo_uses_the_unchanged_bounded_simulator(
    public_demo_app, settings, request_options
):
    app, pipeline, constructor, host = public_demo_app
    before = datetime.now(UTC)
    with TestClient(app) as client:
        response = client.post(PUBLIC_ETL, headers=READ, **request_options)
    after = datetime.now(UTC)
    assert response.status_code == 200
    source, start, end = pipeline.run_cycle.call_args.args
    assert source.source_id == "simulated-cloud" and source.provider == "simulated"
    assert source.server_count == settings.simulator_server_count
    assert source.seed == settings.simulator_seed
    assert source.malformed_rate == settings.simulator_malformed_rate
    assert source.interval_seconds == settings.telemetry_interval_seconds
    assert 0 < (end - start).total_seconds() <= 120
    assert start.tzinfo == UTC and end.tzinfo == UTC
    assert end <= after and (before - end).total_seconds() < settings.telemetry_interval_seconds + 1
    assert source.completed_until(start) == start and source.completed_until(end) == end
    assert (
        constructor.call_args.args[1].etl_max_window_seconds <= settings.etl_api_max_window_seconds
    )
    assert response.json()["data"]["counts"] == dict(
        extracted=300, accepted=297, inserted=297, duplicated=0, rejected=3
    )
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
    host.assert_not_called()


def test_public_demo_allows_immediate_sequential_runs(public_demo_app, settings):
    app, pipeline, _, _ = public_demo_app
    settings.sre_cooldown_seconds = 3600
    with TestClient(app) as client:
        first = client.post(PUBLIC_ETL, headers=READ, json={})
        second = client.post(PUBLIC_ETL, headers=READ, json={})
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["run_id"] != second.json()["data"]["run_id"]
    assert pipeline.run_cycle.call_count == 2
    assert "Retry-After" not in first.headers and "Retry-After" not in second.headers


@pytest.mark.parametrize(
    "body",
    [
        {"source": "host"},
        {"source_id": "other"},
        {"duration": 86400},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"},
        {"server_count": 10000},
        {"seed": 123},
        {"malformed_rate": 0},
        {"url": "https://example.invalid"},
        {"sql": "DROP TABLE servers"},
    ],
)
def test_public_demo_rejects_client_controlled_parameters(public_demo_app, body):
    app, pipeline, constructor, host = public_demo_app
    with TestClient(app) as client:
        assert client.post(PUBLIC_ETL, headers=READ, json=body).status_code == 422
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()
    host.assert_not_called()


def test_public_demo_rejects_query_parameters(public_demo_app):
    app, pipeline, constructor, _ = public_demo_app
    with TestClient(app) as client:
        assert client.post(PUBLIC_ETL + "?source=host", headers=READ, json={}).status_code == 422
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (SourceBusyError("private-lock-detail"), 409, "SOURCE_BUSY"),
        (
            OperationalError("private-sql", {}, Exception("private-db-error")),
            503,
            "DATABASE_UNAVAILABLE",
        ),
    ],
)
def test_public_demo_preserves_lock_conflicts_and_sanitized_errors(
    public_demo_app, error, status, code
):
    app, pipeline, _, _ = public_demo_app
    pipeline.run_cycle.side_effect = error
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(PUBLIC_ETL, headers=READ, json={})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text
    assert "Retry-After" not in response.headers
    assert pipeline.run_cycle.call_count == 1


@pytest.mark.parametrize(
    "path", ["/api/v1/etl/run", "/api/v1/demo/etl/run", "/api/v1/sre/demo-runs"]
)
def test_public_demo_flag_does_not_weaken_admin_routes(public_demo_app, settings, path):
    app, pipeline, constructor, _ = public_demo_app
    settings.sre_enabled = True
    with TestClient(app) as client:
        assert client.post(path, headers=READ, json={}).status_code == 401
    pipeline.run_cycle.assert_not_called()
    constructor.assert_not_called()


def test_public_demo_failed_run_keeps_actual_audit_counters(public_demo_app):
    app, pipeline, _, _ = public_demo_app

    def failed(source, start, end):
        return RunResult(
            uuid4(),
            source.source_id,
            "FAILED",
            start,
            end,
            RunCounts(14, 13, 7, 6, 1),
            None,
            None,
            "DATABASE_ERROR",
        )

    pipeline.run_cycle.side_effect = failed
    with TestClient(app) as client:
        response = client.post(PUBLIC_ETL, headers=READ, json={})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "FAILED"
    assert response.json()["data"]["counts"] == dict(
        extracted=14, accepted=13, inserted=7, duplicated=6, rejected=1
    )


def test_public_demo_retains_invalid_configuration_guard(public_demo_app, settings):
    app, pipeline, _, _ = public_demo_app
    settings.telemetry_interval_seconds = 180
    with TestClient(app) as client:
        response = client.post(PUBLIC_ETL, headers=READ, json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ETL_CONFIGURATION_INVALID"
    pipeline.run_cycle.assert_not_called()
