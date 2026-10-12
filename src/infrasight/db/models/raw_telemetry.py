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


class RawTelemetry(Base):
    __tablename__ = "raw_telemetry"
    __table_args__ = (
        UniqueConstraint("source_id", "source_event_id", name="uq_raw_telemetry_source_event"),
        CheckConstraint(
            "btrim(source_id) <> '' AND btrim(source_event_id) <> ''", name="nonblank_identity"
        ),
        Index("ix_raw_telemetry_etl_run_id", "etl_run_id"),
        Index("ix_raw_telemetry_extracted_at", "extracted_at"),
    )

    id = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id = mapped_column(Text, nullable=False)
    source_event_id = mapped_column(Text, nullable=False)
    etl_run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("etl_runs.id", ondelete="RESTRICT"), nullable=False
    )
    payload = mapped_column(JSONB(none_as_null=True), nullable=False)
    extracted_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    etl_run = relationship("EtlRun")
