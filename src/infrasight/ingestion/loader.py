from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrasight.db.models import (
    DataQualityRejection,
    InfrastructureMetric,
    RawTelemetry,
    Region,
    Server,
)
from infrasight.ingestion.schemas import RunCounts
from infrasight.ingestion.sources.base import EventEnvelope, ExtractionWindow
from infrasight.ingestion.transformations import metric_values
from infrasight.ingestion.validation import validate_event


def load_batch(
    connection,
    run_id,
    source_id: str,
    provider: str,
    window: ExtractionWindow,
    events: tuple[EventEnvelope, ...],
) -> RunCounts:
    counts = RunCounts(extracted=len(events))
    if not events:
        return counts
    # First event wins; conflicting payload versions never silently replace raw evidence.
    unique_events = {event.source_event_id: event for event in reversed(events)}
    raw_values = [
        {
            "source_id": source_id,
            "source_event_id": event.source_event_id,
            "etl_run_id": run_id,
            "payload": event.payload,
        }
        for event in unique_events.values()
    ]
    connection.execute(
        pg_insert(RawTelemetry)
        .values(raw_values)
        .on_conflict_do_nothing(constraint="uq_raw_telemetry_source_event")
    )
    raw_rows = connection.execute(
        select(RawTelemetry.id, RawTelemetry.source_event_id, RawTelemetry.payload).where(
            RawTelemetry.source_id == source_id, RawTelemetry.source_event_id.in_(unique_events)
        )
    ).mappings()
    raw = {row["source_event_id"]: row for row in raw_rows}
    accepted, rejections = [], {}
    for envelope in events:
        stored = raw[envelope.source_event_id]
        canonical = EventEnvelope(
            envelope.source_event_id, envelope.canonical_observed_at, stored["payload"]
        )
        record, errors = validate_event(canonical, window, provider)
        if errors:
            counts.rejected += 1
            rejections[stored["id"]] = {
                "etl_run_id": run_id,
                "raw_telemetry_id": stored["id"],
                "error_code": "INVALID_TELEMETRY",
                "validation_errors": errors,
            }
        else:
            counts.accepted += 1
            accepted.append((stored["id"], record))
    if rejections:
        connection.execute(
            pg_insert(DataQualityRejection)
            .values(list(rejections.values()))
            .on_conflict_do_nothing(constraint="uq_data_quality_rejections_run_raw")
        )
    if not accepted:
        return counts
    region_keys = {
        (record.provider, record.region_code): record.region_display_name or record.region_code
        for _, record in accepted
    }
    connection.execute(
        pg_insert(Region)
        .values(
            [
                {
                    "provider": provider_name,
                    "region_code": code,
                    "display_name": region_keys[(provider_name, code)],
                }
                for provider_name, code in sorted(region_keys)
            ]
        )
        .on_conflict_do_nothing(constraint="uq_regions_provider_code")
    )
    # Bound this lookup to batch region identities, rather than reading the entire table.
    from sqlalchemy import tuple_

    regions = {
        (r.provider, r.region_code): r.id
        for r in connection.execute(
            select(Region.id, Region.provider, Region.region_code).where(
                tuple_(Region.provider, Region.region_code).in_(region_keys)
            )
        )
    }
    inventory = {}
    for _, record in accepted:
        current = inventory.get(record.external_server_id)
        if current is None:
            inventory[record.external_server_id] = {"record": record, "first": record.observed_at}
        else:
            current["first"] = min(current["first"], record.observed_at)
            if record.observed_at > current["record"].observed_at:
                current["record"] = record
    server_values = []
    for external_id, item in sorted(inventory.items()):
        record = item["record"]
        server_values.append(
            {
                "source_id": source_id,
                "external_server_id": external_id,
                "server_name": record.server_name,
                "environment": record.environment,
                "region_id": regions[(record.provider, record.region_code)],
                "first_seen_at": item["first"],
                "last_seen_at": record.observed_at,
            }
        )
    statement = pg_insert(Server).values(server_values)
    newer = statement.excluded.last_seen_at > Server.last_seen_at
    updates = {
        "first_seen_at": func.least(Server.first_seen_at, statement.excluded.first_seen_at),
        "last_seen_at": func.greatest(Server.last_seen_at, statement.excluded.last_seen_at),
        "updated_at": case((newer, datetime.now(UTC)), else_=Server.updated_at),
    }
    for field in ("server_name", "environment", "region_id"):
        updates[field] = case(
            (newer, getattr(statement.excluded, field)), else_=getattr(Server, field)
        )
    servers = {
        row.external_server_id: row.id
        for row in connection.execute(
            statement.on_conflict_do_update(
                constraint="uq_servers_source_external_id", set_=updates
            ).returning(Server.external_server_id, Server.id)
        )
    }
    # Deduplicate both raw IDs and observation identities before the bulk INSERT.
    candidates, raw_ids = {}, set()
    for raw_id, record in accepted:
        identity = (servers[record.external_server_id], record.observed_at)
        if identity not in candidates and raw_id not in raw_ids:
            candidates[identity] = {
                "server_id": identity[0],
                "etl_run_id": run_id,
                "raw_telemetry_id": raw_id,
                **metric_values(record),
            }
            raw_ids.add(raw_id)
    inserted = (
        connection.execute(
            pg_insert(InfrastructureMetric)
            .values(list(candidates.values()))
            .on_conflict_do_nothing()
            .returning(InfrastructureMetric.id)
        )
        .scalars()
        .all()
    )
    counts.inserted = len(inserted)
    counts.duplicated = counts.accepted - counts.inserted
    return counts
