"""Run actual PostgreSQL business questions; never hardcode analytical answers."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infrasight.analytics.schemas import (
    Comparison,
    CpuThreshold,
    Pressure,
    Scope,
    Underutilization,
    Window,
)
from infrasight.analytics.services import AnalyticsService
from infrasight.config import get_settings
from infrasight.db.session import create_database_engine
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.logging import configure_logging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", default="simulated-cloud")
    parser.add_argument("--comparison-source", default="simulated-cloud-phase4-comparison")
    parser.add_argument("--output", type=Path, default=Path(".uv-cache/phase4-demo.json"))
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    try:
        service = AnalyticsService(engine, settings)
        start = datetime(2026, 10, 11, 19, 30, tzinfo=UTC)
        end = start + timedelta(minutes=3)
        historical = Scope(source_id=args.source_id, as_of=end, limit=100)
        rank = historical.model_copy(update={"limit": 5})
        period = dict(source_id=args.source_id, start=start, end=end, as_of=end, limit=100)
        reports = {
            "current_health": service.fleet_totals(service.scope(source_id=args.source_id)),
            "historical_health": service.fleet_totals(historical),
            "top_cpu": service.top_cpu(rank),
            "top_memory": service.top_memory(rank),
            "high_cpu_breaches": service.high_cpu_breaches(CpuThreshold(**period)),
            "highest_cost": service.highest_cost_servers(Window(**period, currency="USD")),
            "fleet_cost": service.fleet_costs(Window(**period)),
            "regional_health": service.regional_health(historical),
            "underutilized_short_demo": service.underutilized(
                Underutilization(**period, min_samples=4)
            ),
            "underutilized_default": service.underutilized(
                Underutilization(
                    source_id=args.source_id, start=end - timedelta(days=1), end=end, as_of=end
                )
            ),
            "sustained_cpu_short_demo": service.sustained_cpu_pressure(
                Pressure(**period, min_samples=4)
            ),
        }
        # Only 2 x 3-minute windows, with a separate source ID. No inventory/watermark reset.
        source = SimulatedCloudTelemetrySource(
            75, seed=7, malformed_rate=0, source_id=args.comparison_source
        )
        pipeline = ETLPipeline(engine, settings)
        runs = []
        for day_start in (start - timedelta(days=1), start):
            result = pipeline.run_cycle(source, day_start, day_start + timedelta(minutes=3))
            runs.append(result.as_dict())
            if result.status != "SUCCEEDED":
                raise RuntimeError("Comparison telemetry ingestion failed")
        comparison_scope = Scope(source_id=args.comparison_source, as_of=end)
        reports["equivalent_selected_periods"] = service.compare_cost(
            Comparison(
                **comparison_scope.model_dump(),
                current_start=start,
                current_end=end,
                previous_start=start - timedelta(days=1),
                previous_end=end - timedelta(days=1),
            )
        )
        reports["today_vs_full_yesterday"] = service.compare_today(
            comparison_scope, equivalent_elapsed=False
        )
        reports["today_vs_equivalent_elapsed"] = service.compare_today(comparison_scope)
        output = {
            "reports": {name: report.model_dump(mode="json") for name, report in reports.items()},
            "comparison_etl_runs": runs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
        rows = {name: report.rows for name, report in reports.items()}
        summary = {
            "full_report": str(args.output),
            "current_health": rows["current_health"],
            "historical_health": rows["historical_health"],
            "top_cpu": [
                {"server": row["external_server_id"], "cpu_percent": row["cpu_usage_percent"]}
                for row in rows["top_cpu"]
            ],
            "high_cpu_breach_servers": len(rows["high_cpu_breaches"]),
            "high_cpu_breach_observations": sum(
                row["breach_count"] for row in rows["high_cpu_breaches"]
            ),
            "highest_cost_server": rows["highest_cost"][0] if rows["highest_cost"] else None,
            "fleet_cost": rows["fleet_cost"],
            "regional_health": rows["regional_health"],
            "short_window_candidates": [
                row["external_server_id"] for row in rows["underutilized_short_demo"]
            ],
            "standard_policy_candidates": len(rows["underutilized_default"]),
            "short_window_cpu_pressure": [
                row["external_server_id"] for row in rows["sustained_cpu_short_demo"]
            ],
            "equivalent_selected_periods": rows["equivalent_selected_periods"],
            "full_yesterday_quality": rows["today_vs_full_yesterday"][0]["quality"],
            "equivalent_elapsed_day_quality": rows["today_vs_equivalent_elapsed"][0]["quality"],
        }
        print(json.dumps(summary, default=str, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
