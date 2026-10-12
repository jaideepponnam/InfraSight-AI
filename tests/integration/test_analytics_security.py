from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from infrasight.analytics.schemas import Scope, Window
from infrasight.analytics.services import AnalyticsService

pytestmark = pytest.mark.integration
PUBLIC_VIEWS = (
    "latest_server_metrics",
    "server_health_summary",
    "high_resource_usage",
    "daily_infrastructure_summary",
    "daily_cloud_cost_summary",
    "region_usage_summary",
)


def test_view_only_role_can_use_services_but_not_internal_data(analytics_db, analytics_data):
    from datetime import timedelta

    data = analytics_data
    data.metric(data.server())
    role = "analytics_test_" + uuid4().hex
    # Identifier comes only from a generated UUID; business-query values remain bound.
    analytics_db.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    analytics_db.execute(text(f'GRANT USAGE ON SCHEMA analytics TO "{role}"'))
    for view in PUBLIC_VIEWS:
        analytics_db.execute(text(f'GRANT SELECT ON analytics.{view} TO "{role}"'))
    analytics_db.execute(text(f'SET LOCAL ROLE "{role}"'))
    try:
        for view in PUBLIC_VIEWS:
            analytics_db.execute(text(f"SELECT * FROM analytics.{view} LIMIT 1"))
        service = AnalyticsService(analytics_db)
        scope = Scope(source_id="fixture", as_of=data.start + timedelta(seconds=30))
        assert service.fleet_totals(scope).rows[0]["healthy_servers"] == 1
        assert (
            service.fleet_costs(
                Window(
                    **scope.model_dump(), start=data.start, end=data.start + timedelta(seconds=30)
                )
            ).rows[0]["estimated_cost"]
            == 1
        )
        for table in (
            "public.raw_telemetry",
            "public.infrastructure_metrics",
            "public.data_quality_rejections",
            "public.etl_runs",
            "analytics._daily_metric_intervals",
        ):
            with pytest.raises(DBAPIError) as error, analytics_db.begin_nested():
                analytics_db.execute(text(f"SELECT * FROM {table} LIMIT 1"))
            assert error.value.orig.sqlstate == "42501"
    finally:
        analytics_db.execute(text("RESET ROLE"))
