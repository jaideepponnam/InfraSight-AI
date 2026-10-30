import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from infrasight.ai.harness import AnalyticsHarness, provider_result
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
        "fleet_totals",
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


@pytest.mark.parametrize(
    "status,body,category,code,api_status",
    [
        (
            400,
            {"error": {"code": "tool_use_failed", "type": "invalid_request_error"}},
            "tool_generation_rejected",
            "AI_PROVIDER_ERROR",
            502,
        ),
        (
            400,
            {"error": {"type": "invalid_request_error"}},
            "invalid_request",
            "AI_PROVIDER_ERROR",
            502,
        ),
        (
            400,
            {"error": {"code": "context_length_exceeded"}},
            "context_limit",
            "AI_PROVIDER_ERROR",
            502,
        ),
        (
            404,
            {"error": {"code": "model_not_found"}},
            "model_unavailable",
            "AI_PROVIDER_ERROR",
            502,
        ),
        (429, {"error": {"code": "rate_limit_exceeded"}}, "rate_limit", "AI_RATE_LIMITED", 429),
        (401, {"error": {"code": "private-category"}}, "unknown", "AI_PROVIDER_CONFIGURATION", 503),
        (503, {"error": {"code": "private-category"}}, "unknown", "AI_PROVIDER_UNAVAILABLE", 503),
        (400, {"error": {"code": ["invalid_request_error"]}}, "unknown", "AI_PROVIDER_ERROR", 502),
        (400, ["private-response"], "unknown", "AI_PROVIDER_ERROR", 502),
        (400, "not-json-private-response", "malformed_error_body", "AI_PROVIDER_ERROR", 502),
        (400, "x" * 100001, "oversized_error_body", "AI_PROVIDER_ERROR", 502),
    ],
    ids=[
        "tool-rejection",
        "invalid-request",
        "context-limit",
        "missing-model",
        "rate-limit",
        "auth-error",
        "server-error",
        "invalid-code-shape",
        "invalid-body-shape",
        "non-json",
        "oversized",
    ],
)
def test_provider_rejection_diagnostics(settings, status, body, category, code, api_status):
    import structlog
    from structlog.testing import capture_logs

    settings.groq_api_key = SecretStr("private-diagnostic-key")
    if isinstance(body, dict):
        body["error"].update(
            message="private-provider-message",
            failed_generation="private-tool-arguments-and-reasoning",
        )

    def respond(request):
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    tokens = structlog.contextvars.bind_contextvars(request_id="diagnostic-request")
    try:
        with capture_logs() as events, pytest.raises(AIError) as raised:
            asyncio.run(
                GroqProvider(settings, httpx.MockTransport(respond)).complete(
                    [{"role": "user", "content": "private-question"}], [], "none"
                )
            )
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
    assert raised.value.code == code
    assert raised.value.status == api_status
    assert events == [
        {
            "event": "ai_provider_rejected",
            "log_level": "warning",
            "upstream_status": status,
            "provider_error_category": category,
            "request_id": "diagnostic-request",
        }
    ]
    assert "private" not in json.dumps(events)
    assert "private" not in str(raised.value)


@pytest.mark.parametrize("rows", [[], [{"value": "1.20"}], [{"a": 1}, {"b": 2}]])
def test_provider_result_keeps_small_or_nonuniform_rows(rows):
    result = {"rows": rows, "currency": "USD"}
    assert provider_result(result) is result


@pytest.mark.parametrize("rounds", [1, 2, 3])
def test_configured_analytics_rounds_reserve_schema_free_summary(
    settings, context, service, rounds
):
    settings.ai_max_analytics_tool_rounds = rounds
    provider = FakeProvider(
        [call(identity=f"call-{index}") for index in range(rounds)]
        + [Completion(content="Only the recorded fleet evidence is available.")]
    )
    response = asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "budget"))
    assert len(provider.requests) == rounds + 1
    assert service.overview.call_count == rounds
    assert len(response.evidence.tool_results) == rounds
    assert provider.requests[0]["choice"] == "required"
    assert all(request["tools"] for request in provider.requests[:-1])
    assert {tool["function"]["name"] for tool in provider.requests[0]["tools"]} == set(TOOLS)
    final = provider.requests[-1]
    assert final["tools"] == [] and final["choice"] == "none"
    assert final["messages"][-1]["role"] == "system"
    assert "available evidence cannot establish" in final["messages"][-1]["content"]


def test_interview_budget_rejects_further_tools_without_executing_them(settings, context, service):
    settings.ai_max_analytics_tool_rounds = 1
    provider = FakeProvider([call(), call("get_critical_servers", identity="call-2")])
    with pytest.raises(AIError, match="AI_TOOL_ROUND_LIMIT"):
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "budget"))
    assert len(provider.requests) == 2
    service.overview.assert_called_once()
    service.critical_servers.assert_not_called()


def test_interview_provider_payload_omits_final_tool_schemas(settings, context, service):
    settings.ai_max_analytics_tool_rounds = 1
    settings.groq_api_key = SecretStr("synthetic-test-key")
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        assert payload["model"] == settings.groq_model
        assert payload["max_tokens"] == 800
        if len(captured) == 1:
            assert payload["tool_choice"] == "required"
            message = call().model_dump(exclude_none=True)
        else:
            assert len(captured) == 2
            assert "tools" not in payload and "tool_choice" not in payload
            assert "parallel_tool_calls" not in payload
            message = {"content": "The recorded fleet is stale; no live probe was run."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    response = asyncio.run(
        AnalyticsHarness(
            GroqProvider(settings, httpx.MockTransport(respond)), service, settings
        ).query(context, "interview")
    )
    assert len(captured) == 2
    assert response.evidence.tool_results[0].result["rows"][0]["stale_servers"] == 75


def test_compact_schemas_omit_only_frozen_context(settings, context, service):
    context.min_samples = 20
    registry = ToolRegistry(service, settings, context)
    schemas = registry.schemas()
    assert {tool["function"]["name"] for tool in schemas} == set(TOOLS)
    for tool in schemas:
        schema = tool["function"]["parameters"]
        assert not {
            "as_of",
            "source_id",
            "currency",
            "freshness_seconds",
            "start",
            "end",
            "min_samples",
        } & set(schema["properties"])
        assert set(schema.get("required", [])) <= set(schema["properties"])
    comparison = next(tool for tool in schemas if tool["function"]["name"] == "compare_cost")
    assert not {"mode", "current_start", "current_end", "previous_start", "previous_end"} & set(
        comparison["function"]["parameters"]["properties"]
    )
    registry.execute("get_cpu_pressure", "{}")
    query = service.sustained_cpu_pressure.call_args.args[0]
    assert query.start == context.start and query.end == context.end
    assert query.as_of == context.reference_time and query.source_id == context.source_id
    assert query.min_samples == 20


def test_schemas_keep_unfixed_window_and_sample_arguments(settings, service):
    context = QueryRequest(question="Investigate CPU pressure", reference_time=END)
    schemas = ToolRegistry(service, settings, context).schemas()
    pressure = next(tool for tool in schemas if tool["function"]["name"] == "get_cpu_pressure")
    assert {"start", "end", "min_samples"} <= set(pressure["function"]["parameters"]["properties"])
    comparison = next(tool for tool in schemas if tool["function"]["name"] == "compare_cost")
    assert "mode" in comparison["function"]["parameters"]["properties"]


def test_interview_empty_evidence_is_explicitly_insufficient(settings, context, service):
    settings.ai_max_analytics_tool_rounds = 1
    service.critical_servers.return_value = AnalyticsReport(
        reference_time=END,
        parameters={"freshness_seconds": 120},
        rows=[],
        warnings=["No additional measurements were retrieved."],
    )
    provider = FakeProvider(
        [call("get_critical_servers"), Completion(content="Invented: every server is healthy.")]
    )
    response = asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "empty"))
    assert "insufficient" in response.answer
    assert "Invented" not in response.answer
    assert response.evidence.tool_results[0].result["rows"] == []
    assert response.evidence.tool_results[0].warnings == [
        "No additional measurements were retrieved."
    ]
    assert len(provider.requests) == 2


def test_interview_preserves_full_totals_staleness_warnings_and_truncation(
    settings, context, service
):
    settings.ai_max_analytics_tool_rounds = 1
    settings.ai_max_result_rows = 2
    rows = [
        {
            "server_id": "stale-server",
            "effective_health": "STALE",
            "observed_at": None,
            "completion_age_seconds": 500,
            "estimated_cost": None,
        },
        {
            "server_id": "missing-server",
            "effective_health": "NO_DATA",
            "observed_at": None,
            "completion_age_seconds": None,
            "estimated_cost": None,
        },
    ]
    totals = {
        "inventory_servers": 75,
        "healthy_servers": 70,
        "critical_servers": 1,
        "warning_servers": 2,
        "stale_servers": 1,
        "no_data_servers": 1,
    }
    service.health.return_value = AnalyticsReport(
        reference_time=END,
        window_start=context.start,
        window_end=context.end,
        parameters={"freshness_seconds": 120},
        rows=rows,
        currency="USD",
        warnings=["No current measurements for these detail rows."],
    )
    service.fleet_totals.return_value = AnalyticsReport(
        reference_time=END, parameters={"freshness_seconds": 120}, rows=[totals]
    )
    provider = FakeProvider(
        [call("get_server_health"), Completion(content="Recorded fleet counts.")]
    )
    response = asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "totals"))
    result = response.evidence.tool_results[0].result
    assert result["rows"] == rows and result["fleet_summary"] == totals
    assert result["result_may_be_truncated"] is True and result["row_limit"] == 2
    assert "Detail rows may be truncated" in response.answer
    wire = json.loads(
        next(
            message["content"]
            for message in provider.requests[1]["messages"]
            if message["role"] == "tool"
        )
    )
    for field in (
        "fleet_summary",
        "reference_time",
        "window_start",
        "window_end",
        "parameters",
        "warnings",
        "currency",
        "row_limit",
        "result_may_be_truncated",
    ):
        assert wire[field] == result[field]
    restored = [dict(zip(wire["row_columns"], row, strict=True)) for row in wire["rows"]]
    assert restored == rows
    assert response.evidence.freshness["per_tool"][0]["servers"][0]["effective_health"] == "STALE"


@pytest.mark.parametrize("failed_round", [1, 2])
def test_interview_rate_limit_preserves_failure_without_retries(
    settings, context, service, failed_round
):
    settings.ai_max_analytics_tool_rounds = 1
    provider = FakeProvider([call()] * (failed_round - 1) + [AIError("AI_RATE_LIMITED", 429)])
    with pytest.raises(AIError) as raised:
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "limited"))
    assert raised.value.code == "AI_RATE_LIMITED" and raised.value.status == 429
    assert len(provider.requests) == failed_round
    assert service.overview.call_count == failed_round - 1


@pytest.mark.parametrize(
    "usage,expected",
    [
        (
            {"prompt_tokens": 1300, "completion_tokens": 40, "total_tokens": 1340},
            {"prompt_tokens": 1300, "completion_tokens": 40, "total_tokens": 1340},
        ),
        (
            {"prompt_tokens": 0, "completion_tokens": True, "total_tokens": "900"},
            {"prompt_tokens": 0},
        ),
        ({"prompt_tokens": -1, "completion_tokens": 1.5, "total_tokens": 1000000001}, {}),
        (
            {"prompt_tokens": {"secret": "private-usage-text"}, "total_tokens": 12},
            {"total_tokens": 12},
        ),
        (None, {}),
        ([], {}),
        ("private-usage-text", {}),
    ],
)
def test_provider_usage_logs_only_bounded_integer_counters(settings, usage, expected):
    from structlog.testing import capture_logs

    settings.groq_api_key = SecretStr("private-provider-key")
    if isinstance(usage, dict):
        usage = {**usage, "secret": "private-usage-text"}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "private-answer"}}], "usage": usage}
        )
    )
    with capture_logs() as events:
        completion = asyncio.run(
            GroqProvider(settings, transport).complete(
                [{"role": "user", "content": "private-prompt"}], [], "none"
            )
        )
    assert completion.content == "private-answer"
    if expected:
        assert events == [
            {"event": "ai_provider_usage", "log_level": "info", "request_id": None, **expected}
        ]
    else:
        assert events == []
    assert "private" not in json.dumps(events)


def test_prod_server_list_compact_round_trip(settings, context, service):
    context.question = "get me status on servers from prod"
    rows = [
        {
            "server_id": f"server-{i}",
            "server_name": f"production-{i}",
            "source_id": "simulated-cloud",
            "environment": "prod",
            "region_code": "us-south",
            "cpu_usage_percent": "42.125",
            "memory_usage_percent": "51.625",
            "storage_usage_percent": None,
            "estimated_cost": "0.00012345",
            "currency": "USD",
            "observed_at": END.isoformat(),
            "effective_health": "STALE" if i == 0 else "HEALTHY",
            "completion_age_seconds": 150 if i == 0 else 0,
        }
        for i in range(10)
    ]
    service.health.return_value = AnalyticsReport(
        reference_time=END,
        currency="USD",
        parameters={"freshness_seconds": 120, "environment": "prod"},
        rows=rows,
    )
    provider = FakeProvider(
        [
            call("get_server_health", '{"environment":"prod"}'),
            Completion(content="A bounded production-server list; one recorded server is stale."),
        ]
    )
    response = asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "prod"))
    query = service.health.call_args.args[0]
    assert query.environment == "prod" and query.source_id == "simulated-cloud"
    original = response.evidence.tool_results[0].result
    wire = json.loads(provider.requests[1]["messages"][-1]["content"])
    restored = [dict(zip(wire["row_columns"], row, strict=True)) for row in wire["rows"]]
    assert restored == original["rows"]
    assert original["rows"] == rows
    assert original["result_may_be_truncated"] is True
    assert wire["result_may_be_truncated"] is True
    assert wire["parameters"] == original["parameters"]
    assert "row_columns" not in original
    assert len(json.dumps(wire)) < len(json.dumps(original)) * 0.7
    assert response.evidence.freshness["per_tool"][0]["servers"][0]["effective_health"] == "STALE"


def test_rate_limit_after_tool_does_not_fabricate_or_retry(settings, context, service):
    provider = FakeProvider(
        [call("get_server_health", '{"environment":"prod"}'), AIError("AI_RATE_LIMITED", 429)]
    )
    with pytest.raises(AIError, match="AI_RATE_LIMITED"):
        asyncio.run(AnalyticsHarness(provider, service, settings).query(context, "limited"))
    assert len(provider.requests) == 2
    service.health.assert_called_once()


def test_rate_limit_logs_only_allowlisted_numeric_quota(settings):
    from structlog.testing import capture_logs

    settings.groq_api_key = SecretStr("private-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            429,
            headers={
                "retry-after": "12",
                "x-ratelimit-limit-tokens": "8000",
                "x-ratelimit-remaining-tokens": "0",
                "x-ratelimit-remaining-requests": "private-untrusted-header",
                "authorization": "private-header",
            },
            json={"error": {"code": "rate_limit_exceeded", "message": "private-message"}},
        )
    )
    with capture_logs() as events, pytest.raises(AIError, match="AI_RATE_LIMITED"):
        asyncio.run(GroqProvider(settings, transport).complete([], [], "none"))
    quota = next(event for event in events if event["event"] == "ai_provider_quota")
    assert quota["retry_after_seconds"] == 12
    assert quota["token_limit"] == 8000 and quota["tokens_remaining"] == 0
    assert "requests_remaining" not in quota
    assert "private" not in json.dumps(events)
