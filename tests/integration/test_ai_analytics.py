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
    def __init__(self, tool, arguments="{}"):
        self.tool, self.calls = tool, 0
        self.arguments, self.requests = arguments, []

    async def complete(self, messages, tools, choice):
        self.calls += 1
        self.requests.append({"messages": list(messages), "tools": tools, "choice": choice})
        if self.calls == 1:
            return Completion.model_validate(
                {
                    "tool_calls": [
                        {
                            "id": "call-db",
                            "type": "function",
                            "function": {"name": self.tool, "arguments": self.arguments},
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
@pytest.mark.parametrize("rounds", [1, 3])
def test_ai_tools_use_actual_postgres(analytics_data, settings, tool, rounds):
    settings.ai_max_analytics_tool_rounds = rounds
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
    provider = FakeProvider(tool)
    response = asyncio.run(
        AnalyticsHarness(provider, AnalyticsService(data.db, settings), settings).query(
            context, "db-request"
        )
    )
    result = response.evidence.tool_results[0].result
    assert response.evidence.tools_used == [tool]
    assert provider.calls == 2
    if rounds == 1:
        assert provider.requests[1]["tools"] == []
        assert provider.requests[1]["choice"] == "none"
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


@pytest.mark.parametrize("environment", ["prod", "dev", "staging"])
def test_server_status_counts_entire_filtered_cohort(analytics_data, settings, environment):
    import json

    from sqlalchemy import update

    from infrasight.ai.tools import ToolRegistry
    from infrasight.db.models import Server

    data = analytics_data
    for index in range(15):
        server = data.server(f"{environment}-{index}")
        data.db.execute(update(Server).where(Server.id == server).values(environment=environment))
        if index < 11:
            data.metric(server, health="CRITICAL" if index < 2 else "HEALTHY")
        elif index == 11:
            data.metric(server, health="WARNING")
        elif index == 12:
            data.metric(server, observed=data.start - timedelta(minutes=5))
        # Last two deliberately have NO_DATA.
    other = data.server("other-environment")
    other_environment = "dev" if environment == "prod" else "prod"
    data.db.execute(update(Server).where(Server.id == other).values(environment=other_environment))
    data.metric(other, health="CRITICAL")
    context = QueryRequest(
        question=f"server status on {environment} environment",
        source_id="fixture",
        reference_time=data.start + timedelta(seconds=30),
    )
    result = ToolRegistry(AnalyticsService(data.db, settings), settings, context).execute(
        "get_server_health", json.dumps({"environment": environment, "limit": 3})
    )
    summary = result["fleet_summary"]
    assert summary["inventory_servers"] == 15
    assert summary["healthy_servers"] == 9
    assert summary["critical_servers"] == 2
    assert summary["warning_servers"] == 1
    assert summary["stale_servers"] == 1
    assert summary["no_data_servers"] == 2
    assert summary["reporting_servers"] == 12
    assert len(result["rows"]) == 3
    assert all(row["environment"] == environment for row in result["rows"])
    assert result["result_may_be_truncated"] is True

    settings.ai_max_analytics_tool_rounds = 1
    provider = FakeProvider(
        "get_server_health", json.dumps({"environment": environment, "limit": 3})
    )
    response = asyncio.run(
        AnalyticsHarness(provider, AnalyticsService(data.db, settings), settings).query(
            context, "interview-totals"
        )
    )
    attached = response.evidence.tool_results[0].result
    assert attached == result
    assert "Detail rows may be truncated" in response.answer
    assert provider.calls == 2 and provider.requests[-1]["tools"] == []
    wire = json.loads(
        next(
            message["content"]
            for message in provider.requests[-1]["messages"]
            if message["role"] == "tool"
        )
    )
    assert wire["fleet_summary"] == summary
    assert wire["result_may_be_truncated"] is True
    assert wire["reference_time"] == result["reference_time"]
