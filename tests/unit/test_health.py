import json
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from infrasight.db.session import get_session
from infrasight.main import create_app


def test_liveness_without_database(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    UUID(response.headers["X-Request-ID"])


def test_readiness_success(settings):
    app = create_app(settings)
    session = Mock()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "available"
    session.execute.assert_called_once()


def test_readiness_failure_does_not_expose_credentials(settings, capsys):
    app = create_app(settings)
    session = Mock()
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("secret"))
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "secret" not in capsys.readouterr().out
    session.rollback.assert_called_once()


def test_unexpected_error_is_sanitized(settings):
    app = create_app(settings)
    session = Mock()
    session.execute.side_effect = RuntimeError("secret")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health/ready")
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_request_log_has_json_context(settings, capsys):
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    request_log = next(log for log in logs if log["event"] == "http_request")
    assert request_log["request_id"] == response.headers["X-Request-ID"]
    assert request_log["status_code"] == 200
    assert "duration_ms" in request_log
