import math
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from infrasight.ingestion.errors import SourceError
from infrasight.ingestion.sources.base import EventEnvelope, ExtractionWindow, SourceBatch, utc_iso


class HostMetricsSource:
    provider = "host"
    supports_history = False
    supports_cursor = False

    def __init__(
        self, settings, collector=None, sleeper=time.sleep, monotonic=time.monotonic, clock=None
    ):
        if collector is None:
            try:
                import psutil
            except ImportError as exc:
                raise SourceError(
                    "Install the optional host dependency to collect host metrics"
                ) from exc
            collector = psutil
        self.collector = collector
        self.settings = settings
        self.source_id = settings.host_source_id
        self.sleeper, self.monotonic = sleeper, monotonic
        self.clock = clock or (lambda: datetime.now(UTC))
        self._samples = deque(maxlen=256)

    @staticmethod
    def _safe(call):
        try:
            value = call()
            return value if value is None or math.isfinite(value) else None
        except (OSError, RuntimeError, AttributeError, ValueError):
            return None

    def _network_bytes(self):
        counters = self.collector.net_io_counters()
        return counters.bytes_sent + counters.bytes_recv

    @property
    def available_from(self):
        return self._samples[0].canonical_observed_at if self._samples else None

    def capture(self) -> EventEnvelope:
        observed = self.clock().astimezone(UTC)
        before = self._safe(self._network_bytes)
        self._safe(lambda: self.collector.cpu_percent(interval=None))
        started = self.monotonic()
        self.sleeper(self.settings.host_sample_seconds)
        elapsed = self.monotonic() - started
        if elapsed < 1:
            raise SourceError("Host sample must measure at least one elapsed second")
        cpu = self._safe(lambda: self.collector.cpu_percent(interval=None))
        memory = self._safe(lambda: self.collector.virtual_memory().percent)
        disk = self._safe(lambda: self.collector.disk_usage(self.settings.host_disk_path).percent)
        after = self._safe(self._network_bytes)
        network = None
        if before is not None and after is not None and after >= before:
            network = round((after - before) * 8 / elapsed / 1_000_000, 4)
        boot_time = self._safe(lambda: self.collector.boot_time())
        uptime = max(0, int(observed.timestamp() - boot_time)) if boot_time is not None else None
        event_id = f"{self.settings.host_external_server_id}:{utc_iso(observed)}"

        def percent(value):
            return None if value is None else str(Decimal(str(value)).quantize(Decimal("0.01")))

        payload = {
            "source_event_id": event_id,
            "external_server_id": self.settings.host_external_server_id,
            "server_name": self.settings.host_external_server_id,
            "provider": "host",
            "region_code": self.settings.host_region_code,
            "environment": self.settings.host_environment,
            "observed_at": utc_iso(observed),
            "cpu_usage_percent": percent(cpu),
            "memory_usage_percent": percent(memory),
            "storage_usage_percent": percent(disk),
            "network_mbps": None if network is None else f"{network:.4f}",
            "uptime_seconds": uptime,
            "server_status": "RUNNING",
            "estimated_cost": None,
            "currency": None,
            "interval_seconds": int(elapsed),
        }
        event = EventEnvelope(event_id, observed, payload)
        self._samples.append(event)
        return event

    def completed_until(self, now: datetime) -> datetime:
        if not self._samples:
            raise SourceError("Capture a host sample before running an ETL cycle")
        last = self._samples[-1]
        return last.canonical_observed_at + timedelta(seconds=last.payload["interval_seconds"])

    def extract_batch(
        self, window: ExtractionWindow, cursor: dict | None, batch_size: int
    ) -> SourceBatch:
        samples = tuple(
            e
            for e in self._samples
            if window.start <= e.canonical_observed_at
            and e.canonical_observed_at + timedelta(seconds=e.payload["interval_seconds"])
            <= window.end
        )
        offset = int(cursor["offset"]) if cursor else 0
        stop = min(len(samples), offset + batch_size)
        return SourceBatch(samples[offset:stop], {"offset": stop}, stop == len(samples))
