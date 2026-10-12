from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column

from infrasight.db.base import Base


class Region(Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("provider", "region_code", name="uq_regions_provider_code"),
        CheckConstraint(
            "btrim(provider) <> '' AND btrim(region_code) <> '' AND btrim(display_name) <> ''",
            name="nonblank_identity",
        ),
    )

    id = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider = mapped_column(Text, nullable=False)
    region_code = mapped_column(Text, nullable=False)
    display_name = mapped_column(Text, nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
