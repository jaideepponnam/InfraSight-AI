from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from infrasight.analytics.schemas import Scope

# These identifiers are internal constants, never user-provided SQL fragments.
FILTER = """source_id = COALESCE(CAST(:source_id AS text), source_id)
AND region_code = COALESCE(CAST(:region_code AS text), region_code)
AND environment = COALESCE(CAST(:environment AS text), environment)"""

HEALTH_CTES = (
    """
inventory AS (
    SELECT server_id, external_server_id, server_name, source_id, provider,
           region_id, region_code, region_display_name, environment
    FROM analytics.latest_server_metrics WHERE """
    + FILTER
    + """
), health AS (
    SELECT i.*, h.metric_id, h.observed_at, h.interval_end, h.cpu_usage_percent,
           h.memory_usage_percent, h.storage_usage_percent, h.server_status,
           h.resource_health AS recorded_resource_health,
           EXTRACT(EPOCH FROM CAST(:as_of AS timestamptz) - h.interval_end) AS
       completion_age_seconds,
           COALESCE(h.interval_end >= CAST(:as_of AS timestamptz)
                    - :freshness_seconds * INTERVAL '1 second', false) AS is_current,
           CASE WHEN h.metric_id IS NULL THEN 'NO_DATA'
                WHEN h.interval_end < CAST(:as_of AS timestamptz)
                     - :freshness_seconds * INTERVAL '1 second' THEN 'STALE'
                ELSE h.resource_health END AS effective_health
    FROM inventory i
    LEFT JOIN LATERAL (
        SELECT metric_id, observed_at, interval_end, cpu_usage_percent, memory_usage_percent,
               storage_usage_percent, server_status, resource_health
        FROM analytics.high_resource_usage h
        WHERE h.server_id = i.server_id AND h.observed_at <= CAST(:as_of AS timestamptz)
          AND h.interval_end <= CAST(:as_of AS timestamptz)
        ORDER BY h.observed_at DESC LIMIT 1
    ) h ON true
)
"""
)

WINDOW_CTES = (
    """
eligible AS (
    SELECT h.*, GREATEST(observed_at, CAST(:start AS timestamptz)) AS segment_start,
           LEAST(interval_end, CAST(:end AS timestamptz)) AS segment_end
    FROM analytics.high_resource_usage h
    WHERE observed_at < CAST(:end AS timestamptz)
      AND interval_end > CAST(:start AS timestamptz)
      AND interval_end <= CAST(:as_of AS timestamptz) AND """
    + FILTER
    + """
), measures AS (
    SELECT e.*, EXTRACT(EPOCH FROM segment_end - segment_start) AS covered_seconds,
           estimated_cost * EXTRACT(EPOCH FROM segment_end - observed_at) / interval_seconds
           - estimated_cost * EXTRACT(EPOCH FROM segment_start - observed_at) / interval_seconds
           AS window_cost
    FROM eligible e
), aggregates AS (
    SELECT server_id, external_server_id, server_name, source_id, provider,
           region_id, region_code, region_display_name, environment,
           COUNT(*) AS observation_count, SUM(covered_seconds) AS summed_observation_seconds,
           SUM(cpu_usage_percent * covered_seconds) / SUM(covered_seconds) AS average_cpu_percent,
           SUM(memory_usage_percent * covered_seconds) / SUM(covered_seconds) AS
       average_memory_percent,
           MAX(cpu_usage_percent) AS peak_cpu_percent,
           COUNT(*) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS breach_count,
           MIN(observed_at) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS first_breach_at,
           MAX(observed_at) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS last_breach_at,
           BOOL_OR(resource_health = 'CRITICAL') AS had_critical,
           SUM(window_cost) FILTER (WHERE currency = CAST(:currency AS text)) AS estimated_cost,
           COUNT(*) FILTER (WHERE estimated_cost IS NULL) AS unpriced_observation_count,
           range_agg(tstzrange(segment_start, segment_end, '[)')) AS observed_ranges,
           range_agg(tstzrange(segment_start, segment_end, '[)'))
               FILTER (WHERE currency = CAST(:currency AS text) AND estimated_cost IS NOT NULL)
               AS priced_ranges
    FROM measures
    GROUP BY server_id, external_server_id, server_name, source_id, provider,
             region_id, region_code, region_display_name, environment
), coverage AS (
    SELECT a.*,
           (SELECT SUM(EXTRACT(EPOCH FROM upper(r) - lower(r)))
            FROM unnest(observed_ranges) r) AS coverage_seconds,
           COALESCE((SELECT SUM(EXTRACT(EPOCH FROM upper(r) - lower(r)))
                     FROM unnest(priced_ranges) r), 0) AS priced_coverage_seconds
    FROM aggregates a
), stats AS (
    SELECT c.*, coverage_seconds / EXTRACT(EPOCH FROM CAST(:end AS timestamptz)
                                                          - CAST(:start AS timestamptz)) AS
       coverage_fraction,
           priced_coverage_seconds / EXTRACT(EPOCH FROM CAST(:end AS timestamptz)
                                                                 - CAST(:start AS timestamptz)) AS
       cost_coverage_fraction,
           summed_observation_seconds > coverage_seconds AS overlap_detected,
           breach_count::numeric / observation_count AS breach_fraction
    FROM coverage c
)
"""
)

HEALTH_SQL = "WITH " + HEALTH_CTES + "SELECT * FROM health ORDER BY server_id LIMIT :limit"
TOTALS_SQL = (
    "WITH "
    + HEALTH_CTES
    + """
SELECT COUNT(*) AS inventory_servers, COUNT(metric_id) AS servers_with_observations,
       COUNT(*) FILTER (WHERE is_current) AS reporting_servers,
       COUNT(*) FILTER (WHERE effective_health = 'HEALTHY') AS healthy_servers,
       COUNT(*) FILTER (WHERE effective_health = 'WARNING') AS warning_servers,
       COUNT(*) FILTER (WHERE effective_health = 'CRITICAL') AS critical_servers,
       COUNT(*) FILTER (WHERE effective_health = 'STALE') AS stale_servers,
       COUNT(*) FILTER (WHERE effective_health = 'NO_DATA') AS no_data_servers,
       AVG(cpu_usage_percent) FILTER (WHERE is_current) AS average_cpu_percent,
       AVG(memory_usage_percent) FILTER (WHERE is_current) AS average_memory_percent,
       AVG(storage_usage_percent) FILTER (WHERE is_current) AS average_storage_percent
FROM health
"""
)
REGIONAL_HEALTH_SQL = (
    "WITH "
    + HEALTH_CTES
    + """
SELECT source_id, provider, region_code, region_display_name, COUNT(*) AS inventory_servers,
       COUNT(*) FILTER (WHERE is_current) AS reporting_servers,
       COUNT(*) FILTER (WHERE effective_health = 'HEALTHY') AS healthy_servers,
       COUNT(*) FILTER (WHERE effective_health = 'WARNING') AS warning_servers,
       COUNT(*) FILTER (WHERE effective_health = 'CRITICAL') AS critical_servers,
       COUNT(*) FILTER (WHERE effective_health = 'STALE') AS stale_servers,
       COUNT(*) FILTER (WHERE effective_health = 'NO_DATA') AS no_data_servers,
       AVG(cpu_usage_percent) FILTER (WHERE is_current) AS average_cpu_percent
FROM health GROUP BY source_id, provider, region_code, region_display_name
ORDER BY critical_servers DESC, region_code, source_id LIMIT :limit
"""
)
BREACH_SQL = (
    """
SELECT server_id, external_server_id, server_name, source_id, provider, region_code, environment,
       MAX(cpu_usage_percent) AS peak_cpu_percent,
       COUNT(*) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS breach_count,
       MIN(observed_at) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS first_breach_at,
       MAX(observed_at) FILTER (WHERE cpu_usage_percent > :cpu_threshold) AS last_breach_at
FROM analytics.high_resource_usage
WHERE observed_at >= CAST(:start AS timestamptz) AND observed_at < CAST(:end AS timestamptz)
  AND interval_end <= CAST(:as_of AS timestamptz) AND """
    + FILTER
    + """
GROUP BY server_id, external_server_id, server_name, source_id, provider, region_code, environment
HAVING COUNT(*) FILTER (WHERE cpu_usage_percent > :cpu_threshold) > 0
ORDER BY peak_cpu_percent DESC, server_id LIMIT :limit
"""
)
PRESSURE_SQL = (
    "WITH "
    + WINDOW_CTES
    + """
SELECT server_id, external_server_id, server_name, source_id, provider, region_code, environment,
       observation_count, average_cpu_percent, peak_cpu_percent, breach_count, breach_fraction,
       coverage_seconds, coverage_fraction, first_breach_at, last_breach_at, overlap_detected
FROM stats WHERE observation_count >= :min_samples AND coverage_fraction >= :min_coverage
  AND breach_fraction >= :min_breach_fraction AND NOT overlap_detected
ORDER BY breach_fraction DESC, peak_cpu_percent DESC, server_id LIMIT :limit
"""
)
UNDERUTILIZED_SQL = (
    "WITH "
    + HEALTH_CTES
    + ","
    + WINDOW_CTES
    + """
SELECT s.server_id, s.external_server_id, s.server_name, s.source_id, s.provider, s.region_code,
       s.environment, s.average_cpu_percent, s.average_memory_percent, s.observation_count,
       s.coverage_seconds, s.coverage_fraction, s.cost_coverage_fraction, s.estimated_cost,
       CAST(:currency AS text) AS currency, h.effective_health AS latest_health,
       h.observed_at AS latest_observed_at, h.completion_age_seconds,
       'OPTIMIZATION_CANDIDATE'::text AS recommendation_type
FROM stats s JOIN health h USING (server_id)
WHERE observation_count >= :min_samples AND coverage_fraction >= :min_coverage
  AND cost_coverage_fraction >= :min_coverage AND NOT overlap_detected AND NOT had_critical
  AND average_cpu_percent < :max_cpu AND average_memory_percent < :max_memory
  AND estimated_cost >= :min_cost AND h.effective_health = 'HEALTHY'
ORDER BY estimated_cost DESC, s.server_id LIMIT :limit
"""
)
TOP_COST_SQL = (
    "WITH "
    + WINDOW_CTES
    + """
SELECT server_id, external_server_id, server_name, source_id, provider, region_code, environment,
       estimated_cost, CAST(:currency AS text) AS currency, observation_count,
       coverage_fraction, cost_coverage_fraction, overlap_detected
FROM stats WHERE estimated_cost IS NOT NULL
ORDER BY estimated_cost DESC, server_id LIMIT :limit
"""
)
FLEET_COST_SQL = (
    "WITH "
    + HEALTH_CTES
    + ","
    + WINDOW_CTES
    + """
SELECT currency, SUM(window_cost) AS estimated_cost, COUNT(*) AS observation_count,
       COUNT(window_cost) AS priced_observation_count,
       COUNT(DISTINCT server_id) AS reporting_server_count,
       (SELECT COUNT(*) FROM inventory) AS expected_server_count,
       (SELECT SUM(coverage_seconds) FROM stats)
           / NULLIF((SELECT COUNT(*) FROM inventory) * EXTRACT(EPOCH FROM
             CAST(:end AS timestamptz) - CAST(:start AS timestamptz)), 0)
           AS telemetry_coverage_fraction,
       COALESCE((SELECT BOOL_OR(overlap_detected) FROM stats), false) AS overlap_detected
FROM measures WHERE CAST(:currency AS text) IS NULL OR currency = CAST(:currency AS text)
GROUP BY currency ORDER BY currency NULLS LAST
"""
)
PERIOD_COST_SQL = (
    "WITH "
    + HEALTH_CTES
    + ","
    + WINDOW_CTES
    + """
SELECT SUM(estimated_cost) AS estimated_cost, CAST(:currency AS text) AS currency,
       COALESCE(SUM(observation_count), 0)::bigint AS observation_count,
       COUNT(*) AS reporting_server_count,
       (SELECT COUNT(*) FROM inventory) AS expected_server_count,
       COALESCE(SUM(coverage_seconds), 0)
           / NULLIF((SELECT COUNT(*) FROM inventory) * EXTRACT(EPOCH FROM
                 CAST(:end AS timestamptz) - CAST(:start AS timestamptz)), 0) AS coverage_fraction,
       COALESCE(SUM(priced_coverage_seconds), 0)
           / NULLIF((SELECT COUNT(*) FROM inventory) * EXTRACT(EPOCH FROM
                 CAST(:end AS timestamptz) - CAST(:start AS timestamptz)), 0) AS
       cost_coverage_fraction,
       COALESCE(BOOL_OR(overlap_detected), false) AS overlap_detected
FROM stats
"""
)


class AnalyticsRepository:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def parameters(query: Scope):
        values = query.model_dump()
        values.setdefault("cpu_threshold", Decimal("80"))
        values.setdefault("currency", None)
        return values

    def rows(self, statement, query):
        rows = self.connection.execute(text(statement), self.parameters(query)).mappings()
        return [
            {
                key: value.astimezone(UTC) if isinstance(value, datetime) else value
                for key, value in row.items()
            }
            for row in rows
        ]

    def health(self, query):
        return self.rows(HEALTH_SQL, query)

    def totals(self, query):
        return self.rows(TOTALS_SQL, query)

    def regional_health(self, query):
        return self.rows(REGIONAL_HEALTH_SQL, query)

    def critical(self, query):
        return self.rows(
            "WITH " + HEALTH_CTES + "SELECT * FROM health WHERE effective_health = 'CRITICAL' "
            "ORDER BY server_id LIMIT :limit",
            query,
        )

    def top_resource(self, query, resource):
        if resource not in {"cpu_usage_percent", "memory_usage_percent"}:
            raise ValueError("Resource ordering is restricted to approved fields")
        return self.rows(
            "WITH "
            + HEALTH_CTES
            + f"SELECT * FROM health WHERE is_current ORDER BY {resource} DESC, "
            "server_id LIMIT :limit",
            query,
        )

    def breaches(self, query):
        return self.rows(BREACH_SQL, query)

    def pressure(self, query):
        return self.rows(PRESSURE_SQL, query)

    def underutilized(self, query):
        return self.rows(UNDERUTILIZED_SQL, query)

    def top_cost(self, query):
        if query.currency is None:
            raise ValueError("Cost ranking requires one explicit currency")
        return self.rows(TOP_COST_SQL, query)

    def fleet_costs(self, query):
        return self.rows(FLEET_COST_SQL, query)

    def period_cost(self, query):
        if query.currency is None:
            raise ValueError("Cost comparison requires one explicit currency")
        return self.rows(PERIOD_COST_SQL, query)[0]
