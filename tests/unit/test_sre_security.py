from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from infrasight.main import create_app
from infrasight.sre.probes import HTTPProbe
from infrasight.sre.rules import SERVICE_KEY

READ = {"X-API-Key": "sre-test-read"}
ADMIN = {**READ, "X-Admin-Key": "sre-test-admin"}
ID = str(uuid4())
MUTATIONS = [
    "/api/v1/sre/demo-runs",
    f"/api/v1/sre/demo-runs/{ID}/probe",
    f"/api/v1/sre/incidents/{ID}/acknowledge",
    f"/api/v1/sre/incidents/{ID}/recover",
]


@pytest.fixture
def app(settings):
    from pydantic import SecretStr

    settings.api_read_key = SecretStr("sre-test-read")
    settings.api_admin_key = SecretStr("sre-test-admin")
    return create_app(settings)


@pytest.mark.parametrize("path", MUTATIONS)
@pytest.mark.parametrize(
    "headers", [{}, READ, {"X-Admin-Key": "sre-test-admin"}, {**READ, "X-Admin-Key": "wrong"}]
)
def test_every_mutation_requires_both_keys(app, path, headers):
    with TestClient(app) as client:
        assert client.post(path, json={}, headers=headers).status_code == 401


def test_disabled_feature_and_openapi(app):
    with TestClient(app) as client:
        assert client.get("/api/v1/sre/services", headers=READ).status_code == 503
        assert client.post("/api/v1/sre/demo-runs", json={}, headers=ADMIN).status_code == 503
        assert client.get(f"/_sre-demo/{ID}/dependency").status_code == 404
    spec = app.openapi()
    assert not any(path.startswith("/_sre-demo") for path in spec["paths"])
    for path in MUTATIONS:
        # Replace actual UUIDs with OpenAPI parameter names.
        route = path.replace(ID, "{run_id}" if "/demo-runs/" in path else "{incident_id}")
        assert spec["paths"][route]["post"]["security"] == [{"ApplicationKey": [], "AdminKey": []}]


def test_admin_cors_is_not_exposed_to_browser(app):
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/sre/demo-runs",
            headers={
                "Origin": "https://jaideepponnam.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key,X-Admin-Key,Idempotency-Key",
            },
        )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "status,state,outcome",
    [
        (503, "active", "HTTP_503"),
        (200, "baseline", "HEALTHY"),
        (200, "expired", "HEALTHY"),
        (302, "baseline", "UNEXPECTED_HTTP"),
        (503, "cleared", "UNEXPECTED_HTTP"),
    ],
)
def test_probe_target_and_sanitized_evidence(settings, monkeypatch, status, state, outcome):
    run_id, correlation = uuid4(), uuid4()
    original = httpx.Client
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status,
            json={
                "kind": SERVICE_KEY,
                "run_id": str(run_id),
                "fault_state": state,
                "private": "must-not-retain",
            },
            headers={"X-Request-ID": str(correlation)},
        )

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)
    result = HTTPProbe(settings).observe(run_id, "probe-only-token")
    assert result["outcome"] == outcome
    assert result["duration_ms"] >= 0
    assert result["target_request_id"] == correlation
    assert "must-not-retain" not in str(result)
    assert "probe-only-token" not in str(result)
    assert seen[0].url.host == "127.0.0.1"
    assert not any(h in seen[0].headers for h in ("X-API-Key", "X-Admin-Key", "Authorization"))


@pytest.mark.parametrize("kind", ["timeout", "transport", "malformed", "oversized", "wrong-run"])
def test_probe_never_invents_controlled_failure(settings, monkeypatch, kind):
    original = httpx.Client

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private-error")
        if kind == "transport":
            raise httpx.ConnectError("private-error")
        if kind == "malformed":
            return httpx.Response(503, content=b"not-json")
        if kind == "oversized":
            return httpx.Response(503, content=b"x" * 4096)
        return httpx.Response(
            503,
            json={"kind": SERVICE_KEY, "run_id": str(uuid4()), "fault_state": "active"},
            headers={"X-Request-ID": str(uuid4())},
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    result = HTTPProbe(settings).observe(uuid4(), "secret")
    assert result["outcome"] in {"TIMEOUT", "TRANSPORT_ERROR", "INVALID_RESPONSE"}
    assert "private-error" not in str(result)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://test@production.neon.tech/db",
        "postgresql+psycopg://test@127.0.0.1/db?host=production.neon.tech",
        "postgresql+psycopg://test@127.0.0.1/db?hostaddr=192.0.2.1",
        "postgresql+psycopg://test@127.0.0.1/db?service=production",
        "postgresql+psycopg://test@127.0.0.1/db?dbname=production",
    ],
)
def test_integration_guard_rejects_remote_and_target_overrides(monkeypatch, url):
    import runpy
    from pathlib import Path

    fixture_file = Path(__file__).resolve().parents[1] / "integration" / "conftest.py"
    guard = runpy.run_path(str(fixture_file))["safe_test_database_url"]
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(RuntimeError, match="remote databases are forbidden"):
        guard()
