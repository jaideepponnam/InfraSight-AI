from fastapi import HTTPException
from sqlalchemy import text

from infrasight.analytics.repository import FILTER, HEALTH_CTES, AnalyticsRepository
from infrasight.ingestion.cli import simulator
from infrasight.ingestion.errors import SourceBusyError
from infrasight.ingestion.pipeline import ETLPipeline
from infrasight.ingestion.sources.host import HostMetricsSource
from infrasight.ingestion.sources.stored import StoredHostTelemetrySource

INVENTORY = """SELECT s.id AS server_id, s.external_server_id, s.server_name, s.source_id,
    s.environment, s.first_seen_at, s.last_seen_at, r.provider, r.region_code,
    r.display_name AS region_display_name FROM servers s JOIN regions r ON r.id=s.region_id"""
RUN_FIELDS = """id AS run_id, source_id, status, requested_window_start, requested_window_end,
requested_at, started_at, finished_at, records_extracted, records_accepted, records_inserted,
records_duplicated, records_rejected, watermark_before, watermark_after,
CASE WHEN status='FAILED' THEN
    CASE WHEN error_code IN ('SOURCE_UNAVAILABLE','SOURCE_ERROR','SOURCE_LOCK_LOST',
        'DATABASE_ERROR','PIPELINE_ERROR') THEN error_code ELSE 'ETL_FAILED' END
END AS error_code,
CASE WHEN status='FAILED' THEN 'ETL failed; consult operator logs.' END AS error_message"""


class OperationsService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def servers(self, params):
        values = params.model_dump()
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as db:
            with db.begin():
                base = "WITH inventory AS (" + INVENTORY + ") "
                rows = (
                    db.execute(
                        text(
                            base
                            + "SELECT * FROM inventory WHERE "
                            + FILTER
                            + " ORDER BY source_id, external_server_id, server_id "
                            "LIMIT :limit OFFSET :offset"
                        ),
                        values,
                    )
                    .mappings()
                    .all()
                )
                total = db.scalar(
                    text(base + "SELECT COUNT(*) FROM inventory WHERE " + FILTER), values
                )
        return {
            "data": [dict(r) for r in rows],
            "meta": {
                "filters": values,
                "pagination": {"offset": params.offset, "limit": params.limit, "total": total},
            },
        }

    def server(self, server_id, query):
        values = AnalyticsRepository.parameters(query)
        values["server_id"] = server_id
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as db:
            with db.begin():
                row = (
                    db.execute(text(INVENTORY + " WHERE s.id=:server_id"), values)
                    .mappings()
                    .first()
                )
                if row is None:
                    raise HTTPException(404, "SERVER_NOT_FOUND")
                health = (
                    db.execute(
                        text(
                            "WITH "
                            + HEALTH_CTES
                            + "SELECT * FROM health WHERE server_id=:server_id"
                        ),
                        values,
                    )
                    .mappings()
                    .first()
                )
        return {
            "data": {**dict(row), "latest_telemetry": dict(health) if health else None},
            "meta": {"reference_time": query.as_of, "freshness_seconds": query.freshness_seconds},
        }

    def runs(self, params):
        values = params.model_dump()
        where = (
            "source_id=COALESCE(CAST(:source_id AS text),source_id) "
            "AND status=COALESCE(CAST(:status AS text),status)"
        )
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as db:
            with db.begin():
                rows = (
                    db.execute(
                        text(
                            "SELECT "
                            + RUN_FIELDS
                            + " FROM etl_runs WHERE "
                            + where
                            + " ORDER BY requested_at DESC, id DESC LIMIT :limit OFFSET :offset"
                        ),
                        values,
                    )
                    .mappings()
                    .all()
                )
                total = db.scalar(text("SELECT COUNT(*) FROM etl_runs WHERE " + where), values)
        return {
            "data": [dict(r) for r in rows],
            "meta": {
                "pagination": {"offset": params.offset, "limit": params.limit, "total": total}
            },
        }

    def run(self, run_id):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    text("SELECT " + RUN_FIELDS + " FROM etl_runs WHERE id=:id"), {"id": run_id}
                )
                .mappings()
                .first()
            )
        if row is None:
            raise HTTPException(404, "ETL_RUN_NOT_FOUND")
        return {"data": dict(row)}

    def trigger(self, body):
        maximum = min(
            self.settings.etl_max_window_seconds, self.settings.etl_api_max_window_seconds
        )
        if body.start is not None and (body.end - body.start).total_seconds() > maximum:
            raise ValueError("API ETL window exceeds bound")
        settings = self.settings.model_copy(update={"etl_max_window_seconds": maximum})
        if settings.etl_overlap_seconds + settings.telemetry_interval_seconds > maximum:
            raise HTTPException(503, "ETL_CONFIGURATION_INVALID")
        if body.source == "simulator":
            source = simulator(settings, "simulated-cloud")
        else:
            if not settings.host_enabled:
                raise HTTPException(422, "SOURCE_DISABLED")
            if body.start is not None:
                source = StoredHostTelemetrySource(self.engine, settings.host_source_id)
            else:
                source = HostMetricsSource(settings)
                source.capture()
        try:
            result = ETLPipeline(self.engine, settings).run_cycle(source, body.start, body.end)
        except SourceBusyError as exc:
            raise HTTPException(409, "SOURCE_BUSY") from exc
        # A completed cycle is an auditable outcome, including FAILED runs.
        # The client inspects status/error_code; this endpoint never pretends to queue work.
        return {"data": result.as_dict()}
