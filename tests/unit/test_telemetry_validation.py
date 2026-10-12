from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from infrasight.ingestion.sources.base import ExtractionWindow
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.ingestion.validation import validate_event

START = datetime(2026, 10, 11, 19, 30, tzinfo=UTC)
WINDOW = ExtractionWindow(START, START + timedelta(seconds=30))


@pytest.fixture
def event():
    return SimulatedCloudTelemetrySource(malformed_rate=0)._event(START, 30, 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("external_server_id", ""),
        ("observed_at", "invalid-timestamp"),
        ("observed_at", "2026-10-11T19:30:00"),
        ("observed_at", 123),
        ("environment", "unknown"),
        ("cpu_usage_percent", "101"),
        ("memory_usage_percent", "NaN"),
        ("network_mbps", "Infinity"),
        ("estimated_cost", "-1"),
        ("estimated_cost", None),
        ("currency", None),
        ("interval_seconds", 0),
        ("uptime_seconds", -1),
        ("interval_seconds", True),
        ("server_status", "unknown"),
        ("provider", "aws"),
        ("region_code", " "),
        ("interval_seconds", 31),
    ],
)
def test_invalid_records(event, field, value):
    changed = replace(event, payload={**event.payload, field: value})
    record, errors = validate_event(changed, WINDOW, "simulated")
    assert record is None and errors
    assert all("input" not in e and "ctx" not in e for e in errors)


def test_normalization_and_optional_measurements(event):
    changed = replace(
        event,
        payload={
            **event.payload,
            "environment": " PROD ",
            "server_status": " running ",
            "currency": " usd ",
            "server_name": " name ",
            "network_mbps": None,
            "uptime_seconds": None,
        },
    )
    record, errors = validate_event(changed, WINDOW, "simulated")
    assert not errors
    assert record.environment == "prod" and record.currency == "USD"
    assert record.server_name == "name"
    assert record.network_mbps is None


def test_missing_identifier_and_wrong_window(event):
    payload = event.payload.copy()
    payload.pop("external_server_id")
    assert validate_event(replace(event, payload=payload), WINDOW, "simulated")[0] is None
    outside = ExtractionWindow(START + timedelta(seconds=30), START + timedelta(seconds=60))
    assert validate_event(event, outside, "simulated")[0] is None


def test_mismatched_canonical_timestamp(event):
    altered = replace(event, canonical_observed_at=START + timedelta(seconds=1))
    assert (
        validate_event(altered, WINDOW, "simulated")[1][0]["code"] == "canonical_timestamp_mismatch"
    )
