import pytest

from infrasight.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://test:secret@127.0.0.1:1/test",
        db_connect_timeout_seconds=1,
    )
