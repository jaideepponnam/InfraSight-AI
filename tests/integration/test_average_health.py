from datetime import timedelta
from decimal import Decimal

from infrasight.analytics.schemas import Window
from infrasight.analytics.services import AnalyticsService


def query(data):
    return Window(
        source_id="fixture",
        start=data.start,
        end=data.start + timedelta(seconds=120),
        as_of=data.start + timedelta(hours=1),
    )


def test_average_health_duration_weighted_not_current_counts(analytics_data):
    data = analytics_data
    server = data.server()
    data.server("no-data")
    data.metric(server, seconds=90, health="HEALTHY")
    data.metric(server, observed=data.start + timedelta(seconds=90), seconds=30, health="WARNING")
    service = AnalyticsService(data.db)
    report = service.average_health(query(data))
    fleet = next(r for r in report.rows if r["scope_kind"] == "fleet")
    assert fleet["healthy_fraction"] == Decimal("0.75")
    assert fleet["warning_fraction"] == Decimal("0.25")
    assert fleet["critical_fraction"] == 0
    assert fleet["coverage_fraction"] == Decimal("0.5")
    live = service.fleet_totals(query(data)).rows[0]
    assert live["healthy_servers"] == 0
    assert live["stale_servers"] == 1
    assert live["no_data_servers"] == 1
    region = next(r for r in report.rows if r["scope_kind"] == "region")
    assert region["healthy_fraction"] == fleet["healthy_fraction"]


def test_average_health_empty_is_unknown(analytics_data):
    data = analytics_data
    data.server()
    fleet = AnalyticsService(data.db).average_health(query(data)).rows[0]
    assert fleet["observation_count"] == 0
    assert fleet["healthy_fraction"] is None
    assert fleet["coverage_fraction"] == 0


def test_average_health_overlap_is_not_presented_as_reliable(analytics_data):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=90, health="HEALTHY")
    data.metric(server, observed=data.start + timedelta(seconds=30), seconds=90, health="CRITICAL")
    report = AnalyticsService(data.db).average_health(query(data))
    fleet = next(r for r in report.rows if r["scope_kind"] == "fleet")
    assert fleet["health_overlap_detected"]
    assert fleet["healthy_fraction"] is None
    assert report.warnings


def test_average_health_clips_window_and_filters_source(analytics_data):
    data = analytics_data
    server = data.server()
    other = data.server("other", source="other")
    data.metric(server, seconds=90, health="HEALTHY")
    data.metric(server, observed=data.start + timedelta(seconds=90), seconds=30, health="CRITICAL")
    data.metric(other, seconds=120, health="WARNING")
    selected = query(data).model_copy(update={"start": data.start + timedelta(seconds=60)})
    fleet = next(
        r
        for r in AnalyticsService(data.db).average_health(selected).rows
        if r["scope_kind"] == "fleet"
    )
    assert fleet["healthy_fraction"] == Decimal("0.5")
    assert fleet["critical_fraction"] == Decimal("0.5")
    assert fleet["warning_fraction"] == 0
