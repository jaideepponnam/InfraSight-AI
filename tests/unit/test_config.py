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


@pytest.mark.parametrize("url", ["sqlite:///test.db", "broken-secret", "postgresql://a/b"])
def test_rejects_invalid_database_url(url):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=url)
    assert url not in str(error.value)


def test_rejects_unbounded_pool(settings):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, db_pool_size=0)
