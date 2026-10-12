import argparse
import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select

from infrasight.config import get_settings
from infrasight.db.models import (
    DataQualityRejection,
    InfrastructureMetric,
    RawTelemetry,
    Server,
)
from infrasight.db.session import create_database_engine
from infrasight.ingestion.errors import SourceError
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.repositories import read_progress
from infrasight.ingestion.sources.host import HostMetricsSource
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.ingestion.sources.stored import StoredHostTelemetrySource
from infrasight.logging import configure_logging


def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone")
    return parsed.astimezone(UTC)


def simulator(settings, source_id):
    return SimulatedCloudTelemetrySource(
        settings.simulator_server_count,
        settings.simulator_seed,
        settings.telemetry_interval_seconds,
        settings.simulator_malformed_rate,
        source_id,
    )


def demo(engine, settings, start=None, source_id="simulated-cloud"):
    source = SimulatedCloudTelemetrySource(75, 7, 30, 0.01, source_id)
    start = start or source.completed_until(datetime.now(UTC)) - timedelta(seconds=180)
    end = start + timedelta(seconds=120)
    next_end = end + timedelta(seconds=60)
    if next_end > datetime.now(UTC):
        raise ValueError("Demo window must contain only completed intervals")
    with engine.connect() as connection:
        if read_progress(connection, source_id) is not None:
            raise ValueError(
                "Demo requires an unused source ID; pass --source-id with a fresh demo ID"
            )
    demo_settings = settings.model_copy(update={"etl_batch_size": 100, "etl_overlap_seconds": 60})
    pipeline = ETLPipeline(engine, demo_settings)
    first = pipeline.run_cycle(source, start, end)
    replay = pipeline.run_cycle(source, start, end)
    incremental = pipeline.run_cycle(source, now=next_end)
    results = [first, replay, incremental]
    if any(result.status != "SUCCEEDED" for result in results):
        print(json.dumps({"runs": [r.as_dict() for r in results]}, indent=2))
        raise SourceError("Demo cycle failed")
    with engine.connect() as connection:
        totals = {
            "servers": connection.scalar(
                select(func.count()).select_from(Server).where(Server.source_id == source_id)
            ),
            "raw_events": connection.scalar(
                select(func.count())
                .select_from(RawTelemetry)
                .where(RawTelemetry.source_id == source_id)
            ),
            "metrics": connection.scalar(
                select(func.count())
                .select_from(InfrastructureMetric)
                .join(Server)
                .where(Server.source_id == source_id)
            ),
            "rejection_attempts": connection.scalar(
                select(func.count())
                .select_from(DataQualityRejection)
                .join(RawTelemetry)
                .where(RawTelemetry.source_id == source_id)
            ),
        }
        rejected = (
            connection.execute(
                select(
                    RawTelemetry.source_event_id,
                    RawTelemetry.payload,
                    DataQualityRejection.validation_errors,
                )
                .join(DataQualityRejection)
                .where(DataQualityRejection.etl_run_id == first.run_id)
                .order_by(RawTelemetry.id)
            )
            .mappings()
            .all()
        )
        history = (
            connection.execute(
                select(
                    Server.external_server_id,
                    InfrastructureMetric.observed_at,
                    InfrastructureMetric.cpu_usage_percent,
                    InfrastructureMetric.memory_usage_percent,
                    InfrastructureMetric.resource_health,
                    InfrastructureMetric.estimated_cost,
                )
                .join(Server)
                .where(Server.source_id == source_id, Server.external_server_id == "sim-002")
                .order_by(InfrastructureMetric.observed_at)
            )
            .mappings()
            .all()
        )
        progress = dict(read_progress(connection, source_id))
    report = {
        "runs": [r.as_dict() for r in results],
        "database_totals": totals,
        "progress": progress,
        "rejected_records": [dict(r) for r in rejected],
        "metric_history": [dict(r) for r in history],
    }
    print(json.dumps(report, default=str, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="InfraSight-AI: one bounded micro-batch ETL cycle")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "replay"):
        command = commands.add_parser(name)
        command.add_argument("--source", choices=["simulator", "host"], default="simulator")
        command.add_argument("--source-id", default=None)
        command.add_argument("--start", type=parse_timestamp)
        command.add_argument("--end", type=parse_timestamp)
    command = commands.add_parser("demo")
    command.add_argument("--start", type=parse_timestamp)
    command.add_argument("--source-id", default="simulated-cloud")
    args = parser.parse_args()
    if args.command == "replay" and (args.start is None or args.end is None):
        parser.error("Replay requires --start and --end")
    engine = None
    try:
        settings = get_settings()
        configure_logging(settings.log_level)
        engine = create_database_engine(settings)
        if args.command == "demo":
            demo(engine, settings, args.start, args.source_id)
            return 0
        if args.source == "simulator":
            source = simulator(settings, args.source_id or "simulated-cloud")
        elif args.command == "replay":
            source = StoredHostTelemetrySource(engine, args.source_id or settings.host_source_id)
        else:
            if not settings.host_enabled:
                raise ValueError("Enable HOST_ENABLED to collect real host metrics")
            if args.start is not None or args.end is not None or args.source_id is not None:
                raise ValueError(
                    "Live host collection uses configured identity and current samples"
                )
            source = HostMetricsSource(settings)
            source.capture()
        result = ETLPipeline(engine, settings).run_cycle(source, args.start, args.end)
        print(json.dumps(result.as_dict(), indent=2))
        return 0 if result.status == "SUCCEEDED" else 1
    except Exception as exc:
        # Validation messages are safe; arbitrary DB/provider messages are not.
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "ETL command failed; inspect structured logs"
        )
        structlog.get_logger(__name__).error(
            "etl_cli_failed", error_type=type(exc).__name__, message=message
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
