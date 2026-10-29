import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from infrasight.config import Settings
from infrasight.db import models  # noqa: F401
from infrasight.db.base import Base
from infrasight.db.session import create_database_engine, create_session_factory
from infrasight.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def database_settings():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    return Settings(_env_file=None, app_env="test", database_url=url)


def test_database_connectivity_and_transaction_cleanup(database_settings):
    engine = create_database_engine(database_settings)
    factory = create_session_factory(engine)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
        with factory() as session:
            # SET LOCAL is transaction-scoped; closing must roll it back.
            session.execute(text("SET LOCAL application_name = 'infrasight_rollback_test'"))
        with factory() as session:
            assert session.scalar(text("SHOW application_name")) != "infrasight_rollback_test"
        assert len(Base.metadata.tables) == 13
    finally:
        engine.dispose()


def test_real_database_readiness(database_settings):
    with TestClient(create_app(database_settings)) as client:
        assert client.get("/health/ready").status_code == 200
