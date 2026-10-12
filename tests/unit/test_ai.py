import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from infrasight.ai.harness import AnalyticsHarness
from infrasight.ai.provider import AIError, Completion, GroqProvider
from infrasight.ai.schemas import QueryRequest
from infrasight.ai.tools import TOOLS, ToolRegistry
from infrasight.analytics.schemas import AnalyticsReport
from infrasight.api.ai import harness
from infrasight.main import create_app

END = datetime(2026, 10, 11, 19, 33, tzinfo=UTC)


def call(name="get_overview", arguments="{}", identity="call_1"):
    return Completion.model_validate(
        {
            "tool_calls": [
                {
                    "id": identity,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ]
        }
    )


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, choice):
        self.requests.append({"messages": list(messages), "tools": tools, "choice": choice})
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def context():
    return QueryRequest(
        question="How is the fleet?",
        source_id="simulated-cloud",
        reference_time=END,
        start=END - timedelta(minutes=3),
        end=END,
    )


@pytest.fixture
def service():
    result = AnalyticsReport(
        reference_time=END,
        window_start=END - timedelta(minutes=3),
        window_end=END,
        currency="USD",
        parameters={"freshness_seconds": 120},
        rows=[
            {
                "stale_servers": 75,
                "observed_cost": Decimal("1.03775797"),
                "coverage": {"cost_coverage_fraction": Decimal("0.99111111")},
            }
        ],
    )
    service = Mock()
    for name in (
        "overview",
        "health",
        "high_cpu_breaches",
        "top_cpu",
        "top_memory",
        "top_storage",
        "cost_summary",
        "compare_cost",
        "api_comparison",
        "regions",
        "underutilized",
        "sustained_cpu_pressure",
        "critical_servers",
    ):
        getattr(service, name).return_value = result
    return service


@pytest.mark.parametrize(
    "name,method",
    [
        ("get_overview", "overview"),
        ("get_server_health", "health"),
        ("get_high_cpu_servers", "high_cpu_breaches"),
        ("get_top_resource_usage", "top_cpu"),
        ("get_cost_summary", "cost_summary"),
        ("compare_cost", "compare_cost"),
        ("get_region_usage", "regions"),
        ("get_underutilized_servers", "underutilized"),
        ("get_cpu_pressure", "sustained_cpu_pressure"),
        ("get_critical_servers", "critical_servers"),
    ],
)
def test_dispatch(settings, context, service, name, method):
    result = ToolRegistry(service, settings, context).execute(name, "{}")
    getattr(service, method).assert_called_once()
    assert result["rows"][0]["observed_cost"] == "1.03775797"
    query = getattr(service, method).call_args.args[0]
    assert query.as_of == END and query.source_id == "simulated-cloud"


@pytest.mark.parametrize(
    "name,args",
    [
        ("execute_sql", "{}"),
        ("python", "{}"),
        ("shell", "{}"),
        ("get_overview", '{"sql":"SELECT * FROM raw_telemetry"}'),
        ("get_overview", '{"limit":100}'),
        ("get_overview", '{"limit":"2"}'),
        ("get_high_cpu_servers", '{"threshold":101}'),
        ("get_overview", '{"source_id":"other-account"}'),
        ("get_overview", '{"start":"2026-10-10T00:00:00Z"}'),
        ("get_overview", "not-json"),
    ],
)
def test_reject_unsafe_or_invalid_arguments(settings, context, service, name, args):
    with pytest.raises(AIError):
        ToolRegistry(service, settings, context).execute(name, args)
    assert service.mock_calls == []


def test_oversized_window(settings, service):
    context = QueryRequest(question="cost", reference_time=END)
    with pytest.raises(AIError, match="AI_INVALID_TOOL_ARGUMENTS"):
        ToolRegistry(service, settings, context).execute(
            "get_cost_summary",
            json.dumps({"start": (END - timedelta(days=8)).isoformat(), "end": END.isoformat()}),
        )


def test_harness_evidence(settings, context, service):
    provider = FakeProvider([call(), Completion(content="The recorded fleet is stale.")])
    response = asyncio.run(
        AnalyticsHarness(provider, service, settings).query(context, "request-1")
    )
    assert response.evidence.tools_used == ["get_overview"]
    assert response.evidence.reference_time == END
    assert response.evidence.window["end"] == END
    assert response.evidence.coverage[0]["cost_coverage_fraction"] == "0.99111111"
    assert response.evidence.tool_results[0].result["rows"][0]["stale_servers"] == 75
    assert response.request_id == "request-1"
    assert provider.requests[0]["choice"] == "required"
    assert json.loads(provider.requests[1]["messages"][-1]["content"])["rows"]


def test_maximum_rounds(settings, context, service):
    provider = FakeProvider([call(identity="call_" + str(i)) for i in range(4)])
    with pytest.raises(AIError, match="AI_TOOL_ROUND_LIMIT"):
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "r"))
    assert service.overview.call_count == 3
    assert provider.requests[-1]["tools"] == []


def test_three_rounds_can_summarize(settings, context, service):
    provider = FakeProvider(
        [call(identity="call_" + str(i)) for i in range(3)] + [Completion(content="Verified.")]
    )
    result = asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "r"))
    assert len(result.evidence.tool_results) == 3


def test_no_evidence_no_answer(settings, context, service):
    with pytest.raises(AIError, match="AI_NO_EVIDENCE"):
        asyncio.run(
            AnalyticsHarness(
                FakeProvider([Completion(content="All healthy!")]), service, settings
            ).query(context, "r")
        )


def test_failed_analytics_no_explanation(settings, context, service):
    service.overview.side_effect = RuntimeError("private-database-detail")
    provider = FakeProvider([call(), Completion(content="fabricated")])
    with pytest.raises(AIError, match="AI_ANALYTICS_UNAVAILABLE"):
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "r"))
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "status,code",
    [
        (429, "AI_RATE_LIMITED"),
        (503, "AI_PROVIDER_UNAVAILABLE"),
        (401, "AI_PROVIDER_CONFIGURATION"),
        (400, "AI_PROVIDER_ERROR"),
    ],
)
def test_provider_http_failures(settings, status, code):
    settings.groq_api_key = SecretStr("synthetic-test-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": "private-provider-detail"})
    )
    with pytest.raises(AIError, match=code) as raised:
        asyncio.run(GroqProvider(settings, transport).complete([], [], "none"))
    assert "private-provider-detail" not in str(raised.value)


@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ReadTimeout("private"), "AI_PROVIDER_TIMEOUT"),
        (httpx.ConnectError("private"), "AI_PROVIDER_UNAVAILABLE"),
    ],
)
def test_provider_transport_failures(settings, error, code):
    settings.groq_api_key = SecretStr("synthetic-test-key")

    def fail(request):
        raise error

    with pytest.raises(AIError, match=code):
        asyncio.run(GroqProvider(settings, httpx.MockTransport(fail)).complete([], [], "none"))


def test_provider_contract_and_no_builtin_tools(settings, context, service):
    settings.groq_api_key = SecretStr("synthetic-test-key")
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Verified."}}]})

    provider = GroqProvider(settings, httpx.MockTransport(respond))
    schemas = ToolRegistry(service, settings, context).schemas()
    asyncio.run(provider.complete([], schemas, "required"))
    assert {t["function"]["name"] for t in captured[0]["tools"]} == set(TOOLS)
    assert all(t["type"] == "function" for t in captured[0]["tools"])
    assert captured[0]["parallel_tool_calls"] is False
    assert "synthetic-test-key" not in json.dumps(captured)


def test_request_deadline(settings, context, service):
    class SlowProvider:
        async def complete(self, *args):
            await asyncio.sleep(1)

    settings.ai_request_timeout_seconds = 0.01
    with pytest.raises(AIError, match="AI_REQUEST_TIMEOUT"):
        asyncio.run(AnalyticsHarness(SlowProvider(), service, settings).query(context, "r"))


def test_ai_api_auth_validation_and_evidence(settings, context, service):
    settings.api_read_key = SecretStr("synthetic-read-key")
    app = create_app(settings)
    app.dependency_overrides[harness] = lambda: AnalyticsHarness(
        FakeProvider([call(), Completion(content="The historical fleet is stale.")]),
        service,
        settings,
    )
    headers = {"X-API-Key": "synthetic-read-key"}
    with TestClient(app) as client:
        assert client.post("/api/v1/ai/query", json={"question": "health"}).status_code == 401
        for body in [
            {"question": " "},
            {"question": "x" * 2001},
            {"question": "health", "sql": "SELECT 1"},
            {"question": "health", "reference_time": "2026-10-11T19:33:00"},
        ]:
            assert client.post("/api/v1/ai/query", headers=headers, json=body).status_code == 422
        response = client.post(
            "/api/v1/ai/query", headers=headers, json=context.model_dump(mode="json")
        )
    assert response.status_code == 200, response.text
    assert response.json()["evidence"]["tools_used"] == ["get_overview"]
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "code,status",
    [
        ("AI_RATE_LIMITED", 429),
        ("AI_PROVIDER_TIMEOUT", 504),
        ("AI_PROVIDER_UNAVAILABLE", 503),
        ("AI_UNKNOWN_TOOL", 502),
    ],
)
def test_ai_api_sanitized_errors(settings, code, status, capsys):
    settings.api_read_key = SecretStr("synthetic-read-key")
    app = create_app(settings)

    class FailingHarness:
        async def query(self, *args):
            raise AIError(code, status)

    app.dependency_overrides[harness] = FailingHarness
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/query",
            headers={"X-API-Key": "synthetic-read-key"},
            json={"question": "private-user-question"},
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-user-question" not in response.text + capsys.readouterr().out


def test_unconfigured_provider(settings):
    settings.groq_api_key = None
    with pytest.raises(AIError, match="AI_NOT_CONFIGURED"):
        asyncio.run(GroqProvider(settings).complete([], [], "none"))


def test_default_respects_smaller_row_bound(settings, context, service):
    settings.ai_max_result_rows = 5
    ToolRegistry(service, settings, context).execute("get_overview", "{}")
    assert service.overview.call_args.args[0].limit == 5


def test_comparison_cannot_override_selected_window(settings, context, service):
    with pytest.raises(AIError, match="AI_INVALID_TOOL_ARGUMENTS"):
        ToolRegistry(service, settings, context).execute(
            "compare_cost", '{"mode":"equivalent_elapsed"}'
        )
    assert service.mock_calls == []


def test_duplicate_call_identity_rejected(settings, context, service):
    provider = FakeProvider([call(), call()])
    with pytest.raises(AIError, match="AI_PROVIDER_INVALID_RESPONSE"):
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "r"))
    assert service.overview.call_count == 1


def test_no_prompts_or_results_logged(settings, context, service, capsys):
    context.question = "private-prompt-for-logging-test"
    provider = FakeProvider([call(), Completion(content="private-answer-for-logging-test")])
    asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "r"))
    output = capsys.readouterr().out
    assert "private-prompt-for-logging-test" not in output
    assert "private-answer-for-logging-test" not in output
    assert "1.03775797" not in output


@pytest.mark.parametrize(
    "body", [{}, {"choices": []}, {"choices": [{"message": {"role": "system", "content": "bad"}}]}]
)
def test_invalid_provider_response(settings, body):
    settings.groq_api_key = SecretStr("synthetic-test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(AIError, match="AI_PROVIDER_INVALID_RESPONSE"):
        asyncio.run(GroqProvider(settings, transport).complete([], [], "none"))


def test_gpt_oss_120b_groq_tool_round_trip(settings, context, service):
    """One mocked round trip exercises the real provider, harness and tool registry."""
    from infrasight.config import Settings

    assert Settings.model_fields["groq_model"].default == "openai/gpt-oss-120b"
    settings.groq_model = "openai/gpt-oss-120b"
    settings.groq_api_key = SecretStr("synthetic-test-key")
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        assert payload["model"] == "openai/gpt-oss-120b"
        assert payload["parallel_tool_calls"] is False
        assert {tool["function"]["name"] for tool in payload["tools"]} == set(TOOLS)
        assert all(tool["type"] == "function" for tool in payload["tools"])
        assert "synthetic-test-key" not in json.dumps(payload)
        if len(captured) == 1:
            assert payload["tool_choice"] == "required"
            message = call().model_dump(exclude_none=True)
        else:
            assert payload["tool_choice"] == "auto"
            assert payload["messages"][-1]["role"] == "tool"
            assert json.loads(payload["messages"][-1]["content"])["rows"][0]["stale_servers"] == 75
            message = {"role": "assistant", "content": "The recorded fleet is stale."}
        # GPT-OSS may supply this extra field; it must not become user-facing content.
        message["reasoning"] = "synthetic-private-reasoning"
        return httpx.Response(200, json={"choices": [{"message": message}]})

    provider = GroqProvider(settings, httpx.MockTransport(respond))
    response = asyncio.run(
        AnalyticsHarness(provider, service, settings).query(context, "model-migration")
    )
    assert len(captured) == 2
    service.overview.assert_called_once()
    assert response.answer == "The recorded fleet is stale."
    assert response.evidence.tools_used == ["get_overview"]
    assert response.evidence.reference_time == END
    assert response.evidence.tool_results[0].result["rows"][0]["observed_cost"] == "1.03775797"
    assert "synthetic-private-reasoning" not in response.model_dump_json()
    assert "synthetic-private-reasoning" not in json.dumps(captured)
