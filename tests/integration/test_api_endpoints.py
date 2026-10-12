from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event

from infrasight.analytics.schemas import Window
from infrasight.analytics.services import AnalyticsService
from infrasight.config import Settings
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.main import create_app

pytestmark = pytest.mark.integration
START = datetime(2026, 10, 11, 19, 30, tzinfo=UTC)
END = START + timedelta(minutes=3)
HEADERS = {"X-API-Key": "integration-read-key"}
PARAMS = {
    "source_id": "simulated-cloud",
    "as_of": END.isoformat(),
    "start": START.isoformat(),
    "end": END.isoformat(),
    "limit": 100,
}


@pytest.fixture(scope="module")
def api_environment():
    from conftest import disposable_database

    with disposable_database() as engine:
        settings = Settings(
            _env_file=None,
            database_url=SecretStr(engine.url.render_as_string(hide_password=False)),
            api_read_key=SecretStr("integration-read-key"),
            api_admin_key=SecretStr("integration-admin-key"),
        )
        result = ETLPipeline(engine, settings).run_cycle(
            SimulatedCloudTelemetrySource(), START, END
        )
        assert result.status == "SUCCEEDED"
        app = create_app(settings)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, engine, settings


def test_overview_four_queries(api_environment):
    client, engine, settings = api_environment
    queries = []

    def count(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", count)
    try:
        response = client.get("/api/v1/analytics/overview", params=PARAMS, headers=HEADERS)
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(queries) == 4
    assert data["inventory_servers"] == 75
    assert (data["healthy_servers"], data["warning_servers"], data["critical_servers"]) == (
        64,
        1,
        10,
    )
    assert data["stale_servers"] == 0
    assert Decimal(data["observed_cost"]) == Decimal("1.03775797")
    service = AnalyticsService(engine, settings)
    expected = service.overview(Window(**PARAMS, currency="USD"))
    assert Decimal(data["observed_cost"]) == expected.rows[0]["observed_cost"]
    assert response.json()["meta"]["window_start"].startswith("2026-10-11T19:30")


def test_stale_snapshot(api_environment):
    client, _, _ = api_environment
    response = client.get(
        "/api/v1/analytics/overview",
        params={**PARAMS, "as_of": (END + timedelta(hours=1)).isoformat()},
        headers=HEADERS,
    )
    data = response.json()["data"]
    assert data["stale_servers"] == 75
    assert data["reporting_servers"] == 0
    assert data["highest_cpu_server"] is None
    assert data["average_cpu_percent"] is None


@pytest.mark.parametrize(
    "endpoint", ["high-cpu", "regions", "cost-summary", "underutilized", "cpu-pressure"]
)
def test_business_answers(api_environment, endpoint):
    client, _, _ = api_environment
    params = {**PARAMS}
    if endpoint in {"underutilized", "cpu-pressure"}:
        params["min_samples"] = 4
    response = client.get("/api/v1/analytics/" + endpoint, params=params, headers=HEADERS)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    if endpoint == "high-cpu":
        assert len(data) == 11
        assert sum(r["breach_count"] for r in data) == 43
    elif endpoint == "regions":
        assert len(data) == 3
        assert sum(r["critical_servers"] for r in data) == 10
        assert sum(Decimal(r["period_cost"]["estimated_cost"]) for r in data) == Decimal(
            "1.03775797"
        )
    elif endpoint == "cost-summary":
        assert Decimal(data["estimated_cost"]) == Decimal("1.03775797")
        assert data["top_cost_servers"][0]["external_server_id"] == "sim-075"
        assert data["currency"] == "USD"
    elif endpoint == "underutilized":
        assert len(data) == 10
        assert response.json()["meta"]["warnings"]
    else:
        assert len(data) == 11


def test_minimum_breaches_and_storage(api_environment):
    client, _, _ = api_environment
    response = client.get(
        "/api/v1/analytics/high-cpu", params={**PARAMS, "min_breach_count": 4}, headers=HEADERS
    )
    assert all(r["breach_count"] >= 4 for r in response.json()["data"])
    response = client.get(
        "/api/v1/analytics/top-resource-usage",
        params={"as_of": END.isoformat(), "resource": "storage"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    values = [Decimal(r["storage_usage_percent"]) for r in response.json()["data"]]
    assert values == sorted(values, reverse=True)


def test_inventory_pagination_and_detail(api_environment):
    client, _, _ = api_environment
    first = client.get("/api/v1/servers", params={"limit": 2}, headers=HEADERS).json()
    second = client.get("/api/v1/servers", params={"limit": 2, "offset": 2}, headers=HEADERS).json()
    assert first["meta"]["pagination"]["total"] == 75
    assert not {r["server_id"] for r in first["data"]} & {r["server_id"] for r in second["data"]}
    detail = client.get(
        "/api/v1/servers/" + first["data"][0]["server_id"],
        params={"as_of": END.isoformat()},
        headers=HEADERS,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["latest_telemetry"]["effective_health"] in {
        "HEALTHY",
        "WARNING",
        "CRITICAL",
    }
    filtered = client.get(
        "/api/v1/servers",
        params={"region_code": "eu-de", "environment": "prod", "limit": 100},
        headers=HEADERS,
    ).json()
    assert filtered["data"]
    assert all(r["region_code"] == "eu-de" and r["environment"] == "prod" for r in filtered["data"])
    assert "payload" not in detail.text


@pytest.mark.parametrize("path", ["servers", "etl/runs"])
def test_unknown_ids(api_environment, path):
    client, _, _ = api_environment
    response = client.get("/api/v1/" + path + "/" + str(uuid4()), headers=HEADERS)
    assert response.status_code == 404


def test_health_pagination_filters_and_empty(api_environment):
    client, _, _ = api_environment
    result = client.get(
        "/api/v1/analytics/server-health",
        params={"as_of": END.isoformat(), "health": "CRITICAL", "limit": 2},
        headers=HEADERS,
    ).json()
    assert len(result["data"]) == 2
    assert result["meta"]["pagination"]["total"] == 10
    assert all(r["effective_health"] == "CRITICAL" for r in result["data"])
    empty = client.get(
        "/api/v1/analytics/server-health", params={"source_id": "absent"}, headers=HEADERS
    )
    assert empty.status_code == 200 and empty.json()["data"] == []


def test_replay_and_history(api_environment):
    client, _, _ = api_environment
    before = client.get("/api/v1/analytics/cost-summary", params=PARAMS, headers=HEADERS).json()[
        "data"
    ]
    response = client.post(
        "/api/v1/etl/run",
        headers={**HEADERS, "X-Admin-Key": "integration-admin-key"},
        json={"source": "simulator", "start": START.isoformat(), "end": END.isoformat()},
    )
    assert response.status_code == 200, response.text
    run = response.json()["data"]
    assert run["status"] == "SUCCEEDED"
    assert run["counts"] == {
        "extracted": 450,
        "accepted": 446,
        "inserted": 0,
        "duplicated": 446,
        "rejected": 4,
    }
    after = client.get("/api/v1/analytics/cost-summary", params=PARAMS, headers=HEADERS).json()[
        "data"
    ]
    assert before == after
    history = client.get("/api/v1/etl/runs", headers=HEADERS).json()
    assert history["meta"]["pagination"]["total"] >= 2
    detail = client.get("/api/v1/etl/runs/" + run["run_id"], headers=HEADERS).json()["data"]
    assert detail["records_duplicated"] == 446
    assert "error_details" not in detail and "cursor_after" not in detail


def test_etl_invalid_or_disabled_source(api_environment):
    client, _, _ = api_environment
    headers = {**HEADERS, "X-Admin-Key": "integration-admin-key"}
    for body in [
        {"source": "arbitrary.class"},
        {"source": "host"},
        {"start": START.isoformat(), "end": (START + timedelta(hours=1)).isoformat()},
    ]:
        assert client.post("/api/v1/etl/run", headers=headers, json=body).status_code == 422


def test_cost_comparison(api_environment):
    client, _, _ = api_environment
    params = {
        "mode": "explicit",
        "as_of": END.isoformat(),
        "source_id": "simulated-cloud",
        "current_start": START.isoformat(),
        "current_end": END.isoformat(),
        "previous_start": (START - timedelta(days=1)).isoformat(),
        "previous_end": (END - timedelta(days=1)).isoformat(),
    }
    response = client.get("/api/v1/analytics/cost-comparison", params=params, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["quality"] == "UNKNOWN_COST"
    assert response.json()["data"]["percentage_change"] is None


def test_no_data_and_unknown_currency(api_environment):
    client, _, _ = api_environment
    no_data = client.get(
        "/api/v1/analytics/server-health",
        params={"as_of": (START - timedelta(minutes=1)).isoformat(), "limit": 100},
        headers=HEADERS,
    )
    assert no_data.status_code == 200
    assert all(
        r["effective_health"] == "NO_DATA" and r["observed_at"] is None
        for r in no_data.json()["data"]
    )
    unknown = client.get(
        "/api/v1/analytics/cost-summary", params={**PARAMS, "currency": "EUR"}, headers=HEADERS
    )
    assert unknown.status_code == 200
    assert unknown.json()["data"]["estimated_cost"] is None
    assert Decimal(unknown.json()["data"]["cost_coverage_fraction"]) == 0
    assert unknown.json()["data"]["top_cost_servers"] == []
