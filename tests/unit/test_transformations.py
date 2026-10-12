from datetime import UTC, datetime

import pytest

from infrasight.ingestion.schemas import TelemetryRecord
from infrasight.ingestion.sources.simulator import SimulatedCloudTelemetrySource
from infrasight.ingestion.transformations import classify_health


@pytest.mark.parametrize(
    "cpu,memory,status,expected",
    [
        (79.99, 79.99, "RUNNING", "HEALTHY"),
        (80, 20, "RUNNING", "WARNING"),
        (20, 80, "RUNNING", "WARNING"),
        (89.99, 20, "RUNNING", "WARNING"),
        (90, 20, "RUNNING", "CRITICAL"),
        (20, 90, "RUNNING", "CRITICAL"),
        (0, 0, "FAILED", "CRITICAL"),
        (0, 0, "DEGRADED", "WARNING"),
        (0, 0, "STOPPED", "HEALTHY"),
    ],
)
def test_documented_health_policy(cpu, memory, status, expected):
    payload = (
        SimulatedCloudTelemetrySource(malformed_rate=0)
        ._event(datetime(2026, 10, 11, tzinfo=UTC), 30, 0)
        .payload
    )
    payload.update(
        cpu_usage_percent=str(cpu),
        memory_usage_percent=str(memory),
        server_status=status,
        storage_usage_percent="100",
    )
    assert classify_health(TelemetryRecord.model_validate(payload)) == expected
