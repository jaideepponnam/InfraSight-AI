from datetime import timedelta

from pydantic import ValidationError

from infrasight.ingestion.schemas import TelemetryRecord
from infrasight.ingestion.sources.base import EventEnvelope, ExtractionWindow


def validate_event(
    envelope: EventEnvelope, window: ExtractionWindow, provider: str
) -> tuple[TelemetryRecord | None, list[dict]]:
    try:
        record = TelemetryRecord.model_validate(envelope.payload)
    except ValidationError as exc:
        # Never persist raw inputs or validator exception contexts in error details.
        return None, [
            {"field": ".".join(map(str, e["loc"])), "code": e["type"]}
            for e in exc.errors(include_input=False, include_context=False)
        ]
    errors = []
    if record.provider != provider:
        errors.append({"field": "provider", "code": "source_provider_mismatch"})
    if record.observed_at != envelope.canonical_observed_at:
        errors.append({"field": "observed_at", "code": "canonical_timestamp_mismatch"})
    if not window.start <= record.observed_at < window.end:
        errors.append({"field": "observed_at", "code": "outside_window"})
    try:
        if record.observed_at + timedelta(seconds=record.interval_seconds) > window.end:
            errors.append({"field": "interval_seconds", "code": "incomplete_interval"})
    except OverflowError:
        errors.append({"field": "interval_seconds", "code": "timestamp_overflow"})
    if (record.estimated_cost is None) != (record.currency is None):
        errors.append({"field": "currency", "code": "cost_currency_pair"})
    return (None, errors) if errors else (record, [])
