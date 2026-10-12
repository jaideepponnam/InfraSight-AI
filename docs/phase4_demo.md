# Phase 4 business analytics demonstration

## Run against actual PostgreSQL

Use InfraSight-AI PostgreSQL at localhost:55432. Keep existing Windows services on 5432/5433 untouched.

    .\.venv\Scripts\alembic.exe upgrade head
    .\.venv\Scripts\python.exe scripts\phase4_demo.py

The script queries existing simulated-cloud data with the shared service. It adds only two three-minute windows under simulated-cloud-phase4-comparison (75 servers, 450 observations each, no malformed events) to demonstrate comparable costs without generating whole days of unnecessary telemetry. Repeating the script replays those windows idempotently; it never clears inventory or resets progress.

Complete results/parameters are saved to .uv-cache/phase4-demo.json (ignored). The console shows a compact business summary. Reference for historical questions: 2026-10-11T19:33:00Z; selected original window: [19:30,19:33) UTC. Current health uses actual wall-clock time.

## Exact inspectable SQL

Open the project database:

    docker compose exec postgres psql -U infrasight -d infrasight

Views need no custom settings. Example parameterized inspection statements:

    PREPARE current_health(text) AS
    SELECT effective_health, COUNT(*) AS servers
    FROM analytics.server_health_summary WHERE source_id = $1
    GROUP BY effective_health ORDER BY effective_health;
    EXECUTE current_health('simulated-cloud');

    PREPARE latest_cpu(text) AS
    SELECT external_server_id, cpu_usage_percent, observed_at, interval_end, freshness
    FROM analytics.latest_server_metrics WHERE source_id = $1
    ORDER BY cpu_usage_percent DESC NULLS LAST, server_id LIMIT 5;
    EXECUTE latest_cpu('simulated-cloud');

    PREPARE breaches(text, timestamptz, timestamptz, numeric) AS
    SELECT external_server_id, MAX(cpu_usage_percent) AS peak_cpu,
           COUNT(*) FILTER (WHERE cpu_usage_percent > $4) AS breaches
    FROM analytics.high_resource_usage
    WHERE source_id = $1 AND observed_at >= $2 AND observed_at < $3 AND interval_end <= $3
    GROUP BY server_id, external_server_id
    HAVING COUNT(*) FILTER (WHERE cpu_usage_percent > $4) > 0
    ORDER BY peak_cpu DESC, external_server_id;
    EXECUTE breaches('simulated-cloud', '2026-10-11T19:30:00Z', '2026-10-11T19:33:00Z', 80);

    PREPARE day_cost(text, date, text) AS
    SELECT external_server_id, SUM(estimated_cost) AS estimated_cost, currency
    FROM analytics.daily_cloud_cost_summary
    WHERE source_id = $1 AND utc_day = $2 AND currency = $3
    GROUP BY server_id, external_server_id, currency ORDER BY estimated_cost DESC NULLS LAST;
    EXECUTE day_cost('simulated-cloud', '2026-10-11', 'USD');

    PREPARE regional_snapshot(text) AS
    SELECT region_code, environment, currency, reporting_server_count,
           healthy_server_count, warning_server_count, critical_server_count,
           stale_server_count, latest_interval_estimated_cost, cost_basis
    FROM analytics.region_usage_summary WHERE source_id = $1
    ORDER BY region_code, environment, currency;
    EXECUTE regional_snapshot('simulated-cloud');

For historical/custom freshness, pressure, optimization, and comparisons, inspect the exact bound SQL constants in src/infrasight/analytics/repository.py. scripts/phase4_demo.py invokes them with these explicit models:

- Scope(as_of=19:33 UTC, source_id=simulated-cloud, freshness_seconds=120).
- CpuThreshold(start=19:30, end=19:33, as_of=19:33, cpu_threshold=80).
- Underutilization(same window, min_samples=4, min_coverage=0.8, max_cpu=10, max_memory=20, min_cost=0.01, currency=USD).
- Pressure(same window, min_samples=4, min_coverage=0.8, min_breach_fraction=0.5).
- Comparison(current=Oct 11 19:30..19:33, previous=Oct 10 19:30..19:33, currency=USD) on the isolated comparison source.

No runtime parameter is smuggled into a connection setting.

## Recorded actual business results

Original source simulated-cloud, historical snapshot 2026-10-11T19:33:00Z:

- Inventory/reporting: 75/75. Healthy 64, warning 1, critical 10.
- Wall-clock inspection: all 75 stale; no falsely current HEALTHY servers.
- Top latest CPU: sim-049 62.46%, sim-056 62.24%, sim-042 61.71%, sim-063 61.17%, sim-035 60.37%.
- Above-80 history: 11 servers, 43 observations. Largest peak: sim-044, 96.99%.
- Highest selected-window cost: sim-075, USD 0.05990589.
- Observed fleet interval cost: USD 1.03775797 over 446 priced observations. Telemetry coverage is 99.11111111% of scoped fleet-time. Four rejected intervals explain missing coverage; there is no extrapolation to a full bill.

| Region | Healthy | Warning | Critical | Reporting |
|---|---:|---:|---:|---:|
| eu-de | 21 | 0 | 4 | 25 |
| us-east | 22 | 0 | 3 | 25 |
| us-south | 21 | 1 | 3 | 25 |

Short-window optimization policy returns 10 candidates: sim-075, sim-012, sim-033, sim-054, sim-068, sim-005, sim-026, sim-047, sim-061, sim-040. Each has full observed coverage in this window and low CPU/memory; no guaranteed savings or automatic shutdown is claimed. The normal 24-hour/20-sample assessment returns zero, correctly reflecting insufficient history.

Short-window CPU pressure returns 11 servers. Ten breached in 4/6 observations (66.67%); sim-044 breached in 3/5 (60%) with one rejected interval. Latest CPU below 80% does not contradict earlier pressure: latest and period-wide questions use different evidence.

Isolated complete comparison source:

| Period | Estimated USD cost | Coverage |
|---|---:|---:|
| Oct 10, 19:30..19:33 UTC | 1.18124211 | 100% |
| Oct 11, 19:30..19:33 UTC | 1.05479934 | 100% |

Difference: -0.12644277 USD; change: -10.70422134%, a comparable DECREASE. Broad today/full-yesterday mode returns UNEQUAL_DURATION; broad equivalent-elapsed day mode returns INSUFFICIENT_COVERAGE because the fixture only covers three minutes. Neither broad comparison invents a reliable percentage.

## Query-plan workbench

    .\.venv\Scripts\python.exe scripts\phase4_explain.py

Creates a uniquely named disposable database, applies migrations, ingests 9,000 clean observations (75 servers x 120 intervals), verifies latest-row strategies agree, runs warmed EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON), saves .uv-cache/phase4-plans.json, and removes only its own database. Actual measurements and index rationale are in docs/analytics_query_plans.md.

## Verification commands

    $env:TEST_DATABASE_URL = (Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    .\.venv\Scripts\python.exe -m pytest -q tests/integration/test_analytics_views.py tests/integration/test_analytics_queries.py tests/integration/test_analytics_security.py tests/integration/test_analytics_migrations.py
    .\.venv\Scripts\python.exe -m pytest -q
    Remove-Item Env:TEST_DATABASE_URL
    .\.venv\Scripts\ruff.exe check .
    .\.venv\Scripts\ruff.exe format --check .
    .\.venv\Scripts\alembic.exe current
    .\.venv\Scripts\alembic.exe check

Downgrade/re-upgrade tests target disposable databases and preserve base data. Never downgrade the application database just to run tests. No production reader credentials are introduced by this phase.

Final verification: migration head 0002 applied; all 28 analytics integration tests and all 179 project tests passed. Ruff lint/format passed. One existing third-party Starlette/AnyIO deprecation warning remains. Rerunning the comparison fixture inserted zero metrics and detected 450 duplicates per window; monetary answers remained unchanged.
