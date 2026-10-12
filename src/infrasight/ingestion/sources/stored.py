from datetime import datetime

from sqlalchemy import select

from infrasight.db.models import RawTelemetry
from infrasight.ingestion.sources.base import EventEnvelope, ExtractionWindow, SourceBatch, utc_iso


class StoredHostTelemetrySource:
    """Replay already captured host events; never invent historical host measurements."""

    provider = "host"
    supports_history = True
    supports_cursor = False
    available_from = None

    def __init__(self, engine, source_id="host-local"):
        self.engine, self.source_id = engine, source_id

    def completed_until(self, now):
        return now

    def extract_batch(
        self, window: ExtractionWindow, cursor: dict | None, batch_size: int
    ) -> SourceBatch:
        # HostMetricsSource always emits fixed-width UTC ISO strings, including for
        # unsupported measurements. This avoids casting arbitrary provider payloads.
        statement = (
            select(RawTelemetry.id, RawTelemetry.source_event_id, RawTelemetry.payload)
            .where(
                RawTelemetry.source_id == self.source_id,
                RawTelemetry.id > (cursor["raw_id"] if cursor else 0),
                RawTelemetry.payload["observed_at"].astext >= utc_iso(window.start),
                RawTelemetry.payload["observed_at"].astext < utc_iso(window.end),
            )
            .order_by(RawTelemetry.id)
            .limit(batch_size)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        events = tuple(
            EventEnvelope(
                row["source_event_id"],
                datetime.fromisoformat(row["payload"]["observed_at"]),
                row["payload"],
            )
            for row in rows
        )
        cursor = {"raw_id": rows[-1]["id"]} if rows else cursor
        return SourceBatch(events, cursor, len(rows) < batch_size)
