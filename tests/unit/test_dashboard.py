from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from infrasight.dashboard.client import APIClient, APIError
from infrasight.dashboard.config import DashboardSettings
from infrasight.dashboard.helpers import (
    badge,
    fleet_rows,
    freshness,
    money,
    number,
    params,
    percent,
)


def settings(**values):
    return DashboardSettings(
        _env_file=None,
        api_key=SecretStr("test-read-only"),
        admin_key=SecretStr("test-admin-only"),
        **values,
    )


def test_client_headers_are_server_side():
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}, "meta": {}})

    client = APIClient(settings(), httpx.MockTransport(respond))
    client.get("/api/v1/servers", {"region_code": None})
    client.trigger({"source": "simulator"})
    assert captured[0].headers["X-API-Key"] == "test-read-only"
    assert "X-Admin-Key" not in captured[0].headers
    assert captured[1].headers["X-Admin-Key"] == "test-admin-only"
    assert "region_code" not in str(captured[0].url)
    client.close()


@pytest.mark.parametrize("status", [401, 403, 409, 422, 429, 502, 503, 504])
def test_clean_api_errors(status):
    client = APIClient(
        settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                json={"error": {"message": "private-provider-detail"}},
                headers={"X-Request-ID": "safe-id"},
            )
        ),
    )
    with pytest.raises(APIError) as caught:
        client.get("/api/v1/servers")
    assert caught.value.status == status
    assert caught.value.request_id == "safe-id"
    assert "private-provider-detail" not in caught.value.message
    assert "test-read-only" not in str(caught.value)
    client.close()


@pytest.mark.parametrize("body", [[], {}, {"data": 1, "meta": []}, {"answer": 123, "evidence": {}}])
def test_invalid_structured_response(body):
    client = APIClient(
        settings(), httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    )
    with pytest.raises(APIError):
        client.get("/api/v1/servers")
    client.close()


def test_timeout_and_connection_errors():
    for failure, status in [
        (httpx.ReadTimeout("private"), 504),
        (httpx.ConnectError("private"), 503),
    ]:

        def fail(request, error=failure):
            raise error

        client = APIClient(settings(), httpx.MockTransport(fail))
        with pytest.raises(APIError) as caught:
            client.get("/api/v1/servers")
        assert caught.value.status == status
        client.close()


def test_missing_admin_does_not_send_request():
    config = settings()
    config.admin_key = None
    client = APIClient(
        config, httpx.MockTransport(lambda request: pytest.fail("No network call expected"))
    )
    with pytest.raises(APIError, match="ADMIN_KEY_NOT_CONFIGURED"):
        client.trigger({})
    client.close()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://database",
        "https://user:password@example.com",
        "https://example.com?token=hidden",
    ],
)
def test_frontend_settings_reject_secret_urls(url):
    with pytest.raises(ValidationError):
        settings(api_base_url=url)


def test_exact_money_formatting():
    assert money("9007199254740993.12345678", "USD", 8) == "USD 9,007,199,254,740,993.12345678"
    assert money(Decimal("0.00000001"), "USD", 8) == "USD 0.00000001"
    assert money(None) == "Unknown"
    assert number("NaN") is None and number("Infinity") is None
    assert percent("0.99111111", True) == "99.1%"


def test_freshness_does_not_confuse_reference_with_live():
    fresh = {
        "servers_with_observations": 75,
        "reporting_servers": 75,
        "stale_servers": 0,
        "no_data_servers": 0,
    }
    assert freshness(fresh, "Historical demo") == "SNAPSHOT"
    assert freshness(fresh, "Live · last hour") == "LIVE"
    assert (
        freshness({**fresh, "reporting_servers": 0, "stale_servers": 75}, "Live · last hour")
        == "STALE"
    )
    assert freshness({"servers_with_observations": 0}, "Historical demo") == "NO_DATA"
    assert freshness({**fresh, "stale_servers": 1}, "Live · last hour") == "PARTIAL"


def test_fleet_keeps_stale_health_and_exact_cost():
    row = fleet_rows(
        [
            {
                "server_name": "example",
                "effective_health": "STALE",
                "estimated_cost": "0.12345678",
                "currency": "USD",
            }
        ]
    )[0]
    assert row["Health"] == "STALE"
    assert row["Interval cost"] == "USD 0.12345678"
    assert row["CPU"] == "—"
    assert "<script>" not in badge("<script>")


def test_reference_controls():
    historical = params("Historical demo", "simulated-cloud")
    assert historical["as_of"].startswith("2026-10-11T19:33")
    assert historical["start"].startswith("2026-10-11T19:30")
    now = datetime(2026, 10, 12, tzinfo=UTC)
    live = params("Live · last hour", "simulated-cloud", now=now)
    assert live["end"] == now.isoformat()
    assert live["start"].startswith("2026-10-11T23:00")
