from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Text,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column

from infrasight.db.base import Base


class EtlRun(Base):
    __tablename__ = "etl_runs"
    __table_args__ = (
        CheckConstraint("btrim(source_id) <> ''", name="nonblank_source"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", name="valid_status"
        ),
        CheckConstraint("requested_window_end > requested_window_start", name="window_order"),
        CheckConstraint(
            "records_extracted >= 0 AND records_accepted >= 0 AND records_inserted >= 0 "
            "AND records_duplicated >= 0 AND records_rejected >= 0",
            name="nonnegative_counts",
        ),
        CheckConstraint(
            "records_accepted + records_rejected <= records_extracted AND "
            "records_inserted + records_duplicated <= records_accepted",
            name="count_bounds",
        ),
        CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name="execution_order",
        ),
        CheckConstraint(
            "status NOT IN ('SUCCEEDED', 'FAILED') OR finished_at IS NOT NULL",
            name="terminal_finished",
        ),
        CheckConstraint(
            "status <> 'SUCCEEDED' OR (records_extracted = records_accepted + "
            "records_rejected AND records_accepted = records_inserted + "
            "records_duplicated)",
            name="success_counts",
        ),
        Index("ix_etl_runs_status_requested", "status", "requested_at"),
        Index("ix_etl_runs_source_requested", "source_id", desc("requested_at")),
    )

    id = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_id = mapped_column(Text, nullable=False)
    status = mapped_column(Text, nullable=False, server_default=text("'QUEUED'"))
    requested_window_start = mapped_column(DateTime(timezone=True), nullable=False)
    requested_window_end = mapped_column(DateTime(timezone=True), nullable=False)
    requested_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at = mapped_column(DateTime(timezone=True), nullable=True)
    records_extracted = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    records_accepted = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    records_inserted = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    records_duplicated = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    records_rejected = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cursor_before = mapped_column(JSONB(none_as_null=True), nullable=True)
    cursor_after = mapped_column(JSONB(none_as_null=True), nullable=True)
    watermark_before = mapped_column(DateTime(timezone=True), nullable=True)
    watermark_after = mapped_column(DateTime(timezone=True), nullable=True)
    error_code = mapped_column(Text, nullable=True)
    error_message = mapped_column(Text, nullable=True)
    error_details = mapped_column(JSONB(none_as_null=True), nullable=True)
