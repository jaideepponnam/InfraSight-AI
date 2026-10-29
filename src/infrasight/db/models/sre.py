"""SRE tables are independent of the seven legacy telemetry tables."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column

from infrasight.db.base import Base


def identifier():
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created():
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SREService(Base):
    __tablename__ = "sre_services"
    __table_args__ = (
        UniqueConstraint("service_key", name="uq_sre_services_key"),
        CheckConstraint(
            "service_key = 'controlled-application-dependency'", name="approved_service"
        ),
    )
    id = identifier()
    service_key = mapped_column(Text, nullable=False)
    description = mapped_column(Text, nullable=False)
    created_at = created()


class SREDemoRun(Base):
    __tablename__ = "sre_demo_runs"
    __table_args__ = (
        CheckConstraint("scenario = 'http-503'", name="approved_scenario"),
        CheckConstraint(
            "status IN ('ACTIVE','SUCCEEDED','FAILED','INTERRUPTED')", name="valid_status"
        ),
        CheckConstraint(
            "phase IN ('CREATED','BASELINE','FAULT','DETECTED','RECOVERY','COMPLETE')",
            name="valid_phase",
        ),
        CheckConstraint("deadline_at > created_at", name="deadline_order"),
        CheckConstraint(
            "fault_expires_at IS NULL OR fault_expires_at <= deadline_at", name="fault_deadline"
        ),
        CheckConstraint("status = 'ACTIVE' OR finished_at IS NOT NULL", name="terminal_finished"),
        UniqueConstraint("service_id", "idempotency_key", name="uq_sre_demo_runs_request"),
        Index(
            "ix_sre_demo_runs_active_service",
            "service_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_sre_demo_runs_created_at", "created_at"),
    )
    id = identifier()
    service_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_services.id", ondelete="RESTRICT"), nullable=False
    )
    scenario = mapped_column(Text, nullable=False)
    idempotency_key = mapped_column(Text, nullable=False)
    status = mapped_column(Text, nullable=False, server_default=text("'ACTIVE'"))
    phase = mapped_column(Text, nullable=False, server_default=text("'CREATED'"))
    # Only a hash is stored; the capability itself never leaves server-side probe code.
    probe_token_hash = mapped_column(Text, nullable=False)
    fault_enabled = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fault_expires_at = mapped_column(DateTime(timezone=True), nullable=True)
    fault_cleared_at = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_code = mapped_column(Text, nullable=True)
    created_at = created()


class SREProbeResult(Base):
    __tablename__ = "sre_probe_results"
    __table_args__ = (
        CheckConstraint("phase IN ('BASELINE','DETECTION','VERIFICATION')", name="valid_phase"),
        CheckConstraint(
            "outcome IN ('HEALTHY','HTTP_503','UNEXPECTED_HTTP','TIMEOUT','TRANSPORT_ERROR',"
            "'INVALID_RESPONSE')",
            name="valid_outcome",
        ),
        CheckConstraint("duration_ms >= 0", name="positive_duration"),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="valid_http"
        ),
        Index("ix_sre_probe_results_run_observed", "run_id", "observed_at"),
    )
    id = identifier()
    run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_demo_runs.id", ondelete="RESTRICT"), nullable=False
    )
    phase = mapped_column(Text, nullable=False)
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms = mapped_column(Numeric(12, 3), nullable=False)
    http_status = mapped_column(Integer, nullable=True)
    outcome = mapped_column(Text, nullable=False)
    target_request_id = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence = mapped_column(JSONB, nullable=False)


class SREIncident(Base):
    __tablename__ = "sre_incidents"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DETECTED','ACKNOWLEDGED','INVESTIGATING','MITIGATING',"
            "'VERIFYING','RESOLVED')",
            name="valid_state",
        ),
        CheckConstraint("severity = 'SEV3'", name="valid_severity"),
        CheckConstraint(
            "state <> 'RESOLVED' OR resolved_at IS NOT NULL", name="resolved_timestamp"
        ),
        CheckConstraint("resolved_at IS NULL OR resolved_at >= detected_at", name="resolved_order"),
        Index(
            "ix_sre_incidents_active_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("state <> 'RESOLVED'"),
        ),
        Index("ix_sre_incidents_detected_at", "detected_at"),
    )
    id = identifier()
    service_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_services.id", ondelete="RESTRICT"), nullable=False
    )
    run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_demo_runs.id", ondelete="RESTRICT"), nullable=False
    )
    fingerprint = mapped_column(Text, nullable=False)
    title = mapped_column(Text, nullable=False)
    severity = mapped_column(Text, nullable=False, server_default=text("'SEV3'"))
    state = mapped_column(Text, nullable=False, server_default=text("'DETECTED'"))
    policy_version = mapped_column(Text, nullable=False)
    detected_at = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
    version = mapped_column(Integer, nullable=False, server_default=text("1"))


class SREIncidentEvent(Base):
    __tablename__ = "sre_incident_events"
    __table_args__ = (
        UniqueConstraint("incident_id", "sequence", name="uq_sre_incident_events_sequence"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint(
            "actor IN ('admin-key','admin-exercise-runner','system')", name="valid_actor"
        ),
    )
    id = identifier()
    incident_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_incidents.id", ondelete="RESTRICT"), nullable=False
    )
    sequence = mapped_column(Integer, nullable=False)
    event_type = mapped_column(Text, nullable=False)
    actor = mapped_column(Text, nullable=False)
    from_state = mapped_column(Text, nullable=True)
    to_state = mapped_column(Text, nullable=False)
    request_id = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence = mapped_column(JSONB, nullable=False)
    created_at = created()


class SRERecoveryAttempt(Base):
    __tablename__ = "sre_recovery_attempts"
    __table_args__ = (
        UniqueConstraint("incident_id", "idempotency_key", name="uq_sre_recovery_attempts_request"),
        CheckConstraint("action = 'clear-controlled-dependency-fault'", name="approved_action"),
        CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','INTERRUPTED')", name="valid_status"
        ),
        CheckConstraint("status = 'RUNNING' OR finished_at IS NOT NULL", name="terminal_finished"),
        Index(
            "ix_sre_recovery_attempts_active_incident",
            "incident_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )
    id = identifier()
    incident_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("sre_incidents.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key = mapped_column(Text, nullable=False)
    action = mapped_column(Text, nullable=False)
    status = mapped_column(Text, nullable=False, server_default=text("'RUNNING'"))
    error_code = mapped_column(Text, nullable=True)
    action_applied = mapped_column(Boolean, nullable=False, server_default=text("false"))
    evidence = mapped_column(JSONB, nullable=False)
    request_id = mapped_column(UUID(as_uuid=True), nullable=False)
    started_at = created()
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
