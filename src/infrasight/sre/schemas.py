from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from infrasight.sre.lifecycle import STATES


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExerciseRequest(StrictRequest):
    scenario: Literal["http-503"] = "http-503"


class RecoveryRequest(StrictRequest):
    action: Literal["clear-controlled-dependency-fault"] = "clear-controlled-dependency-fault"


class IncidentFilter(StrictRequest):
    state: Literal[*STATES] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ServiceView(FromAttributes):
    id: UUID
    service_key: str
    description: str
    created_at: datetime


class RunView(FromAttributes):
    id: UUID
    service_id: UUID
    scenario: str
    status: str
    phase: str
    fault_enabled: bool
    fault_expires_at: datetime | None
    fault_cleared_at: datetime | None
    deadline_at: datetime
    finished_at: datetime | None
    error_code: str | None
    created_at: datetime


class IncidentView(FromAttributes):
    id: UUID
    service_id: UUID
    run_id: UUID
    title: str
    severity: str
    state: str
    policy_version: str
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    version: int


class EventView(FromAttributes):
    id: UUID
    incident_id: UUID
    sequence: int
    event_type: str
    actor: str
    from_state: str | None
    to_state: str
    request_id: UUID
    evidence: dict[str, Any]
    created_at: datetime


class ProbeView(FromAttributes):
    id: UUID
    run_id: UUID
    phase: str
    observed_at: datetime
    duration_ms: Decimal
    http_status: int | None
    outcome: str
    target_request_id: UUID | None
    request_id: UUID
    evidence: dict[str, Any]


class RecoveryView(FromAttributes):
    id: UUID
    incident_id: UUID
    action: str
    status: str
    error_code: str | None
    action_applied: bool
    evidence: dict[str, Any]
    request_id: UUID
    started_at: datetime
    finished_at: datetime | None


class DiagnosticEvidence(StrictRequest):
    run: RunView
    probes: list[ProbeView]
    recovery_attempts: list[RecoveryView]


class Metadata(BaseModel):
    request_id: UUID
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


T = TypeVar("T")


class SREEnvelope(BaseModel, Generic[T]):
    data: T
    meta: Metadata
