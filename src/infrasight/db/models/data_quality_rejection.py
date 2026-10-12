from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column, relationship

from infrasight.db.base import Base


class DataQualityRejection(Base):
    __tablename__ = "data_quality_rejections"
    __table_args__ = (
        UniqueConstraint(
            "etl_run_id", "raw_telemetry_id", name="uq_data_quality_rejections_run_raw"
        ),
        CheckConstraint("btrim(error_code) <> ''", name="nonblank_error"),
        CheckConstraint(
            "CASE WHEN jsonb_typeof(validation_errors) = 'array' THEN "
            "jsonb_array_length(validation_errors) > 0 ELSE false END",
            name="nonempty_errors",
        ),
        Index("ix_data_quality_rejections_raw_telemetry_id", "raw_telemetry_id"),
        Index("ix_data_quality_rejections_rejected_at", "rejected_at"),
    )

    id = mapped_column(BigInteger, Identity(), primary_key=True)
    etl_run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("etl_runs.id", ondelete="RESTRICT"), nullable=False
    )
    raw_telemetry_id = mapped_column(
        BigInteger, ForeignKey("raw_telemetry.id", ondelete="RESTRICT"), nullable=False
    )
    error_code = mapped_column(Text, nullable=False)
    validation_errors = mapped_column(JSONB(none_as_null=True), nullable=False)
    rejected_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    etl_run = relationship("EtlRun")

    raw_telemetry = relationship("RawTelemetry")
