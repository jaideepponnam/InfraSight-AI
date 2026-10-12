from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from infrasight.ingestion.sources.base import ExtractionWindow
from infrasight.ingestion.sources.host import HostMetricsSource
from infrasight.ingestion.validation import validate_event

START = datetime(2026, 10, 11, tzinfo=UTC)


def host(settings, reset=False, unsupported=False):
    collector = Mock()
    collector.cpu_percent.return_value = 34.25
    collector.virtual_memory.return_value = SimpleNamespace(percent=55.5)
    collector.disk_usage.return_value = SimpleNamespace(percent=20.5)
    collector.net_io_counters.side_effect = [
        SimpleNamespace(bytes_sent=100, bytes_recv=100),
        SimpleNamespace(bytes_sent=50 if reset else 600100, bytes_recv=50 if reset else 400100),
    ]
    collector.boot_time.return_value = START.timestamp() - 3600
    if unsupported:
        collector.cpu_percent.side_effect = PermissionError("blocked")
        collector.net_io_counters.side_effect = PermissionError("blocked")
        collector.boot_time.side_effect = OSError("blocked")
    times = iter([0.0, 1.1])
    return HostMetricsSource(
        settings,
        collector=collector,
        sleeper=lambda _: None,
        monotonic=lambda: next(times),
        clock=lambda: START,
    )


def test_measured_host_rate_and_null_cost(settings):
    source = host(settings)
    event = source.capture()
    record, errors = validate_event(
        event, ExtractionWindow(START, START + timedelta(seconds=2)), "host"
    )
    assert not errors
    assert record.network_mbps == Decimal("7.2727")
    assert record.estimated_cost is None and record.currency is None
    assert record.uptime_seconds == 3600
    assert record.interval_seconds == 1
    batch = source.extract_batch(ExtractionWindow(START, START + timedelta(seconds=2)), None, 1)
    assert batch.events == (event,) and batch.done


def test_network_counter_reset_returns_unsupported(settings):
    assert host(settings, reset=True).capture().payload["network_mbps"] is None


def test_missing_required_metric_is_rejected_without_invented_values(settings):
    event = host(settings, unsupported=True).capture()
    assert event.payload["cpu_usage_percent"] is None
    assert event.payload["network_mbps"] is None
    assert event.payload["uptime_seconds"] is None
    record, errors = validate_event(
        event, ExtractionWindow(START, START + timedelta(seconds=2)), "host"
    )
    assert record is None and errors
