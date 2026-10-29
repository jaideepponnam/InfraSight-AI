from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration


def test_analytics_downgrade_reupgrade_preserves_base_data(analytics_db, analytics_data):
    data = analytics_data
    data.metric(data.server())
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = analytics_db
    assert analytics_db.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
    command.downgrade(config, "0001")
    assert "analytics" not in inspect(analytics_db).get_schema_names()
    assert analytics_db.scalar(text("SELECT COUNT(*) FROM infrastructure_metrics")) == 1
    command.upgrade(config, "0002")
    assert analytics_db.scalar(text("SELECT COUNT(*) FROM analytics.high_resource_usage")) == 1
    assert set(inspect(analytics_db).get_view_names(schema="analytics")) == {
        "latest_server_metrics",
        "server_health_summary",
        "high_resource_usage",
        "daily_infrastructure_summary",
        "daily_cloud_cost_summary",
        "region_usage_summary",
        "_daily_metric_intervals",
    }
