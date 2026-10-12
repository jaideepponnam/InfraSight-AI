from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship

from infrasight.db.base import Base


class InfrastructureMetric(Base):
    __tablename__ = "infrastructure_metrics"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "observed_at", name="uq_infrastructure_metrics_server_observed"
        ),
        UniqueConstraint("raw_telemetry_id", name="uq_infrastructure_metrics_raw_telemetry"),
        CheckConstraint("cpu_usage_percent BETWEEN 0 AND 100", name="valid_cpu"),
        CheckConstraint("memory_usage_percent BETWEEN 0 AND 100", name="valid_memory"),
        CheckConstraint("storage_usage_percent BETWEEN 0 AND 100", name="valid_storage"),
        CheckConstraint(
            "network_mbps >= 0 AND network_mbps < 'Infinity'::numeric", name="valid_network"
        ),
        CheckConstraint("uptime_seconds >= 0", name="valid_uptime"),
        CheckConstraint(
            "estimated_cost >= 0 AND estimated_cost < 'Infinity'::numeric", name="valid_cost"
        ),
        CheckConstraint("interval_seconds > 0", name="positive_interval"),
        CheckConstraint(
            "server_status IN ('RUNNING', 'DEGRADED', 'STOPPED', 'FAILED')", name="valid_status"
        ),
        CheckConstraint(
            "resource_health IN ('HEALTHY', 'WARNING', 'CRITICAL')", name="valid_health"
        ),
        CheckConstraint("(estimated_cost IS NULL) = (currency IS NULL)", name="cost_currency_pair"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="valid_currency"),
        Index("ix_infrastructure_metrics_server_observed_desc", "server_id", desc("observed_at")),
        Index("ix_infrastructure_metrics_observed_server", "observed_at", "server_id"),
        Index("ix_infrastructure_metrics_etl_run_id", "etl_run_id"),
    )

    id = mapped_column(BigInteger, Identity(), primary_key=True)
    server_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="RESTRICT"), nullable=False
    )
    etl_run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("etl_runs.id", ondelete="RESTRICT"), nullable=False
    )
    raw_telemetry_id = mapped_column(
        BigInteger, ForeignKey("raw_telemetry.id", ondelete="RESTRICT"), nullable=False
    )
    observed_at = mapped_column(DateTime(timezone=True), nullable=False)
    cpu_usage_percent = mapped_column(Numeric(5, 2), nullable=False)
    memory_usage_percent = mapped_column(Numeric(5, 2), nullable=False)
    storage_usage_percent = mapped_column(Numeric(5, 2), nullable=False)
    network_mbps = mapped_column(Numeric(14, 4), nullable=True)
    uptime_seconds = mapped_column(BigInteger, nullable=True)
    server_status = mapped_column(Text, nullable=False)
    resource_health = mapped_column(Text, nullable=False)
    estimated_cost = mapped_column(Numeric(18, 8), nullable=True)
    currency = mapped_column(String(3), nullable=True)
    interval_seconds = mapped_column(Integer, nullable=False)
    ingested_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    server = relationship("Server")

    etl_run = relationship("EtlRun")

    raw_telemetry = relationship("RawTelemetry")
