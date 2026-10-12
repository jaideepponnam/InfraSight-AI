from datetime import UTC, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    question: str = Field(min_length=1, max_length=2000)
    source_id: str | None = Field(default=None, min_length=1, max_length=256)
    reference_time: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    freshness_seconds: int | None = Field(default=None, ge=1, le=86400)
    min_samples: int | None = Field(default=None, ge=1, le=10000)

    @field_validator("question", "source_id")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Nonblank input required")
        return value.strip() if value is not None else value

    @field_validator("reference_time", "start", "end")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def bounded_window(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Both window boundaries are required")
        if self.start is not None:
            if not self.start < self.end <= self.reference_time:
                raise ValueError("Require start < end <= reference_time")
            if (self.end - self.start).total_seconds() > 7 * 86400:
                raise ValueError("Window is bounded to seven days")
        return self


class ToolEvidence(BaseModel):
    tool: str
    arguments: dict[str, Any]
    reference_time: datetime
    window: dict[str, datetime | None]
    freshness: dict[str, Any]
    coverage: list[dict[str, Any]]
    currency: str | None
    returned_rows: int
    result: dict[str, Any]
    warnings: list[str]


class Evidence(BaseModel):
    tools_used: list[str]
    reference_time: datetime
    window: dict[str, datetime | None]
    freshness: dict[str, Any]
    coverage: list[dict[str, Any]]
    currency: str
    tool_results: list[ToolEvidence]


class QueryResponse(BaseModel):
    answer: str
    evidence: Evidence
    request_id: str
