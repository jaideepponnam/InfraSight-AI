from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ExtractionWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.start, self.end)):
            raise ValueError("Extraction windows require timezone-aware timestamps")
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        object.__setattr__(self, "end", self.end.astimezone(UTC))
        if self.end <= self.start:
            raise ValueError("Window end must be later than start")


@dataclass(frozen=True)
class EventEnvelope:
    source_event_id: str
    canonical_observed_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class SourceBatch:
    events: tuple[EventEnvelope, ...]
    next_cursor: dict[str, Any] | None
    done: bool


class TelemetrySource(Protocol):
    source_id: str
    provider: str
    supports_history: bool
    supports_cursor: bool
    available_from: datetime | None

    def completed_until(self, now: datetime) -> datetime: ...

    def extract_batch(
        self, window: ExtractionWindow, cursor: dict | None, batch_size: int
    ) -> SourceBatch: ...


def utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")
