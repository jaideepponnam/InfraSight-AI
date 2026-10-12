from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from infrasight.analytics.schemas import Scope


class BusinessRow(BaseModel):
    """Approved service fields; decimal measurements serialize as exact strings."""

    model_config = ConfigDict(extra="allow")
    server_id: UUID | None = None
    server_name: str | None = None
    source_id: str | None = None
    region_code: str | None = None
    environment: str | None = None
    effective_health: str | None = None
    observed_at: datetime | None = None
    cpu_usage_percent: Decimal | None = None
    memory_usage_percent: Decimal | None = None
    storage_usage_percent: Decimal | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None


class Metadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    request_id: str
    reference_time: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    currency: str | None = None
    freshness_seconds: int | None = None
    warnings: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    data: BusinessRow | list[BusinessRow]
    meta: Metadata


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str


class TriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["simulator", "host"] = "simulator"
    start: AwareDatetime | None = Field(
        default=None, description="Inclusive timezone-aware window start; provide both boundaries."
    )
    end: AwareDatetime | None = Field(
        default=None, description="Exclusive timezone-aware window end."
    )

    @model_validator(mode="after")
    def paired_window(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Provide both start and end")
        if self.start is not None and self.start >= self.end:
            raise ValueError("Require start before end")
        return self


class WindowParameters(Scope):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    def query(self, model, lookback=None):
        if (self.start is None) != (self.end is None):
            raise ValueError("Provide both window boundaries")
        values = self.model_dump()
        if "freshness_seconds" not in self.model_fields_set:
            values.pop("freshness_seconds")
        values["start"] = self.start or (
            self.as_of - timedelta(hours=lookback)
            if lookback
            else self.as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        values["end"] = self.end or self.as_of
        if "threshold" in values:
            values["cpu_threshold"] = values["threshold"]
        return model(**{k: v for k, v in values.items() if k in model.model_fields})


class CpuParameters(WindowParameters):
    threshold: Decimal = Field(
        default=Decimal("80"),
        ge=0,
        le=100,
        description="CPU percent; breaches are strictly greater than this threshold.",
    )
    min_breach_count: int = Field(default=1, ge=1, le=10000)


class PressureParameters(WindowParameters):
    threshold: Decimal = Field(
        default=Decimal("80"),
        ge=0,
        le=100,
        description="CPU percent; observations must be strictly above it.",
    )
    min_samples: int = Field(default=20, ge=1, le=10000)
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    min_breach_fraction: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)


class UnderutilizedParameters(WindowParameters):
    max_cpu: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    max_memory: Decimal = Field(default=Decimal("20"), gt=0, le=100)
    min_samples: int = Field(default=20, ge=1, le=10000)
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    min_cost: Decimal = Field(default=Decimal("0.01"), gt=0)


class ResourceParameters(Scope):
    resource: Literal["cpu", "memory", "storage"] = "cpu"


class ComparisonParameters(Scope):
    mode: Literal["equivalent_elapsed", "completed_days", "today_vs_yesterday", "explicit"] = (
        "equivalent_elapsed"
    )
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    current_start: AwareDatetime | None = None
    current_end: AwareDatetime | None = None
    previous_start: AwareDatetime | None = None
    previous_end: AwareDatetime | None = None
    min_coverage: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)


class InventoryParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str | None = Field(default=None, min_length=1, max_length=256)
    region_code: str | None = Field(default=None, min_length=1, max_length=128)
    environment: Literal["dev", "staging", "prod"] | None = None
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=100)


class RunParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str | None = Field(default=None, min_length=1, max_length=256)
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"] | None = None
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=100)


class CoverageData(BaseModel):
    estimated_cost: Decimal | None
    currency: str
    observation_count: int
    reporting_server_count: int
    expected_server_count: int
    coverage_fraction: Decimal | None
    cost_coverage_fraction: Decimal | None
    overlap_detected: bool


class OverviewData(BusinessRow):
    inventory_servers: int
    servers_with_observations: int
    reporting_servers: int
    healthy_servers: int
    warning_servers: int
    critical_servers: int
    stale_servers: int
    no_data_servers: int
    average_cpu_percent: Decimal | None
    average_memory_percent: Decimal | None
    average_storage_percent: Decimal | None
    observed_cost: Decimal | None
    latest_telemetry_timestamp: datetime | None
    coverage: CoverageData
    highest_cpu_server: BusinessRow | None
    highest_cost_server: BusinessRow | None


class OverviewEnvelope(Envelope):
    data: OverviewData


class CostSummaryData(CoverageData):
    top_cost_servers: list[BusinessRow]


class CostEnvelope(Envelope):
    data: CostSummaryData


class RegionalData(BusinessRow):
    inventory_servers: int
    reporting_servers: int
    healthy_servers: int
    warning_servers: int
    critical_servers: int
    stale_servers: int
    no_data_servers: int
    average_cpu_percent: Decimal | None
    average_memory_percent: Decimal | None
    average_storage_percent: Decimal | None
    latest_telemetry_timestamp: datetime | None
    period_cost: dict[str, Any]


class RegionalEnvelope(Envelope):
    data: list[RegionalData]


class ComparisonData(BaseModel):
    current: CoverageData
    previous: CoverageData
    difference: Decimal | None
    percentage_change: Decimal | None
    direction: str
    quality: str


class ComparisonEnvelope(Envelope):
    data: ComparisonData


class Counts(BaseModel):
    extracted: int
    accepted: int
    inserted: int
    duplicated: int
    rejected: int


class TriggerData(BaseModel):
    run_id: UUID
    source_id: str
    status: Literal["SUCCEEDED", "FAILED"]
    window_start: datetime
    window_end: datetime
    watermark_before: datetime | None
    watermark_after: datetime | None
    counts: Counts
    error_code: str | None


class TriggerEnvelope(Envelope):
    data: TriggerData
