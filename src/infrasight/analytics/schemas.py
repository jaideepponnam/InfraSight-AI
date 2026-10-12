from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    as_of: AwareDatetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC reference time; only completed observations are eligible.",
    )
    freshness_seconds: int = Field(
        default=120,
        ge=1,
        le=86400,
        description="Maximum completed-observation age in seconds before STALE.",
    )
    source_id: str | None = Field(default=None, min_length=1, max_length=256)
    region_code: str | None = Field(default=None, min_length=1, max_length=128)
    environment: Literal["dev", "staging", "prod"] | None = None
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("as_of")
    @classmethod
    def utc_reference(cls, value):
        return value.astimezone(UTC)

    @field_validator("source_id", "region_code")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Filter must not be blank")
        return value


class Window(Scope):
    start: AwareDatetime = Field(description="Inclusive UTC period start.")
    end: AwareDatetime = Field(description="Exclusive UTC period end, no later than as_of.")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("start", "end")
    @classmethod
    def utc_window(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_window(self):
        if not self.start < self.end <= self.as_of:
            raise ValueError("Require start < end <= as_of")
        if (self.end - self.start).total_seconds() > 7 * 86400:
            raise ValueError("Analytics windows are bounded to seven days")
        return self


class HealthQuery(Scope):
    health: Literal["HEALTHY", "WARNING", "CRITICAL", "STALE", "NO_DATA"] | None = None
    offset: int = Field(default=0, ge=0, le=100000)


class CpuThreshold(Window):
    min_breach_count: int = Field(default=1, ge=1, le=10000)
    cpu_threshold: Decimal = Field(default=Decimal("80"), ge=0, le=100)


class Pressure(CpuThreshold):
    min_samples: int = Field(default=20, ge=1, le=10000)
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    min_breach_fraction: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)


class Underutilization(Window):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    max_cpu: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    max_memory: Decimal = Field(default=Decimal("20"), gt=0, le=100)
    min_samples: int = Field(default=20, ge=1, le=10000)
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    min_cost: Decimal = Field(default=Decimal("0.01"), gt=0)


class Comparison(Scope):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    current_start: AwareDatetime
    current_end: AwareDatetime
    previous_start: AwareDatetime
    previous_end: AwareDatetime
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    allow_unequal_duration: bool = False

    @model_validator(mode="after")
    def periods(self):
        for prefix in ("current", "previous"):
            start = getattr(self, prefix + "_start").astimezone(UTC)
            end = getattr(self, prefix + "_end").astimezone(UTC)
            Window(as_of=self.as_of, start=start, end=end)
            setattr(self, prefix + "_start", start)
            setattr(self, prefix + "_end", end)
        if self.previous_end > self.current_start:
            raise ValueError("Comparison periods must not overlap")
        if (
            not self.allow_unequal_duration
            and self.current_end - self.current_start != self.previous_end - self.previous_start
        ):
            raise ValueError("Comparison periods must have equivalent duration")
        return self


class AnalyticsReport(BaseModel):
    """Common transport contract; Decimal values retain precision in Python/JSON serialization."""

    reference_time: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    currency: str | None = None
    rows: list[dict[str, Any]]
    parameters: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
