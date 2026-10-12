"""Measure analytics plans on a bounded, disposable 9,000-observation fleet."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from infrasight.analytics.repository import (
    BREACH_SQL,
    HEALTH_CTES,
    TOP_COST_SQL,
    AnalyticsRepository,
)
from infrasight.analytics.schemas import CpuThreshold
from infrasight.config import get_settings
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.logging import configure_logging

DISTINCT_SQL = """
SELECT DISTINCT ON (server_id) server_id, observed_at, cpu_usage_percent
FROM analytics.high_resource_usage
WHERE source_id = :source_id AND observed_at <= CAST(:as_of AS timestamptz)
  AND interval_end <= CAST(:as_of AS timestamptz)
ORDER BY server_id, observed_at DESC
"""
LATERAL_SQL = "WITH " + HEALTH_CTES + "SELECT server_id, observed_at, cpu_usage_percent FROM health"
# Date conversion is explicit; no session timezone dependence.
DAILY_SQL = """
SELECT * FROM analytics.daily_infrastructure_summary
WHERE source_id = :source_id AND utc_day = (CAST(:start AS timestamptz) AT TIME ZONE 'UTC')::date
"""


def main():
    settings = get_settings()
    configure_logging(settings.log_level)
    admin = create_engine(
        settings.database_url.get_secret_value(),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
    name = "infrasight_plan_" + uuid4().hex
    engine, created = None, False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created = True
        engine = create_engine(
            make_url(settings.database_url.get_secret_value()).set(database=name),
            connect_args={"connect_timeout": 3},
            hide_parameters=True,
        )
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0002")
        start = datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
        end = start + timedelta(hours=1)
        result = ETLPipeline(engine, settings).run_cycle(
            SimulatedCloudTelemetrySource(75, malformed_rate=0, source_id="plan-fleet"), start, end
        )
        if result.status != "SUCCEEDED" or result.counts.inserted != 9000:
            raise RuntimeError("Representative telemetry fixture failed")
        query = CpuThreshold(
            source_id="plan-fleet", start=start, end=end, as_of=end, currency="USD", limit=20
        )
        reports = {}
        with engine.begin() as connection:
            connection.execute(text("ANALYZE"))
            lateral = connection.execute(
                text(LATERAL_SQL), AnalyticsRepository.parameters(query)
            ).all()
            distinct = connection.execute(
                text(DISTINCT_SQL), AnalyticsRepository.parameters(query)
            ).all()
            if sorted(lateral) != sorted(distinct):
                raise RuntimeError("Latest-row benchmark strategies disagree")
            cases = {
                "latest_lateral": (LATERAL_SQL, query),
                "latest_distinct_on": (DISTINCT_SQL, query),
                "high_cpu_last_five_minutes": (
                    BREACH_SQL,
                    query.model_copy(update={"start": end - timedelta(minutes=5)}),
                ),
                "cost_ranking_one_hour": (TOP_COST_SQL, query),
                "daily_summary": (DAILY_SQL, query),
            }
            for label, (statement, parameters) in cases.items():
                # First execution warms the fixture; report the second full plan.
                explain = text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement)
                connection.execute(explain, AnalyticsRepository.parameters(parameters)).scalar_one()
                reports[label] = connection.execute(
                    explain, AnalyticsRepository.parameters(parameters)
                ).scalar_one()[0]
        output = {"fixture": result.as_dict(), "plans": reports, "new_indexes_added": False}
        target = Path(".uv-cache/phase4-plans.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, default=str, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "observations": 9000,
                    "plans": {
                        label: {
                            "execution_ms": p["Execution Time"],
                            "planning_ms": p["Planning Time"],
                            "actual_rows": p["Plan"]["Actual Rows"],
                            "shared_hit_blocks": p["Plan"].get("Shared Hit Blocks", 0),
                        }
                        for label, p in reports.items()
                    },
                },
                indent=2,
            )
        )
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
