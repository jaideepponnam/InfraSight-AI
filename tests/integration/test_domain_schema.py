from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from infrasight.db.base import Base
from infrasight.db.models import (
    DataQualityRejection,
    EtlRun,
    InfrastructureMetric,
    IngestionState,
    RawTelemetry,
    Region,
    Server,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def add(db, model, **values):
    return db.scalar(insert(model).values(**values).returning(model.id))


def expect_failure(db, statement, sqlstate):
    with pytest.raises(DBAPIError) as error, db.begin_nested():
        db.execute(statement)
    assert error.value.orig.sqlstate == sqlstate


@pytest.fixture
def graph(db):
    region = add(
        db, Region, provider="simulated", region_code="us-central", display_name="US Central"
    )
    run = add(
        db,
        EtlRun,
        source_id="simulated-cloud",
        requested_window_start=NOW,
        requested_window_end=NOW + timedelta(minutes=1),
    )
    server = add(
        db,
        Server,
        source_id="simulated-cloud",
        external_server_id="vm-001",
        server_name="analytics-01",
        environment="prod",
        region_id=region,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    raw = add(
        db,
        RawTelemetry,
        source_id="simulated-cloud",
        source_event_id="event-001",
        etl_run_id=run,
        payload={"cpu": "40.25", "unknown_provider_field": [1, 2]},
    )
    metric = add(
        db,
        InfrastructureMetric,
        server_id=server,
        etl_run_id=run,
        raw_telemetry_id=raw,
        observed_at=NOW,
        cpu_usage_percent=Decimal("40.25"),
        memory_usage_percent=50,
        storage_usage_percent=60,
        network_mbps=Decimal("1.1250"),
        uptime_seconds=123,
        server_status="RUNNING",
        resource_health="HEALTHY",
        estimated_cost=Decimal("0.00001234"),
        currency="USD",
        interval_seconds=30,
    )
    return {"region": region, "run": run, "server": server, "raw": raw, "metric": metric}


def test_schema_constraints_indexes_and_types(db):
    inspector = inspect(db)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    for name, table in Base.metadata.tables.items():
        actual = {column["name"]: column for column in inspector.get_columns(name)}
        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable
        actual_checks = {c["name"] for c in inspector.get_check_constraints(name)}
        expected_checks = {
            c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
        }
        assert actual_checks == expected_checks
        assert {i["name"] for i in inspector.get_indexes(name)} >= {i.name for i in table.indexes}
        actual_unique = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(name)}
        expected_unique = {
            tuple(c.columns.keys())
            for c in table.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        }
        assert actual_unique == expected_unique
        for foreign_key in inspector.get_foreign_keys(name):
            assert foreign_key["options"]["ondelete"] == "RESTRICT"
        for column in actual.values():
            if column["name"].endswith("_at") or column["name"].startswith("watermark"):
                assert column["type"].timezone
    metric_columns = {c["name"]: c for c in inspector.get_columns("infrastructure_metrics")}
    assert metric_columns["estimated_cost"]["type"].precision == 18
    assert metric_columns["estimated_cost"]["type"].scale == 8
    indexes = {i["name"]: i for i in inspector.get_indexes("infrastructure_metrics")}
    assert indexes["ix_infrastructure_metrics_server_observed_desc"]["column_sorting"][
        "observed_at"
    ] == ("desc",)


def test_roundtrip_defaults_relationships_and_precision(db, graph):
    with Session(bind=db, join_transaction_mode="create_savepoint") as session:
        metric = session.get(InfrastructureMetric, graph["metric"])
        assert metric.estimated_cost == Decimal("0.00001234")
        assert metric.observed_at == NOW
        assert metric.observed_at.utcoffset() == timedelta(0)
        assert metric.ingested_at.tzinfo is not None
        assert isinstance(metric.server.id, UUID)
        assert metric.server.region.display_name == "US Central"
        assert metric.raw_telemetry.payload["unknown_provider_field"] == [1, 2]
        assert metric.etl_run.status == "QUEUED"
        assert metric.etl_run.records_extracted == 0


def test_timezone_offset_preserves_instant(db, graph):
    local = NOW.astimezone(timezone(timedelta(hours=-5)))
    db.execute(update(InfrastructureMetric).values(observed_at=local))
    assert db.scalar(select(InfrastructureMetric.observed_at)) == NOW


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_usage_percent", -1),
        ("cpu_usage_percent", 101),
        ("cpu_usage_percent", Decimal("NaN")),
        ("memory_usage_percent", 101),
        ("storage_usage_percent", -1),
        ("network_mbps", -1),
        ("network_mbps", Decimal("NaN")),
        ("network_mbps", Decimal("Infinity")),
        ("uptime_seconds", -1),
        ("estimated_cost", Decimal("-0.01")),
        ("estimated_cost", Decimal("NaN")),
        ("interval_seconds", 0),
        ("server_status", "UNKNOWN"),
        ("resource_health", "UNKNOWN"),
        ("currency", "usd"),
        ("estimated_cost", None),
        ("currency", None),
    ],
)
def test_invalid_metrics_are_rejected(db, graph, field, value):
    # Fixed-precision NUMERIC rejects infinity before CHECK evaluation.
    sqlstate = "22003" if value == Decimal("Infinity") else "23514"
    expect_failure(db, update(InfrastructureMetric).values({field: value}), sqlstate)


def test_optional_host_measurements_and_boundary_percentages(db, graph):
    db.execute(
        update(InfrastructureMetric).values(
            cpu_usage_percent=0,
            memory_usage_percent=100,
            network_mbps=None,
            uptime_seconds=None,
            estimated_cost=None,
            currency=None,
        )
    )
    assert db.scalar(select(InfrastructureMetric.estimated_cost)) is None


@pytest.mark.parametrize(
    "model,field",
    [
        (Region, "provider"),
        (Server, "server_name"),
        (RawTelemetry, "payload"),
        (InfrastructureMetric, "cpu_usage_percent"),
        (EtlRun, "source_id"),
    ],
)
def test_not_null_is_enforced(db, graph, model, field):
    expect_failure(db, update(model).values({field: None}), "23502")


@pytest.mark.parametrize(
    "model,field,value",
    [
        (Region, "region_code", " "),
        (Server, "source_id", ""),
        (Server, "environment", "qa"),
        (Server, "last_seen_at", NOW - timedelta(seconds=1)),
        (RawTelemetry, "source_event_id", " "),
        (EtlRun, "source_id", " "),
        (EtlRun, "status", "UNKNOWN"),
        (EtlRun, "requested_window_end", NOW),
        (EtlRun, "records_extracted", -1),
        (EtlRun, "records_accepted", 1),
        (EtlRun, "records_inserted", 1),
        (EtlRun, "records_duplicated", 1),
        (EtlRun, "records_rejected", 1),
        (EtlRun, "status", "SUCCEEDED"),
        (EtlRun, "status", "FAILED"),
        (EtlRun, "finished_at", NOW),
    ],
)
def test_inventory_and_run_checks(db, graph, model, field, value):
    expect_failure(db, update(model).values({field: value}), "23514")


def test_successful_run_requires_reconciled_counts(db, graph):
    statement = update(EtlRun).values(
        status="SUCCEEDED",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        records_extracted=4,
        records_accepted=3,
        records_rejected=1,
        records_inserted=1,
        records_duplicated=1,
    )
    expect_failure(db, statement, "23514")
    db.execute(statement.values(records_duplicated=2))


def test_duplicate_region(db, graph):
    expect_failure(
        db,
        insert(Region).values(provider="simulated", region_code="us-central", display_name="Other"),
        "23505",
    )


def test_duplicate_server_identity(db, graph):
    values = dict(db.execute(select(Server.__table__)).mappings().one())
    values.pop("id")
    expect_failure(db, insert(Server).values(**values), "23505")


def test_duplicate_source_event_across_runs(db, graph):
    run = add(
        db,
        EtlRun,
        source_id="simulated-cloud",
        requested_window_start=NOW,
        requested_window_end=NOW + timedelta(minutes=1),
    )
    expect_failure(
        db,
        insert(RawTelemetry).values(
            source_id="simulated-cloud", source_event_id="event-001", etl_run_id=run, payload={}
        ),
        "23505",
    )
    # Identical provider event IDs in a different source are distinct.
    add(
        db,
        RawTelemetry,
        source_id="other-collector",
        source_event_id="event-001",
        etl_run_id=run,
        payload={},
    )


def test_duplicate_observation_with_different_event(db, graph):
    raw = add(
        db,
        RawTelemetry,
        source_id="simulated-cloud",
        source_event_id="event-002",
        etl_run_id=graph["run"],
        payload={},
    )
    values = dict(db.execute(select(InfrastructureMetric.__table__)).mappings().one())
    values.pop("id")
    values["raw_telemetry_id"] = raw
    expect_failure(db, insert(InfrastructureMetric).values(**values), "23505")


def test_raw_event_cannot_create_second_metric(db, graph):
    values = dict(db.execute(select(InfrastructureMetric.__table__)).mappings().one())
    values.pop("id")
    values["observed_at"] += timedelta(seconds=30)
    expect_failure(db, insert(InfrastructureMetric).values(**values), "23505")


@pytest.mark.parametrize(
    "model,field",
    [
        (Server, "region_id"),
        (RawTelemetry, "etl_run_id"),
        (InfrastructureMetric, "server_id"),
        (InfrastructureMetric, "etl_run_id"),
    ],
)
def test_missing_uuid_parents_fail(db, graph, model, field):
    expect_failure(db, update(model).values({field: uuid4()}), "23503")


def test_missing_raw_parent_fails(db, graph):
    expect_failure(db, update(InfrastructureMetric).values(raw_telemetry_id=-1), "23503")


@pytest.mark.parametrize("model", [Region, Server, EtlRun, RawTelemetry])
def test_parent_deletion_preserves_history(db, graph, model):
    expect_failure(db, delete(model), "23503")
    assert db.scalar(select(InfrastructureMetric.id)) == graph["metric"]


@pytest.mark.parametrize("errors", [[], {}, "invalid", None])
def test_rejections_require_nonempty_errors(db, graph, errors):
    expect_failure(
        db,
        insert(DataQualityRejection).values(
            etl_run_id=graph["run"],
            raw_telemetry_id=graph["raw"],
            error_code="INVALID_CPU",
            validation_errors=errors,
        ),
        "23502" if errors is None else "23514",
    )


def test_rejection_attempt_identity_and_history(db, graph):
    values = {
        "etl_run_id": graph["run"],
        "raw_telemetry_id": graph["raw"],
        "error_code": "INVALID_CPU",
        "validation_errors": [{"field": "cpu"}],
    }
    add(db, DataQualityRejection, **values)
    expect_failure(db, insert(DataQualityRejection).values(**values), "23505")
    next_run = add(
        db,
        EtlRun,
        source_id="simulated-cloud",
        requested_window_start=NOW,
        requested_window_end=NOW + timedelta(minutes=1),
    )
    add(db, DataQualityRejection, **{**values, "etl_run_id": next_run})


def test_ingestion_progress_roundtrip_and_identity(db, graph):
    db.execute(update(EtlRun).values(status="SUCCEEDED", started_at=NOW, finished_at=NOW))
    values = {
        "source_id": "simulated-cloud",
        "cursor": {"page": "opaque-token"},
        "watermark": NOW,
        "last_successful_run_id": graph["run"],
    }
    db.execute(insert(IngestionState).values(**values))
    expect_failure(db, insert(IngestionState).values(**values), "23505")
    expect_failure(db, update(IngestionState).values(last_successful_run_id=uuid4()), "23503")
    expect_failure(db, update(IngestionState).values(source_id=" "), "23514")
    with Session(bind=db, join_transaction_mode="create_savepoint") as session:
        state = session.get(IngestionState, "simulated-cloud")
        assert state.cursor == {"page": "opaque-token"}
        assert state.watermark == NOW
        assert state.last_successful_run.status == "SUCCEEDED"


def test_new_source_can_have_no_progress(db):
    db.execute(insert(IngestionState).values(source_id="host-local"))
    assert db.scalar(select(IngestionState.watermark)) is None
