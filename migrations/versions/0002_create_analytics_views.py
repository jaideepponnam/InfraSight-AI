"""Stable analytics views; no parameter-dependent session settings.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen SQL: migration execution never imports a mutable application SQL file.
SQL = r"""-- Stable datasets: no custom connection/session settings. UTC boundaries are explicit.
CREATE SCHEMA analytics;

CREATE VIEW analytics.high_resource_usage AS
SELECT m.id AS metric_id, s.id AS server_id, s.external_server_id, s.server_name,
       s.source_id, r.provider, r.id AS region_id, r.region_code,
       r.display_name AS region_display_name, s.environment, m.observed_at,
       m.observed_at + m.interval_seconds * INTERVAL '1 second' AS interval_end,
       m.cpu_usage_percent, m.memory_usage_percent, m.storage_usage_percent,
       m.network_mbps, m.uptime_seconds, m.server_status, m.resource_health,
       m.estimated_cost, m.currency, m.interval_seconds
FROM public.infrastructure_metrics m
JOIN public.servers s ON s.id = m.server_id
JOIN public.regions r ON r.id = s.region_id;

CREATE VIEW analytics.latest_server_metrics AS
WITH reference AS (SELECT statement_timestamp() AS reference_time)
SELECT s.id AS server_id, s.external_server_id, s.server_name, s.source_id,
       r.provider, r.id AS region_id, r.region_code, r.display_name AS region_display_name,
       s.environment, s.first_seen_at, s.last_seen_at, m.metric_id, m.observed_at,
       m.interval_end, m.cpu_usage_percent, m.memory_usage_percent, m.storage_usage_percent,
       m.network_mbps, m.uptime_seconds, m.server_status, m.resource_health,
       m.estimated_cost, m.currency, m.interval_seconds, ref.reference_time,
       EXTRACT(EPOCH FROM ref.reference_time - m.observed_at) AS observation_age_seconds,
       EXTRACT(EPOCH FROM ref.reference_time - m.interval_end) AS completion_age_seconds,
       120 AS freshness_threshold_seconds,
       COALESCE(m.interval_end >= ref.reference_time - INTERVAL '120 seconds', false) AS is_current,
       CASE WHEN m.metric_id IS NULL THEN 'NO_DATA'
            WHEN m.interval_end < ref.reference_time - INTERVAL '120 seconds' THEN 'STALE'
            ELSE 'FRESH' END AS freshness
FROM public.servers s
JOIN public.regions r ON r.id = s.region_id
CROSS JOIN reference ref
LEFT JOIN LATERAL (
    SELECT m.id AS metric_id, m.observed_at,
           m.observed_at + m.interval_seconds * INTERVAL '1 second' AS interval_end,
           m.cpu_usage_percent, m.memory_usage_percent, m.storage_usage_percent,
           m.network_mbps, m.uptime_seconds, m.server_status, m.resource_health,
           m.estimated_cost, m.currency, m.interval_seconds
    FROM public.infrastructure_metrics m
    WHERE m.server_id = s.id AND m.observed_at <= ref.reference_time
      AND m.observed_at + m.interval_seconds * INTERVAL '1 second' <= ref.reference_time
    ORDER BY m.observed_at DESC LIMIT 1
) m ON true;

CREATE VIEW analytics.server_health_summary AS
SELECT server_id, external_server_id, server_name, source_id, provider, region_id,
       region_code, region_display_name, environment, observed_at, interval_end,
       cpu_usage_percent, memory_usage_percent, storage_usage_percent, server_status,
       resource_health AS recorded_resource_health, reference_time,
       freshness_threshold_seconds, completion_age_seconds, is_current, freshness,
       CASE WHEN freshness = 'NO_DATA' THEN 'NO_DATA'
            WHEN NOT is_current THEN 'STALE' ELSE resource_health END AS effective_health
FROM analytics.latest_server_metrics;

-- Private helper: cost is allocated with cumulative NUMERIC differences, not rounded rates.
CREATE VIEW analytics._daily_metric_intervals AS
WITH boundaries AS (
    SELECT h.*, ((h.observed_at AT TIME ZONE 'UTC')::date + days.n) AS utc_day,
           (((h.observed_at AT TIME ZONE 'UTC')::date + days.n)::timestamp
              AT TIME ZONE 'UTC') AS day_start
    FROM analytics.high_resource_usage h
    CROSS JOIN LATERAL generate_series(0,
        ((h.interval_end - INTERVAL '1 microsecond') AT TIME ZONE 'UTC')::date
        - (h.observed_at AT TIME ZONE 'UTC')::date) days(n)
), segments AS (
    SELECT b.*, GREATEST(observed_at, day_start) AS segment_start,
           LEAST(interval_end, day_start + INTERVAL '24 hours') AS segment_end
    FROM boundaries b
)
SELECT metric_id, server_id, external_server_id, server_name, source_id, provider,
       region_id, region_code, region_display_name, environment, utc_day, observed_at,
       interval_end, segment_start, segment_end,
       EXTRACT(EPOCH FROM segment_end - segment_start) AS covered_seconds,
       cpu_usage_percent, memory_usage_percent, storage_usage_percent, network_mbps,
       resource_health, currency,
       estimated_cost * EXTRACT(EPOCH FROM segment_end - observed_at) / interval_seconds
       - estimated_cost * EXTRACT(EPOCH FROM segment_start - observed_at) / interval_seconds
       AS allocated_cost
FROM segments;

CREATE VIEW analytics.daily_infrastructure_summary AS
SELECT utc_day, source_id, provider, region_id, region_code, region_display_name,
       environment, currency, COUNT(DISTINCT server_id) AS reporting_server_count,
       COUNT(*) AS observation_count, SUM(covered_seconds) AS observation_seconds,
       SUM(cpu_usage_percent * covered_seconds) / SUM(covered_seconds) AS average_cpu_percent,
       SUM(memory_usage_percent * covered_seconds) / SUM(covered_seconds) AS average_memory_percent,
       SUM(storage_usage_percent * covered_seconds) / SUM(covered_seconds) AS
       average_storage_percent,
       SUM(network_mbps * covered_seconds)
           / NULLIF(SUM(covered_seconds) FILTER (WHERE network_mbps IS NOT NULL), 0)
           AS average_network_mbps,
       COUNT(*) FILTER (WHERE resource_health = 'WARNING') AS warning_observations,
       COUNT(*) FILTER (WHERE resource_health = 'CRITICAL') AS critical_observations,
       SUM(allocated_cost) AS estimated_cost,
       COUNT(allocated_cost) AS priced_observation_count,
       COALESCE(SUM(covered_seconds) FILTER (WHERE allocated_cost IS NOT NULL), 0)
           AS priced_observation_seconds
FROM analytics._daily_metric_intervals
GROUP BY utc_day, source_id, provider, region_id, region_code, region_display_name,
         environment, currency;

CREATE VIEW analytics.daily_cloud_cost_summary AS
SELECT utc_day, server_id, external_server_id, server_name, source_id, provider,
       region_id, region_code, region_display_name, environment, currency,
       COUNT(*) AS observation_count, COUNT(allocated_cost) AS priced_observation_count,
       SUM(covered_seconds) AS observation_seconds, SUM(allocated_cost) AS estimated_cost
FROM analytics._daily_metric_intervals
GROUP BY utc_day, server_id, external_server_id, server_name, source_id, provider,
         region_id, region_code, region_display_name, environment, currency;

CREATE VIEW analytics.region_usage_summary AS
SELECT source_id, provider, region_id, region_code, region_display_name, environment,
       currency, COUNT(*) AS inventory_server_count,
       COUNT(*) FILTER (WHERE is_current) AS reporting_server_count,
       AVG(cpu_usage_percent) FILTER (WHERE is_current) AS average_cpu_percent,
       AVG(memory_usage_percent) FILTER (WHERE is_current) AS average_memory_percent,
       AVG(storage_usage_percent) FILTER (WHERE is_current) AS average_storage_percent,
       COUNT(*) FILTER (WHERE is_current AND resource_health = 'HEALTHY') AS healthy_server_count,
       COUNT(*) FILTER (WHERE is_current AND resource_health = 'WARNING') AS warning_server_count,
       COUNT(*) FILTER (WHERE is_current AND resource_health = 'CRITICAL') AS critical_server_count,
       COUNT(*) FILTER (WHERE metric_id IS NOT NULL AND NOT is_current) AS stale_server_count,
       COUNT(*) FILTER (WHERE metric_id IS NULL) AS no_data_server_count,
       SUM(estimated_cost) FILTER (WHERE is_current) AS latest_interval_estimated_cost,
       COUNT(estimated_cost) FILTER (WHERE is_current) AS priced_current_server_count,
       MIN(interval_seconds) FILTER (WHERE is_current AND estimated_cost IS NOT NULL)
           AS cost_min_interval_seconds,
       MAX(interval_seconds) FILTER (WHERE is_current AND estimated_cost IS NOT NULL)
           AS cost_max_interval_seconds,
       'SUM_OF_FRESH_LATEST_INTERVALS'::text AS cost_basis,
       MAX(observed_at) AS last_observation_at, MAX(completion_age_seconds) AS
       oldest_completion_age_seconds,
       MAX(reference_time) AS reference_time, 120 AS freshness_threshold_seconds
FROM analytics.latest_server_metrics
GROUP BY source_id, provider, region_id, region_code, region_display_name, environment, currency;
"""


def upgrade():
    for statement in SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    for view in (
        "region_usage_summary",
        "daily_cloud_cost_summary",
        "daily_infrastructure_summary",
        "_daily_metric_intervals",
        "server_health_summary",
        "latest_server_metrics",
        "high_resource_usage",
    ):
        op.execute(f"DROP VIEW analytics.{view}")
    op.execute("DROP SCHEMA analytics")
