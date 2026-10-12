from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from infrasight.analytics.repository import AnalyticsRepository
from infrasight.analytics.schemas import (
    CpuThreshold,
    Pressure,
    Scope,
    Underutilization,
    Window,
)
from infrasight.analytics.services import AnalyticsService

pytestmark = pytest.mark.integration


def window(data, **values):
    return dict(
        source_id="fixture",
        start=data.start,
        end=data.start + timedelta(seconds=120),
        as_of=data.start + timedelta(seconds=120),
        **values,
    )


def test_historical_health_counts_and_exact_freshness_boundary(analytics_db, analytics_data):
    data = analytics_data
    a, b = data.server("healthy"), data.server("critical")
    data.server("no-data")
    data.metric(a)
    data.metric(b, observed=data.start + timedelta(seconds=30), cpu="95", health="CRITICAL")
    service = AnalyticsService(analytics_db)
    query = Scope(
        as_of=data.start + timedelta(seconds=90), freshness_seconds=60, source_id="fixture"
    )
    totals = service.fleet_totals(query).rows[0]
    assert (
        totals["inventory_servers"],
        totals["reporting_servers"],
        totals["healthy_servers"],
        totals["critical_servers"],
        totals["no_data_servers"],
    ) == (3, 2, 1, 1, 1)
    older = query.model_copy(update={"freshness_seconds": 59})
    assert service.fleet_totals(older).rows[0]["stale_servers"] == 1
    assert service.critical_servers(query).rows[0]["server_id"] == b
    # Reference before the critical interval finishes must not use future interval data.
    early = query.model_copy(update={"as_of": data.start + timedelta(seconds=50)})
    assert service.fleet_totals(early).rows[0]["critical_servers"] == 0


def test_strict_cpu_threshold_rankings_and_regional_health(analytics_db, analytics_data):
    data = analytics_data
    a, b = data.server("a"), data.server("b", region="eu-de")
    data.metric(a, cpu="80", health="WARNING")
    data.metric(a, observed=data.start + timedelta(seconds=30), cpu="81", health="WARNING")
    data.metric(b, cpu="95", memory="96", health="CRITICAL")
    service = AnalyticsService(analytics_db)
    query = Scope(as_of=data.start + timedelta(seconds=60), source_id="fixture")
    assert service.top_cpu(query).rows[0]["server_id"] == b
    assert service.top_memory(query).rows[0]["server_id"] == b
    breaches = service.high_cpu_breaches(CpuThreshold(**window(data))).rows
    assert {r["server_id"]: r["breach_count"] for r in breaches} == {a: 1, b: 1}
    regions = service.regional_health(query).rows
    assert regions[0]["region_code"] == "eu-de" and regions[0]["critical_servers"] == 1


def test_underutilized_candidates_require_samples_coverage_health_and_price(
    analytics_db, analytics_data
):
    data = analytics_data
    good = data.server("good")
    short = data.server("short")
    critical = data.server("critical")
    expensive_memory = data.server("memory-at-threshold")
    cheap = data.server("cheap")
    unpriced = data.server("unpriced")
    for i in range(4):
        observed = data.start + timedelta(seconds=30 * i)
        data.metric(good, observed=observed, cpu="5", memory="10")
        if i < 3:
            data.metric(short, observed=observed, cpu="5", memory="10")
        data.metric(
            critical,
            observed=observed,
            cpu="5",
            memory="10",
            health="CRITICAL" if i == 1 else "HEALTHY",
        )
        data.metric(expensive_memory, observed=observed, cpu="5", memory="20")
        data.metric(cheap, observed=observed, cpu="5", memory="10", cost="0.001")
        data.metric(unpriced, observed=observed, cpu="5", memory="10", cost=None, currency=None)
    report = AnalyticsService(analytics_db).underutilized(
        Underutilization(**window(data), min_samples=4)
    )
    assert [r["server_id"] for r in report.rows] == [good]
    assert report.rows[0]["coverage_fraction"] == 1
    assert report.rows[0]["estimated_cost"] == 4
    assert report.rows[0]["recommendation_type"] == "OPTIMIZATION_CANDIDATE"
    assert report.warnings


def test_interval_union_does_not_inflate_coverage_and_overlap_is_excluded(
    analytics_db, analytics_data
):
    data = analytics_data
    server = data.server("overlap")
    for offset in (0, 10, 20, 30):
        data.metric(server, observed=data.start + timedelta(seconds=offset), cpu="5", memory="10")
    query = Underutilization(**window(data), min_samples=4, min_coverage=Decimal("0.4"))
    repository = AnalyticsRepository(analytics_db)
    from infrasight.analytics.repository import WINDOW_CTES

    stats = repository.rows("WITH " + WINDOW_CTES + "SELECT * FROM stats", query)[0]
    assert stats["coverage_seconds"] == 60 and stats["summed_observation_seconds"] == 120
    assert stats["coverage_fraction"] == Decimal("0.5") and stats["overlap_detected"]
    assert not AnalyticsService(analytics_db).underutilized(query).rows
    assert AnalyticsService(analytics_db).fleet_costs(query).warnings


def test_cpu_pressure_percentage_minimum_samples_and_coverage(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    for i, cpu in enumerate(("80", "81", "95", "81")):
        data.metric(
            server,
            observed=data.start + timedelta(seconds=i * 30),
            cpu=cpu,
            health="CRITICAL" if cpu == "95" else "WARNING",
        )
    service = AnalyticsService(analytics_db)
    query = Pressure(**window(data), min_samples=4)
    row = service.sustained_cpu_pressure(query).rows[0]
    assert row["breach_count"] == 3 and row["breach_fraction"] == Decimal("0.75")
    assert row["coverage_fraction"] == 1
    assert not service.sustained_cpu_pressure(query.model_copy(update={"min_samples": 5})).rows
    assert not service.sustained_cpu_pressure(
        query.model_copy(update={"min_breach_fraction": Decimal("0.8")})
    ).rows


def test_coverage_boundary_inclusive(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    for i in range(4):
        data.metric(
            server,
            observed=data.start + timedelta(seconds=i * 24),
            seconds=24,
            cpu="5",
            memory="10",
        )
    service = AnalyticsService(analytics_db)
    query = Underutilization(**window(data), min_samples=4)
    assert service.underutilized(query).rows[0]["coverage_fraction"] == Decimal("0.8")
    assert not service.underutilized(
        query.model_copy(update={"min_coverage": Decimal("0.81")})
    ).rows


def test_cost_ranking_mixed_currencies_null_and_clipped_interval(analytics_db, analytics_data):
    data = analytics_data
    a, b, c, d = (data.server(name) for name in ("usd-low", "usd-high", "eur", "unknown"))
    data.metric(a, seconds=120, cost="1.00000001")
    data.metric(b, seconds=120, cost="2")
    data.metric(c, seconds=120, cost="99", currency="EUR")
    data.metric(d, seconds=120, cost=None, currency=None)
    service = AnalyticsService(analytics_db)
    query = Window(**window(data))
    rows = service.fleet_costs(query).rows
    assert all(row["telemetry_coverage_fraction"] == 1 for row in rows)
    assert {r["currency"]: r["estimated_cost"] for r in rows} == {
        "USD": Decimal("3.00000001"),
        "EUR": Decimal(99),
        None: None,
    }
    assert (
        service.highest_cost_servers(query.model_copy(update={"currency": "USD"})).rows[0][
            "server_id"
        ]
        == b
    )
    clipped = query.model_copy(
        update={"end": data.start + timedelta(seconds=60), "currency": "USD"}
    )
    assert service.fleet_costs(clipped).rows[0]["estimated_cost"] == Decimal("1.500000005")
    with pytest.raises(ValueError):
        service.highest_cost_servers(query)


@pytest.mark.parametrize(
    "baseline,current,direction,percentage",
    [
        ("10", "12", "INCREASE", Decimal(20)),
        ("10", "8", "DECREASE", Decimal(-20)),
        ("0", "1", "INCREASE_FROM_ZERO", None),
        ("0", "0", "UNCHANGED", None),
    ],
)
def test_exact_cost_comparison_and_zero_baseline(
    analytics_db, analytics_data, baseline, current, direction, percentage
):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=60, cost=baseline)
    today = data.start + timedelta(days=1)
    data.metric(server, observed=today, seconds=60, cost=current)
    scope = Scope(as_of=today + timedelta(seconds=60), source_id="fixture")
    row = AnalyticsService(analytics_db).compare_today(scope).rows[0]
    assert row["quality"] == "COMPARABLE" and row["direction"] == direction
    assert row["percentage_change"] == percentage
    assert row["current"]["estimated_cost"] == Decimal(current)
    assert isinstance(row["current"]["observation_count"], int)


def test_incomplete_and_unequal_periods_do_not_claim_increase(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=30, cost="1")
    today = data.start + timedelta(days=1)
    data.metric(server, observed=today, seconds=30, cost="2")
    service = AnalyticsService(analytics_db)
    scope = Scope(as_of=today + timedelta(seconds=60), source_id="fixture")
    row = service.compare_today(scope).rows[0]
    assert row["quality"] == "INSUFFICIENT_COVERAGE" and row["percentage_change"] is None
    assert row["direction"] == "UNDETERMINED"
    assert (
        service.compare_today(scope, equivalent_elapsed=False).rows[0]["quality"]
        == "UNEQUAL_DURATION"
    )


def test_completed_day_comparison(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=86400, cost="10")
    data.metric(server, observed=data.start + timedelta(days=1), seconds=86400, cost="15")
    scope = Scope(as_of=data.start + timedelta(days=2), source_id="fixture")
    row = AnalyticsService(analytics_db).compare_completed_days(scope).rows[0]
    assert row["quality"] == "COMPARABLE" and row["percentage_change"] == 50


def test_missing_cost_is_not_zero(analytics_db, analytics_data):
    data = analytics_data
    server = data.server()
    data.metric(server, seconds=60, cost=None, currency=None)
    today = data.start + timedelta(days=1)
    data.metric(server, observed=today, seconds=60, cost="2")
    scope = Scope(as_of=today + timedelta(seconds=60), source_id="fixture")
    row = AnalyticsService(analytics_db).compare_today(scope).rows[0]
    assert row["quality"] == "UNKNOWN_COST" and row["difference"] is None


def test_bound_filter_cannot_inject_sql_or_affect_other_queries(analytics_db, analytics_data):
    data = analytics_data
    data.metric(data.server())
    service = AnalyticsService(analytics_db)
    query = Scope(as_of=data.start + timedelta(seconds=60), source_id="fixture")
    assert service.fleet_totals(query).rows[0]["inventory_servers"] == 1
    injected = query.model_copy(update={"source_id": "fixture' OR true; DROP TABLE servers; --"})
    assert service.fleet_totals(injected).rows[0]["inventory_servers"] == 0
    assert service.fleet_totals(query).rows[0]["inventory_servers"] == 1
    assert analytics_db.scalar(text("SELECT COUNT(*) FROM public.servers")) == 1


def test_replay_does_not_change_analytics(etl_engine, settings):
    from datetime import UTC, datetime
    from uuid import uuid4

    from infrasight.ingestion.pipeline import ETLPipeline
    from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource

    source_id = "analytics-replay-" + uuid4().hex
    source = SimulatedCloudTelemetrySource(5, malformed_rate=0, source_id=source_id)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    pipeline = ETLPipeline(etl_engine, settings)
    service = AnalyticsService(etl_engine)
    query = Window(source_id=source_id, start=start, end=end, as_of=end, currency="USD")
    assert pipeline.run_cycle(source, start, end).status == "SUCCEEDED"
    first = service.fleet_costs(query).rows
    assert pipeline.run_cycle(source, start, end).counts.inserted == 0
    assert service.fleet_costs(query).rows == first


def test_explain_executes_real_bounded_analytics(analytics_db, analytics_data):
    from infrasight.analytics.repository import TOTALS_SQL

    data = analytics_data
    data.metric(data.server())
    query = Scope(as_of=data.start + timedelta(seconds=30), source_id="fixture")
    plan = analytics_db.scalar(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + TOTALS_SQL),
        AnalyticsRepository.parameters(query),
    )[0]
    assert plan["Plan"]["Actual Rows"] == 1
    assert plan["Execution Time"] >= 0


def test_service_timestamps_are_utc_even_in_another_session_timezone(analytics_db, analytics_data):
    from datetime import UTC

    data = analytics_data
    data.metric(data.server())
    analytics_db.execute(
        text("SELECT set_config('TimeZone', :zone, true)"), {"zone": "America/New_York"}
    )
    row = (
        AnalyticsService(analytics_db)
        .health(Scope(source_id="fixture", as_of=data.start + timedelta(seconds=30)))
        .rows[0]
    )
    assert row["observed_at"].tzinfo == UTC
    assert row["observed_at"] == data.start
