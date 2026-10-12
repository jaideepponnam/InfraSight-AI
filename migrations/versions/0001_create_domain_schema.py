"""create_domain_schema
Revision ID: 0001
Revises:
Create Date: 2026-10-11 19:53:58.959658
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Explicit, frozen schema operations; no application metadata imports.
    op.create_table(
        "etl_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column("requested_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "records_extracted", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("records_accepted", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("records_inserted", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "records_duplicated", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("records_rejected", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cursor_before",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "cursor_after",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("watermark_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "error_details",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint("btrim(source_id) <> ''", name=op.f("ck_etl_runs_nonblank_source")),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR (records_extracted = records_accepted + "
            "records_rejected AND records_accepted = records_inserted + "
            "records_duplicated)",
            name=op.f("ck_etl_runs_success_counts"),
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_etl_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('SUCCEEDED', 'FAILED') OR finished_at IS NOT NULL",
            name=op.f("ck_etl_runs_terminal_finished"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name=op.f("ck_etl_runs_execution_order"),
        ),
        sa.CheckConstraint(
            "records_accepted + records_rejected <= records_extracted AND "
            "records_inserted + records_duplicated <= records_accepted",
            name=op.f("ck_etl_runs_count_bounds"),
        ),
        sa.CheckConstraint(
            "records_extracted >= 0 AND records_accepted >= 0 AND records_inserted >= 0 "
            "AND records_duplicated >= 0 AND records_rejected >= 0",
            name=op.f("ck_etl_runs_nonnegative_counts"),
        ),
        sa.CheckConstraint(
            "requested_window_end > requested_window_start", name=op.f("ck_etl_runs_window_order")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etl_runs")),
    )
    op.create_index(
        "ix_etl_runs_source_requested",
        "etl_runs",
        ["source_id", sa.literal_column("requested_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_etl_runs_status_requested", "etl_runs", ["status", "requested_at"], unique=False
    )
    op.create_table(
        "regions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("region_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(provider) <> '' AND btrim(region_code) <> '' AND btrim(display_name) <> ''",
            name=op.f("ck_regions_nonblank_identity"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regions")),
        sa.UniqueConstraint("provider", "region_code", name="uq_regions_provider_code"),
    )
    op.create_table(
        "ingestion_state",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "cursor", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> ''", name=op.f("ck_ingestion_state_nonblank_source")
        ),
        sa.ForeignKeyConstraint(
            ["last_successful_run_id"],
            ["etl_runs.id"],
            name=op.f("fk_ingestion_state_last_successful_run_id_etl_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id", name=op.f("pk_ingestion_state")),
    )
    op.create_table(
        "raw_telemetry",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("etl_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> '' AND btrim(source_event_id) <> ''",
            name=op.f("ck_raw_telemetry_nonblank_identity"),
        ),
        sa.ForeignKeyConstraint(
            ["etl_run_id"],
            ["etl_runs.id"],
            name=op.f("fk_raw_telemetry_etl_run_id_etl_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_telemetry")),
        sa.UniqueConstraint("source_id", "source_event_id", name="uq_raw_telemetry_source_event"),
    )
    op.create_index("ix_raw_telemetry_etl_run_id", "raw_telemetry", ["etl_run_id"], unique=False)
    op.create_index(
        "ix_raw_telemetry_extracted_at", "raw_telemetry", ["extracted_at"], unique=False
    )
    op.create_table(
        "servers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("external_server_id", sa.Text(), nullable=False),
        sa.Column("server_name", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("region_id", sa.UUID(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> '' AND btrim(external_server_id) <> '' AND "
            "btrim(server_name) <> ''",
            name=op.f("ck_servers_nonblank_identity"),
        ),
        sa.CheckConstraint(
            "environment IN ('dev', 'staging', 'prod')", name=op.f("ck_servers_valid_environment")
        ),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name=op.f("ck_servers_seen_order")),
        sa.ForeignKeyConstraint(
            ["region_id"],
            ["regions.id"],
            name=op.f("fk_servers_region_id_regions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_servers")),
        sa.UniqueConstraint(
            "source_id", "external_server_id", name="uq_servers_source_external_id"
        ),
    )
    op.create_index("ix_servers_environment", "servers", ["environment"], unique=False)
    op.create_index(
        "ix_servers_region_environment", "servers", ["region_id", "environment"], unique=False
    )
    op.create_table(
        "data_quality_rejections",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("etl_run_id", sa.UUID(), nullable=False),
        sa.Column("raw_telemetry_id", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=False),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(validation_errors) = 'array' THEN "
            "jsonb_array_length(validation_errors) > 0 ELSE false END",
            name=op.f("ck_data_quality_rejections_nonempty_errors"),
        ),
        sa.CheckConstraint(
            "btrim(error_code) <> ''", name=op.f("ck_data_quality_rejections_nonblank_error")
        ),
        sa.ForeignKeyConstraint(
            ["etl_run_id"],
            ["etl_runs.id"],
            name=op.f("fk_data_quality_rejections_etl_run_id_etl_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_telemetry_id"],
            ["raw_telemetry.id"],
            name=op.f("fk_data_quality_rejections_raw_telemetry_id_raw_telemetry"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_rejections")),
        sa.UniqueConstraint(
            "etl_run_id", "raw_telemetry_id", name="uq_data_quality_rejections_run_raw"
        ),
    )
    op.create_index(
        "ix_data_quality_rejections_raw_telemetry_id",
        "data_quality_rejections",
        ["raw_telemetry_id"],
        unique=False,
    )
    op.create_index(
        "ix_data_quality_rejections_rejected_at",
        "data_quality_rejections",
        ["rejected_at"],
        unique=False,
    )
    op.create_table(
        "infrastructure_metrics",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("etl_run_id", sa.UUID(), nullable=False),
        sa.Column("raw_telemetry_id", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_usage_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("memory_usage_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("storage_usage_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("network_mbps", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=True),
        sa.Column("server_status", sa.Text(), nullable=False),
        sa.Column("resource_health", sa.Text(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_infrastructure_metrics_valid_currency")
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0 AND estimated_cost < 'Infinity'::numeric",
            name=op.f("ck_infrastructure_metrics_valid_cost"),
        ),
        sa.CheckConstraint(
            "network_mbps >= 0 AND network_mbps < 'Infinity'::numeric",
            name=op.f("ck_infrastructure_metrics_valid_network"),
        ),
        sa.CheckConstraint(
            "resource_health IN ('HEALTHY', 'WARNING', 'CRITICAL')",
            name=op.f("ck_infrastructure_metrics_valid_health"),
        ),
        sa.CheckConstraint(
            "server_status IN ('RUNNING', 'DEGRADED', 'STOPPED', 'FAILED')",
            name=op.f("ck_infrastructure_metrics_valid_status"),
        ),
        sa.CheckConstraint(
            "(estimated_cost IS NULL) = (currency IS NULL)",
            name=op.f("ck_infrastructure_metrics_cost_currency_pair"),
        ),
        sa.CheckConstraint(
            "cpu_usage_percent BETWEEN 0 AND 100", name=op.f("ck_infrastructure_metrics_valid_cpu")
        ),
        sa.CheckConstraint(
            "interval_seconds > 0", name=op.f("ck_infrastructure_metrics_positive_interval")
        ),
        sa.CheckConstraint(
            "memory_usage_percent BETWEEN 0 AND 100",
            name=op.f("ck_infrastructure_metrics_valid_memory"),
        ),
        sa.CheckConstraint(
            "storage_usage_percent BETWEEN 0 AND 100",
            name=op.f("ck_infrastructure_metrics_valid_storage"),
        ),
        sa.CheckConstraint(
            "uptime_seconds >= 0", name=op.f("ck_infrastructure_metrics_valid_uptime")
        ),
        sa.ForeignKeyConstraint(
            ["etl_run_id"],
            ["etl_runs.id"],
            name=op.f("fk_infrastructure_metrics_etl_run_id_etl_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_telemetry_id"],
            ["raw_telemetry.id"],
            name=op.f("fk_infrastructure_metrics_raw_telemetry_id_raw_telemetry"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_infrastructure_metrics_server_id_servers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_infrastructure_metrics")),
        sa.UniqueConstraint("raw_telemetry_id", name="uq_infrastructure_metrics_raw_telemetry"),
        sa.UniqueConstraint(
            "server_id", "observed_at", name="uq_infrastructure_metrics_server_observed"
        ),
    )
    op.create_index(
        "ix_infrastructure_metrics_etl_run_id",
        "infrastructure_metrics",
        ["etl_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_metrics_observed_server",
        "infrastructure_metrics",
        ["observed_at", "server_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_metrics_server_observed_desc",
        "infrastructure_metrics",
        ["server_id", sa.literal_column("observed_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "ix_infrastructure_metrics_server_observed_desc", table_name="infrastructure_metrics"
    )
    op.drop_index("ix_infrastructure_metrics_observed_server", table_name="infrastructure_metrics")
    op.drop_index("ix_infrastructure_metrics_etl_run_id", table_name="infrastructure_metrics")
    op.drop_table("infrastructure_metrics")
    op.drop_index("ix_data_quality_rejections_rejected_at", table_name="data_quality_rejections")
    op.drop_index(
        "ix_data_quality_rejections_raw_telemetry_id", table_name="data_quality_rejections"
    )
    op.drop_table("data_quality_rejections")
    op.drop_index("ix_servers_region_environment", table_name="servers")
    op.drop_index("ix_servers_environment", table_name="servers")
    op.drop_table("servers")
    op.drop_index("ix_raw_telemetry_extracted_at", table_name="raw_telemetry")
    op.drop_index("ix_raw_telemetry_etl_run_id", table_name="raw_telemetry")
    op.drop_table("raw_telemetry")
    op.drop_table("ingestion_state")
    op.drop_table("regions")
    op.drop_index("ix_etl_runs_status_requested", table_name="etl_runs")
    op.drop_index("ix_etl_runs_source_requested", table_name="etl_runs")
    op.drop_table("etl_runs")
