from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column, relationship

from infrasight.db.base import Base


class IngestionState(Base):
    __tablename__ = "ingestion_state"
    __table_args__ = (CheckConstraint("btrim(source_id) <> ''", name="nonblank_source"),)

    source_id = mapped_column(Text, primary_key=True)
    cursor = mapped_column(JSONB(none_as_null=True), nullable=True)
    watermark = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_run_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("etl_runs.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    last_successful_run = relationship("EtlRun")
