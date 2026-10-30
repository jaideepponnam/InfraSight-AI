import pytest
from pydantic import ValidationError

from infrasight.config import Settings


def test_password_is_redacted(settings):
    assert "secret" not in repr(settings)
    assert "secret" not in settings.model_dump_json()


def test_environment_loading(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:secret@localhost/demo")
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    assert Settings(_env_file=None).db_pool_size == 7


@pytest.mark.parametrize("url", ["sqlite:///test.db", "broken-secret", "postgresql:///b"])
def test_rejects_invalid_database_url(url):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=url)
    assert url not in str(error.value)


def test_rejects_unbounded_pool(settings):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, db_pool_size=0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"etl_batch_size": 1001},
        {"etl_max_window_seconds": 89},
        {"etl_initial_lookback_seconds": 29},
    ],
)
def test_ingestion_configuration_prevents_unbounded_or_stalled_windows(settings, overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sre_probe_port": 80},
        {"sre_probe_port": 65536},
        {"sre_probe_timeout_seconds": 0},
        {"sre_probe_timeout_seconds": 6},
        {"sre_run_deadline_seconds": 29},
        {"sre_run_deadline_seconds": 121},
        {"sre_cooldown_seconds": -1},
    ],
)
def test_sre_configuration_bounds(settings, overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, **overrides)


def test_sre_disabled_by_default_and_inherits_hosted_port(settings, monkeypatch):
    monkeypatch.setenv("PORT", "12345")
    configured = Settings(_env_file=None, database_url=settings.database_url)
    assert configured.sre_enabled is False
    assert configured.sre_probe_port == 12345


def test_public_etl_is_disabled_by_default(settings, monkeypatch):
    monkeypatch.delenv("DEMO_PUBLIC_ETL_ENABLED", raising=False)
    assert (
        Settings(_env_file=None, database_url=settings.database_url).demo_public_etl_enabled
        is False
    )


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_public_etl_flag_environment_loading(settings, monkeypatch, value, expected):
    monkeypatch.setenv("DEMO_PUBLIC_ETL_ENABLED", value)
    assert (
        Settings(_env_file=None, database_url=settings.database_url).demo_public_etl_enabled
        is expected
    )
