from alembic import context

from infrasight.config import get_settings
from infrasight.db import models  # noqa: F401 -- register all domain metadata
from infrasight.db.base import Base
from infrasight.db.session import create_database_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests supply a connection to a disposable database; normal CLI uses .env.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return
    engine = create_database_engine(get_settings())
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
