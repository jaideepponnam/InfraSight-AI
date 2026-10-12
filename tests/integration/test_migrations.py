from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from infrasight.db.base import Base

pytestmark = pytest.mark.integration


def test_downgrade_reupgrade_and_metadata_match(domain_engine):
    # domain_engine always points to a uniquely named disposable database.
    assert domain_engine.url.database.startswith("infrasight_test_")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with domain_engine.begin() as connection:
        config.attributes["connection"] = connection
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []
