from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import make_url

from infrasight.api.dependencies import analytics
from infrasight.config import Settings
from infrasight.main import create_app


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_neon_url_normalization_preserves_encoded_credentials_and_tls(scheme):
    raw = f"{scheme}://demo:p%40ss%25word@ep-demo.us-east-2.aws.neon.tech/demo?sslmode=require&channel_binding=require"
    settings = Settings(_env_file=None, database_url=raw)
    parsed = make_url(settings.database_url.get_secret_value())
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.password == "p@ss%word"
    assert parsed.query["sslmode"] == "require"
    assert parsed.query["channel_binding"] == "require"
    assert "p@ss" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://demo:private@ep-demo-pooler.us-east-2.aws.neon.tech/demo?sslmode=require",
        "postgresql://demo:private@ep-demo.us-east-2.aws.neon.tech/demo",
        "postgresql://demo:private@ep-demo.us-east-2.aws.neon.tech/demo?sslmode=disable",
    ],
)
def test_neon_rejects_pooler_and_insecure_connections(url):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=url)
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "origin",
    ["*", "https://*.example.com", "https://example.com/path", "https://user:password@example.com"],
)
def test_cors_rejects_wildcards_paths_and_credentials(settings, origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, cors_allowed_origins=[origin])


def test_read_credential_cannot_be_admin_credential(settings):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=settings.database_url,
            api_read_key="same",
            api_admin_key="same",
        )


@pytest.fixture
def cors_app(settings):
    settings.api_read_key = SecretStr("public-demo-read")
    settings.api_admin_key = SecretStr("private-admin")
    app = create_app(settings)
    app.dependency_overrides[analytics] = lambda: Mock()
    return app


@pytest.mark.parametrize(
    "origin", ["https://jaideepponnam.com", "http://localhost:5173", "http://127.0.0.1:5174"]
)
def test_read_and_ai_cors_preflight_without_authentication(cors_app, origin):
    with TestClient(cors_app) as client:
        response = client.options(
            "/api/v1/ai/query",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key,Content-Type",
            },
        )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


def test_unapproved_origin_is_not_allowed(cors_app):
    with TestClient(cors_app) as client:
        response = client.options(
            "/api/v1/ai/query",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_bypass_auth_and_exposes_request_id(cors_app):
    with TestClient(cors_app) as client:
        response = client.get("/api/v1/servers", headers={"Origin": "https://jaideepponnam.com"})
    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "https://jaideepponnam.com"
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"


def test_public_demo_key_cannot_trigger_etl(cors_app):
    with TestClient(cors_app) as client:
        response = client.post(
            "/api/v1/etl/run", json={}, headers={"X-API-Key": "public-demo-read"}
        )
    assert response.status_code == 401
