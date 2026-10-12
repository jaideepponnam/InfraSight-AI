import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from infrasight.ai.harness import AnalyticsHarness
from infrasight.ai.provider import Completion
from infrasight.ai.schemas import QueryRequest
from infrasight.analytics.services import AnalyticsService

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, tool):
        self.tool, self.calls = tool, 0

    async def complete(self, messages, tools, choice):
        self.calls += 1
        if self.calls == 1:
            return Completion.model_validate(
                {
                    "tool_calls": [
                        {
                            "id": "call-db",
                            "type": "function",
                            "function": {"name": self.tool, "arguments": "{}"},
                        }
                    ]
                }
            )
        return Completion(content="The answer is supported by the attached database evidence.")


@pytest.mark.parametrize(
    "tool",
    [
        "get_overview",
        "get_cost_summary",
        "get_high_cpu_servers",
        "get_region_usage",
        "get_server_health",
        "get_critical_servers",
        "get_top_resource_usage",
    ],
)
def test_ai_tools_use_actual_postgres(analytics_data, settings, tool):
    data = analytics_data
    server = data.server("ai-server")
    data.metric(server, cpu="95", health="CRITICAL", cost="0.12345678")
    context = QueryRequest(
        question="Infrastructure analytics",
        source_id="fixture",
        reference_time=data.start + timedelta(seconds=30),
        start=data.start,
        end=data.start + timedelta(seconds=30),
    )
    response = asyncio.run(
        AnalyticsHarness(FakeProvider(tool), AnalyticsService(data.db, settings), settings).query(
            context, "db-request"
        )
    )
    result = response.evidence.tool_results[0].result
    assert response.evidence.tools_used == [tool]
    assert result["rows"]
    assert "never-expose" not in response.model_dump_json()
    if tool == "get_overview":
        assert result["rows"][0]["critical_servers"] == 1
        assert Decimal(result["rows"][0]["observed_cost"]) == Decimal("0.12345678")
    elif tool == "get_cost_summary":
        assert Decimal(result["rows"][0]["estimated_cost"]) == Decimal("0.12345678")
    elif tool == "get_high_cpu_servers":
        assert result["rows"][0]["breach_count"] == 1


def test_ai_stale_and_no_data_evidence(analytics_data, settings):
    data = analytics_data
    server = data.server("stale-ai")
    data.server("no-data-ai")
    data.metric(server)
    context = QueryRequest(
        question="Health", source_id="fixture", reference_time=data.start + timedelta(hours=1)
    )
    response = asyncio.run(
        AnalyticsHarness(
            FakeProvider("get_server_health"), AnalyticsService(data.db, settings), settings
        ).query(context, "db-request")
    )
    rows = response.evidence.tool_results[0].result["rows"]
    assert {r["effective_health"] for r in rows} == {"STALE", "NO_DATA"}
    assert len(response.evidence.freshness["per_tool"][0]["servers"]) == 2
