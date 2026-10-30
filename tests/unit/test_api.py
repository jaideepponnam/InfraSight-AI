import json
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from infrasight.api.dependencies import analytics
from infrasight.api.schemas import Envelope
from infrasight.main import create_app


@pytest.fixture
def api_app(settings):
    settings.api_read_key = SecretStr("unit-read-key")
    settings.api_admin_key = SecretStr("unit-admin-key")
    return create_app(settings)


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json"])
def test_public_paths(api_app, path):
    with TestClient(api_app) as client:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-Admin-Key": "unit-admin-key"}])
def test_read_requires_read_key(api_app, headers):
    with TestClient(api_app) as client:
        response = client.get("/api/v1/servers", headers=headers)
    assert response.status_code == 401
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "unit-read-key" not in response.text


@pytest.mark.parametrize("admin", [None, "wrong"])
def test_admin_requires_both_keys(api_app, admin):
    headers = {"X-API-Key": "unit-read-key"}
    if admin:
        headers["X-Admin-Key"] = admin
    with TestClient(api_app) as client:
        response = client.post("/api/v1/etl/run", headers=headers, json={})
    assert response.status_code == 401


def test_fail_closed_without_configured_key(settings):
    settings.api_read_key = None
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/servers", headers={"X-API-Key": "anything"})
    assert response.status_code == 503


@pytest.mark.parametrize(
    "path,params",
    [
        ("servers", {"limit": 101}),
        ("servers", {"offset": -1}),
        ("servers", {"environment": "invalid"}),
        ("analytics/high-cpu", {"threshold": 101}),
        ("analytics/high-cpu", {"threshold": "NaN"}),
        ("analytics/high-cpu", {"min_breach_count": 0}),
        ("analytics/overview", {"as_of": "2026-10-11T19:33:00"}),
        ("analytics/overview", {"start": "2026-10-11T19:30:00Z"}),
        ("analytics/overview", {"start": "2026-10-11T19:33:00Z", "end": "2026-10-11T19:30:00Z"}),
        ("analytics/top-resource-usage", {"resource": "cpu; DROP TABLE servers"}),
        ("analytics/cost-summary", {"currency": "usd"}),
        ("analytics/cpu-pressure", {"min_coverage": 2}),
        ("analytics/cost-comparison", {"mode": "explicit"}),
        ("analytics/overview", {"unknown": "ignored?"}),
        ("servers/not-a-uuid", {}),
    ],
)
def test_validation(api_app, path, params):
    with TestClient(api_app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/" + path, params=params, headers={"X-API-Key": "unit-read-key"}
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_PARAMETERS"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_database_error_sanitized(api_app, capsys):
    service = Mock()
    service.overview.side_effect = OperationalError("secret-sql", {}, Exception("secret-password"))
    api_app.dependency_overrides[analytics] = lambda: service
    with TestClient(api_app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/analytics/overview", headers={"X-API-Key": "unit-read-key"})
    assert response.status_code == 503
    assert "secret-password" not in response.text + capsys.readouterr().out


def test_decimal_serialization():
    envelope = Envelope.model_validate(
        {
            "data": {
                "estimated_cost": Decimal("123.12345678"),
                "nested": {"cost": Decimal("0.00000001")},
            },
            "meta": {"request_id": "test"},
        }
    )
    assert '"123.12345678"' in envelope.model_dump_json(exclude_unset=True)
    assert Decimal(
        json.loads(envelope.model_dump_json(exclude_unset=True))["data"]["nested"]["cost"]
    ) == Decimal("0.00000001")


def test_openapi_security(api_app):
    spec = api_app.openapi()
    assert spec["components"]["securitySchemes"]["ApplicationKey"]["name"] == "X-API-Key"
    assert spec["components"]["securitySchemes"]["AdminKey"]["name"] == "X-Admin-Key"
    for path in ("/api/v1/etl/run", "/api/v1/demo/etl/run"):
        post = spec["paths"][path]["post"]
        assert post["security"] == [{"ApplicationKey": [], "AdminKey": []}]
        assert "202" not in post["responses"]
    assert "security" not in spec["paths"]["/health"]["get"]
    assert "unit-read-key" not in str(spec)


def test_source_busy_response(api_app, monkeypatch):
    from infrasight.ingestion.errors import SourceBusyError
    from infrasight.ingestion.pipeline import ETLPipeline

    def busy(*args, **kwargs):
        raise SourceBusyError("internal-source-detail")

    monkeypatch.setattr(ETLPipeline, "run_cycle", busy)
    with TestClient(api_app) as client:
        response = client.post(
            "/api/v1/etl/run",
            headers={"X-API-Key": "unit-read-key", "X-Admin-Key": "unit-admin-key"},
            json={},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_BUSY"
    assert "internal-source-detail" not in response.text


def test_etl_failed_cycle_remains_completed_result(api_app, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from infrasight.ingestion.pipeline import ETLPipeline
    from infrasight.ingestion.schemas import RunCounts, RunResult

    end = datetime.now(UTC)
    result = RunResult(
        uuid4(),
        "simulated-cloud",
        "FAILED",
        end - timedelta(minutes=1),
        end,
        RunCounts(),
        None,
        None,
        "SOURCE_UNAVAILABLE",
    )
    monkeypatch.setattr(ETLPipeline, "run_cycle", lambda *args, **kwargs: result)
    with TestClient(api_app) as client:
        response = client.post(
            "/api/v1/etl/run",
            headers={"X-API-Key": "unit-read-key", "X-Admin-Key": "unit-admin-key"},
            json={},
        )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "FAILED"
    assert response.json()["data"]["error_code"] == "SOURCE_UNAVAILABLE"


def test_unknown_route_consistent_error(api_app):
    with TestClient(api_app) as client:
        response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
