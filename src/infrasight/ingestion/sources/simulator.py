import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

from infrasight.ingestion.errors import SourceError
from infrasight.ingestion.sources.base import (
    EventEnvelope,
    ExtractionWindow,
    SourceBatch,
    utc_iso,
)

REGIONS = ("us-south", "us-east", "eu-de")
ENVIRONMENTS = ("dev", "staging", "prod")
PROFILES = (
    "healthy",
    "cpu-spike",
    "memory-pressure",
    "intermittent-failure",
    "expensive-underutilized",
    "high-network",
    "growing-demand",
)


class SimulatedCloudTelemetrySource:
    provider = "simulated"
    supports_history = True
    supports_cursor = False
    available_from = None

    def __init__(
        self,
        server_count=75,
        seed=7,
        interval_seconds=30,
        malformed_rate=0.01,
        source_id="simulated-cloud",
    ):
        if not 1 <= server_count <= 100 or not 1 <= interval_seconds <= 3600:
            raise ValueError("Fleet and interval are outside supported bounds")
        if not 0 <= malformed_rate <= 0.1 or not source_id.strip():
            raise ValueError("Invalid malformed rate or source identity")
        self.source_id = source_id
        self.server_count = server_count
        self.seed = seed
        self.interval_seconds = interval_seconds
        self.malformed_rate = malformed_rate

    def completed_until(self, now: datetime) -> datetime:
        now = now.astimezone(UTC)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds = int((now - midnight).total_seconds())
        return midnight + timedelta(
            seconds=seconds // self.interval_seconds * self.interval_seconds
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _intervals(
        window: ExtractionWindow, interval_seconds: int
    ) -> tuple[tuple[datetime, int], ...]:
        intervals = []
        day = window.start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < window.end:
            seconds = max(0, (window.start - day).total_seconds())
            offset = math.ceil(seconds / interval_seconds) * interval_seconds
            while offset < 86400:
                observed = day + timedelta(seconds=offset)
                duration = min(interval_seconds, 86400 - offset)
                if observed >= window.end:
                    break
                # Membership comes from canonical interval metadata, never a corrupted payload.
                if (
                    observed >= window.start
                    and observed + timedelta(seconds=duration) <= window.end
                ):
                    intervals.append((observed, duration))
                offset += interval_seconds
            day += timedelta(days=1)
        return tuple(intervals)

    def _event(self, observed: datetime, duration: int, index: int) -> EventEnvelope:
        profile = PROFILES[index % len(PROFILES)]
        slot = int(observed.timestamp()) // self.interval_seconds
        wave = math.sin(slot / 4 + index + self.seed)
        cpu, memory, network = 42 + wave * 8, 52 + wave * 6, 12 + abs(wave) * 8
        status = "RUNNING"
        hourly_rate = Decimal("0.12")
        if profile == "cpu-spike":
            cpu = 94 + wave * 3 if slot % 12 < 4 else 46 + wave * 8
        elif profile == "memory-pressure":
            memory = 89 + abs(wave) * 7
        elif profile == "intermittent-failure":
            if slot % 10 in (2, 3):
                status, cpu, memory, network = "FAILED", 0, 0, 0
            elif slot % 10 == 4:
                status, cpu = "DEGRADED", 76
        elif profile == "expensive-underutilized":
            cpu, memory, hourly_rate = 5 + wave * 2, 12 + wave * 3, Decimal("0.85")
        elif profile == "high-network":
            network = 900 + wave * 100
        elif profile == "growing-demand":
            cpu = 28 + ((slot % 120) * 0.5) + wave * 2
        region = REGIONS[index % len(REGIONS)]
        region_factor = (Decimal("1"), Decimal("1.2"), Decimal("1.4"))[index % 3]
        daily_factor = Decimal("1.12") if observed.date().toordinal() % 2 else Decimal("1")
        cost = (
            hourly_rate
            * region_factor
            * daily_factor
            * Decimal(duration)
            / Decimal(3600)
            * (Decimal("1") + Decimal(str(round(cpu, 2))) / Decimal(1000))
        )
        event_id = f"sim-{index + 1:03d}:{utc_iso(observed)}"
        payload = {
            "source_event_id": event_id,
            "external_server_id": f"sim-{index + 1:03d}",
            "server_name": f"{profile}-{index + 1:03d}",
            "profile": profile,
            "provider": self.provider,
            "region_code": region,
            "region_display_name": {
                "us-south": "US South",
                "us-east": "US East",
                "eu-de": "Germany",
            }[region],
            "environment": ENVIRONMENTS[(index // 3) % 3],
            "observed_at": utc_iso(observed),
            "cpu_usage_percent": f"{cpu:.2f}",
            "memory_usage_percent": f"{memory:.2f}",
            "storage_usage_percent": f"{57 + wave * 4:.2f}",
            "network_mbps": f"{network:.4f}",
            "uptime_seconds": 0 if status == "FAILED" else 604800 + slot % 86400,
            "server_status": status,
            "estimated_cost": str(cost.quantize(Decimal("0.00000001"))),
            "currency": "USD",
            "interval_seconds": duration,
        }
        if self.malformed_rate:
            # A deterministic periodic schedule gives small, predictable rejection counts.
            period = max(10, round(1 / self.malformed_rate))
            ordinal = slot * self.server_count + index + self.seed
            if ordinal % period == 0:
                mutation = (ordinal // period) % 5
                if mutation == 0:
                    payload["cpu_usage_percent"] = "125.00"
                elif mutation == 1:
                    payload.pop("external_server_id")
                elif mutation == 2:
                    payload["environment"] = "invalid"
                elif mutation == 3:
                    payload["observed_at"] = "invalid-timestamp"
                else:
                    payload["estimated_cost"] = "-1.00"
        return EventEnvelope(event_id, observed, payload)

    def extract_batch(
        self, window: ExtractionWindow, cursor: dict | None, batch_size: int
    ) -> SourceBatch:
        intervals = self._intervals(window, self.interval_seconds)
        offset = int(cursor["offset"]) if cursor else 0
        count = len(intervals) * self.server_count
        if offset < 0 or offset > count or batch_size < 1:
            raise SourceError("Invalid extraction cursor")
        stop = min(count, offset + batch_size)
        events = tuple(
            self._event(*intervals[position // self.server_count], position % self.server_count)
            for position in range(offset, stop)
        )
        return SourceBatch(
            events, {"offset": stop, "window_end": utc_iso(window.end)}, stop == count
        )
