from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship

from infrasight.db.base import Base


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (
        UniqueConstraint("source_id", "external_server_id", name="uq_servers_source_external_id"),
        CheckConstraint(
            "btrim(source_id) <> '' AND btrim(external_server_id) <> '' AND "
            "btrim(server_name) <> ''",
            name="nonblank_identity",
        ),
        CheckConstraint("environment IN ('dev', 'staging', 'prod')", name="valid_environment"),
        CheckConstraint("last_seen_at >= first_seen_at", name="seen_order"),
        Index("ix_servers_region_environment", "region_id", "environment"),
        Index("ix_servers_environment", "environment"),
    )

    id = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_id = mapped_column(Text, nullable=False)
    external_server_id = mapped_column(Text, nullable=False)
    server_name = mapped_column(Text, nullable=False)
    environment = mapped_column(Text, nullable=False)
    region_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    first_seen_at = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at = mapped_column(DateTime(timezone=True), nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    region = relationship("Region")
