from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource

pytestmark = pytest.mark.integration
LEGACY_TABLES = (
    "regions",
    "servers",
    "etl_runs",
    "raw_telemetry",
    "infrastructure_metrics",
    "data_quality_rejections",
    "ingestion_state",
)


def snapshot(connection):
    return {
        name: connection.execute(
            text(f"SELECT to_jsonb(t)::text FROM {name} t ORDER BY to_jsonb(t)::text")
        )
        .scalars()
        .all()
        for name in LEGACY_TABLES
    }


def test_additive_migration_preserves_every_legacy_row_and_view(sre_engine, settings):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with sre_engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0002")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result = ETLPipeline(sre_engine, settings).run_cycle(
        SimulatedCloudTelemetrySource(server_count=50, malformed_rate=0.1),
        start,
        start + timedelta(seconds=120),
    )
    assert result.status == "SUCCEEDED"
    with sre_engine.begin() as db:
        config.attributes["connection"] = db
        before = snapshot(db)
        assert all(before[name] for name in LEGACY_TABLES)
        views = set(inspect(db).get_view_names(schema="analytics"))
        measurements = db.scalar(text("SELECT COUNT(*) FROM analytics.high_resource_usage"))
        command.upgrade(config, "head")
        assert snapshot(db) == before
        assert set(inspect(db).get_view_names(schema="analytics")) == views
        assert db.scalar(text("SELECT COUNT(*) FROM analytics.high_resource_usage")) == measurements
        sre_tables = {name for name in inspect(db).get_table_names() if name.startswith("sre_")}
        assert sre_tables == {
            "sre_services",
            "sre_demo_runs",
            "sre_probe_results",
            "sre_incidents",
            "sre_incident_events",
            "sre_recovery_attempts",
        }
        command.downgrade(config, "0002")
        assert snapshot(db) == before
        assert not any(name.startswith("sre_") for name in inspect(db).get_table_names())
        command.upgrade(config, "head")
        assert snapshot(db) == before
