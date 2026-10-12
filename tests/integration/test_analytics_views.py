from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_latest_row_and_stale_health_with_inventory_without_data(analytics_db, analytics_data):
    data = analytics_data
    server = data.server("observed")
    data.server("unobserved")
    data.metric(server, cpu="15")
    latest = data.metric(server, observed=data.start + timedelta(seconds=30), cpu="30")
    rows = (
        analytics_db.execute(
            text("SELECT * FROM analytics.latest_server_metrics ORDER BY server_name")
        )
        .mappings()
        .all()
    )
    assert rows[0]["metric_id"] == latest and rows[0]["cpu_usage_percent"] == Decimal("30")
    assert rows[0]["freshness"] == "STALE" and rows[1]["freshness"] == "NO_DATA"
    health = (
        analytics_db.execute(
            text("SELECT * FROM analytics.server_health_summary ORDER BY server_name")
        )
        .mappings()
        .all()
    )
    assert health[0]["recorded_resource_health"] == "HEALTHY"
    assert health[0]["effective_health"] == "STALE" and health[1]["effective_health"] == "NO_DATA"


def test_wall_clock_view_default_is_visible_not_session_config(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    now = analytics_db.scalar(text("SELECT statement_timestamp()"))
    data.metric(server, observed=now - timedelta(seconds=40), seconds=30)
    row = (
        analytics_db.execute(text("SELECT * FROM analytics.latest_server_metrics")).mappings().one()
    )
    assert row["freshness_threshold_seconds"] == 120 and row["is_current"]
    assert 0 <= row["completion_age_seconds"] < 20
    assert (
        analytics_db.scalar(text("SELECT effective_health FROM analytics.server_health_summary"))
        == "HEALTHY"
    )


@pytest.mark.parametrize("timezone", ["UTC", "America/New_York", "Pacific/Apia"])
def test_cross_midnight_exact_cost_and_utc_day(analytics_db, analytics_data, timezone):
    data = analytics_data
    server = data.server()
    data.metric(
        server, observed=datetime(2026, 1, 1, 23, 59, 45, tzinfo=UTC), seconds=30, cost="1.00000001"
    )
    analytics_db.execute(text("SELECT set_config('TimeZone', :zone, true)"), {"zone": timezone})
    rows = analytics_db.execute(
        text(
            "SELECT utc_day, estimated_cost FROM analytics.daily_cloud_cost_summary "
            "ORDER BY utc_day"
        )
    ).all()
    assert (
        len(rows) == 2
        and str(rows[0].utc_day) == "2026-01-01"
        and str(rows[1].utc_day) == "2026-01-02"
    )
    assert rows[0].estimated_cost == Decimal("0.500000005")
    assert sum(r.estimated_cost for r in rows) == Decimal("1.00000001")


def test_duration_weighted_resources_null_network_and_unknown_cost(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=30, cpu="10", cost=None, currency=None, network=None)
    data.metric(
        server,
        observed=data.start + timedelta(seconds=30),
        seconds=90,
        cpu="90",
        cost=None,
        currency=None,
        network=Decimal("8"),
        health="CRITICAL",
    )
    row = (
        analytics_db.execute(text("SELECT * FROM analytics.daily_infrastructure_summary"))
        .mappings()
        .one()
    )
    assert row["average_cpu_percent"] == Decimal("70")
    assert row["average_network_mbps"] == Decimal("8")
    assert row["estimated_cost"] is None and row["priced_observation_count"] == 0
    assert row["observation_count"] == 2 and row["critical_observations"] == 1


def test_cost_grouping_keeps_currencies_separate(analytics_db, analytics_data):
    data = analytics_data
    a, b = data.server("usd"), data.server("eur", region="eu-de")
    data.metric(a, cost="2", currency="USD")
    data.metric(b, cost="3", currency="EUR")
    rows = (
        analytics_db.execute(
            text(
                "SELECT currency, SUM(estimated_cost) AS cost FROM "
                "analytics.daily_cloud_cost_summary GROUP BY currency"
            )
        )
        .mappings()
        .all()
    )
    assert {r["currency"]: r["cost"] for r in rows} == {"USD": Decimal(2), "EUR": Decimal(3)}
    assert analytics_db.scalar(text("SELECT COUNT(*) FROM analytics.region_usage_summary")) == 2


def test_public_views_exclude_internal_sensitive_columns(analytics_db):
    views = (
        "latest_server_metrics",
        "server_health_summary",
        "high_resource_usage",
        "daily_infrastructure_summary",
        "daily_cloud_cost_summary",
        "region_usage_summary",
    )
    for view in views:
        columns = (
            analytics_db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE "
                    "table_schema='analytics' AND table_name=:name"
                ),
                {"name": view},
            )
            .scalars()
            .all()
        )
        assert columns and not set(columns) & {
            "payload",
            "validation_errors",
            "error_message",
            "error_details",
            "raw_telemetry_id",
            "etl_run_id",
        }
        definition = analytics_db.scalar(
            text("SELECT pg_get_viewdef(CAST(:view AS regclass), true)"),
            {"view": "analytics." + view},
        )
        assert "current_setting" not in definition and "set_config" not in definition
