from datetime import UTC, datetime, timedelta

from infrasight.ingestion.sources.base import ExtractionWindow
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource

START = datetime(2026, 10, 11, 19, 30, tzinfo=UTC)


def collect(source, window, size=100):
    events, cursor = [], None
    while True:
        batch = source.extract_batch(window, cursor, size)
        assert len(batch.events) <= size
        events.extend(batch.events)
        cursor = batch.next_cursor
        if batch.done:
            return events


def test_reproducible_independent_of_batch_size_and_extraction_order():
    window = ExtractionWindow(START, START + timedelta(minutes=2))
    source = SimulatedCloudTelemetrySource()
    expected = collect(source, window)
    collect(source, ExtractionWindow(START - timedelta(minutes=2), START), 17)
    assert expected == collect(source, window, 23)
    assert expected == collect(SimulatedCloudTelemetrySource(), window, 75)
    assert len(expected) == 300
    assert len({e.source_event_id for e in expected}) == 300
    assert {e.payload["region_code"] for e in expected} == {"us-south", "us-east", "eu-de"}
    assert {e.payload["environment"] for e in expected} - {"invalid"} == {"dev", "staging", "prod"}
    assert len({e.payload["profile"] for e in expected}) == 7


def test_malformed_timestamp_is_selected_using_canonical_metadata():
    window = ExtractionWindow(START, START + timedelta(minutes=2))
    events = collect(SimulatedCloudTelemetrySource(malformed_rate=0.1), window)
    bad = [e for e in events if e.payload["observed_at"] == "invalid-timestamp"]
    assert bad
    assert all(window.start <= e.canonical_observed_at < window.end for e in bad)
    assert any("external_server_id" not in e.payload for e in events)
    assert any(e.payload["cpu_usage_percent"] == "125.00" for e in events)
    assert any(e.payload["environment"] == "invalid" for e in events)
    assert any(e.payload["estimated_cost"] == "-1.00" for e in events)


def test_half_open_windows_and_midnight_split():
    start = datetime(2026, 10, 11, 23, 59, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    source = SimulatedCloudTelemetrySource(server_count=1, interval_seconds=77, malformed_rate=0)
    events = collect(source, ExtractionWindow(start, end))
    assert events
    for event in events:
        interval_end = event.canonical_observed_at + timedelta(
            seconds=event.payload["interval_seconds"]
        )
        assert interval_end <= end
        assert interval_end <= event.canonical_observed_at.replace(
            hour=0, minute=0, second=0
        ) + timedelta(days=1)
    left = collect(source, ExtractionWindow(start, start + timedelta(minutes=1)))
    right = collect(source, ExtractionWindow(start + timedelta(minutes=1), end))
    assert set(e.source_event_id for e in left).isdisjoint(e.source_event_id for e in right)


def test_profiles_cost_variation_and_live_changes():
    source = SimulatedCloudTelemetrySource(malformed_rate=0)
    first = source._event(START, 30, 4).payload
    expensive = float(first["estimated_cost"])
    healthy = source._event(START, 30, 0).payload
    assert float(first["cpu_usage_percent"]) < 10
    assert expensive > float(healthy["estimated_cost"]) * 5
    assert source._event(START, 30, 5).payload["network_mbps"] != healthy["network_mbps"]
    assert source._event(START + timedelta(seconds=30), 30, 0).payload != healthy
    assert (
        source._event(START - timedelta(days=1), 30, 0).payload["estimated_cost"]
        != healthy["estimated_cost"]
    )
