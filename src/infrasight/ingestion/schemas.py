from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class TelemetryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, hide_input_in_errors=True)
    external_server_id: str = Field(min_length=1, max_length=256)
    server_name: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=128)
    region_code: str = Field(min_length=1, max_length=128)
    region_display_name: str | None = None
    environment: Literal["dev", "staging", "prod"]
    observed_at: datetime
    cpu_usage_percent: Percent
    memory_usage_percent: Percent
    storage_usage_percent: Percent
    network_mbps: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    uptime_seconds: int | None = Field(default=None, ge=0, le=9223372036854775807, strict=True)
    server_status: Literal["RUNNING", "DEGRADED", "STOPPED", "FAILED"]
    estimated_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=8)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    interval_seconds: int = Field(gt=0, le=2147483647, strict=True)

    @field_validator(
        "external_server_id",
        "server_name",
        "provider",
        "region_code",
        "region_display_name",
        mode="before",
    )
    @classmethod
    def trim_identity(cls, value):
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A nonblank string is required")
        return value.strip()

    @field_validator("environment", "server_status", "currency", mode="before")
    @classmethod
    def normalize_labels(cls, value, info):
        if not isinstance(value, str):
            return value
        return value.strip().lower() if info.field_name == "environment" else value.strip().upper()

    @field_validator("observed_at", mode="before")
    @classmethod
    def require_timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("Use an ISO timestamp or timezone-aware datetime")
        return value

    @field_validator("observed_at")
    @classmethod
    def timestamp_to_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)


@dataclass
class RunCounts:
    extracted: int = 0
    accepted: int = 0
    inserted: int = 0
    duplicated: int = 0
    rejected: int = 0

    def add(self, other: "RunCounts") -> "RunCounts":
        return RunCounts(**{k: v + asdict(other)[k] for k, v in asdict(self).items()})

    def database_values(self) -> dict:
        return {"records_" + key: value for key, value in asdict(self).items()}


@dataclass(frozen=True)
class RunResult:
    run_id: UUID
    source_id: str
    status: str
    window_start: datetime
    window_end: datetime
    counts: RunCounts
    watermark_before: datetime | None
    watermark_after: datetime | None
    error_code: str | None = None

    def as_dict(self) -> dict:
        values = asdict(self)
        values["run_id"] = str(self.run_id)
        for key in ("window_start", "window_end", "watermark_before", "watermark_after"):
            if values[key] is not None:
                values[key] = values[key].isoformat()
        return values
