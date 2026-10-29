import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from infrasight.db import models  # noqa: F401


def safe_test_database_url():
    url = os.getenv("TEST_DATABASE_URL")
    parsed = make_url(url) if url else None
    if parsed and (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or set(parsed.query) - {"sslmode"}
    ):
        raise RuntimeError(
            "Integration tests require loopback PostgreSQL; remote databases are forbidden"
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def guard_test_database():
    safe_test_database_url()


@contextmanager
def disposable_database():
    url = safe_test_database_url()
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to enable disposable PostgreSQL schema tests")
    # Only a newly created, uniquely named database is migrated/dropped by these tests.
    database_name = "infrasight_test_" + uuid4().hex
    admin = create_engine(
        url,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
    )
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        created = True
        engine = create_engine(
            make_url(url).set(database=database_name),
            connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
        )
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def domain_engine():
    with disposable_database() as engine:
        yield engine


@pytest.fixture(scope="session")
def etl_engine():
    # ETL commits real batches; keep them out of the schema tests' transaction fixture.
    with disposable_database() as engine:
        yield engine


@pytest.fixture
def db(domain_engine):
    with domain_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture(scope="session")
def analytics_engine():
    with disposable_database() as engine:
        yield engine


@pytest.fixture
def analytics_db(analytics_engine):
    with analytics_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def analytics_data(analytics_db):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import insert

    from infrasight.db.models import EtlRun, InfrastructureMetric, RawTelemetry, Region, Server

    class Data:
        def __init__(self):
            self.db = analytics_db
            self.start = datetime(2026, 1, 1, tzinfo=UTC)
            self.run = self.db.scalar(
                insert(EtlRun)
                .values(
                    source_id="fixture",
                    requested_window_start=self.start,
                    requested_window_end=self.start + timedelta(days=7),
                )
                .returning(EtlRun.id)
            )
            self.regions = {}
            self.event = 0

        def server(self, name="a", region="us-south", source="fixture"):
            if region not in self.regions:
                self.regions[region] = self.db.scalar(
                    insert(Region)
                    .values(provider="simulated", region_code=region, display_name=region)
                    .returning(Region.id)
                )
            return self.db.scalar(
                insert(Server)
                .values(
                    source_id=source,
                    external_server_id=name,
                    server_name=name,
                    environment="prod",
                    region_id=self.regions[region],
                    first_seen_at=self.start,
                    last_seen_at=self.start,
                )
                .returning(Server.id)
            )

        def metric(
            self,
            server,
            observed=None,
            seconds=30,
            cpu="10",
            memory="20",
            cost="1",
            currency="USD",
            health="HEALTHY",
            network=None,
        ):
            self.event += 1
            raw = self.db.scalar(
                insert(RawTelemetry)
                .values(
                    source_id="fixture",
                    source_event_id=str(self.event),
                    etl_run_id=self.run,
                    payload={"secret": "never-expose"},
                )
                .returning(RawTelemetry.id)
            )
            return self.db.scalar(
                insert(InfrastructureMetric)
                .values(
                    server_id=server,
                    etl_run_id=self.run,
                    raw_telemetry_id=raw,
                    observed_at=observed or self.start,
                    cpu_usage_percent=Decimal(cpu),
                    memory_usage_percent=Decimal(memory),
                    storage_usage_percent=Decimal("50"),
                    network_mbps=network,
                    uptime_seconds=None,
                    server_status="RUNNING",
                    resource_health=health,
                    estimated_cost=None if cost is None else Decimal(cost),
                    currency=currency,
                    interval_seconds=seconds,
                )
                .returning(InfrastructureMetric.id)
            )

    return Data()


@pytest.fixture
def sre_engine():
    with disposable_database() as engine:
        yield engine


@pytest.fixture
def sre_http(sre_engine):
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from pydantic import SecretStr

    from infrasight.config import Settings
    from infrasight.main import create_app

    read = "sre-integration-read"
    admin_key = "sre-integration-admin"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=sre_engine.url.render_as_string(hide_password=False),
        api_read_key=SecretStr(read),
        api_admin_key=SecretStr(admin_key),
        sre_enabled=True,
        sre_probe_port=port,
        sre_cooldown_seconds=0,
    )
    app = create_app(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            host="127.0.0.1",
            port=port,
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "Temporary HTTP server did not start"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=30
        ) as client:
            yield client, settings
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), "Temporary HTTP server did not stop"
