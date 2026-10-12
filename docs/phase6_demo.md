# Phase 6: AI analytics harness

Configure GROQ_API_KEY privately through environment/settings. Never paste it into source,
logs, documentation, examples, or screenshots. GROQ_MODEL defaults to
openai/gpt-oss-120b. Other settings: GROQ_TIMEOUT_SECONDS=20,
AI_REQUEST_TIMEOUT_SECONDS=60, AI_MAX_RESULT_ROWS=20. httpx is a runtime dependency.
The provider protocol can later support watsonx without changing analytics tools.

Start the existing FastAPI factory on loopback as documented in Phase 5. POST
/api/v1/ai/query requires the existing X-API-Key; no admin key is needed.

~~~json
{
  "question": "Which servers are expensive but underutilized?",
  "source_id": "simulated-cloud",
  "reference_time": "2026-10-11T19:33:00Z",
  "start": "2026-10-11T19:30:00Z",
  "end": "2026-10-11T19:33:00Z",
  "currency": "USD",
  "min_samples": 4
}
~~~

The short three-minute historical fixture explicitly lowers the sample requirement to 4.
Normal analytics defaults remain 20 samples, 80% coverage, and the existing health policy.
Without context, reference_time is current UTC; ordinary period analytics default to today,
while optimization and sustained-pressure assessments use trailing 24 hours.

Flow: question/context -> Groq local function selection -> strict argument validation ->
existing AnalyticsService -> PostgreSQL -> bounded structured tool result -> Groq explanation.
Only ten fixed tools are registered: get_overview, get_server_health, get_high_cpu_servers,
get_top_resource_usage, get_cost_summary, compare_cost, get_region_usage,
get_underutilized_servers, get_cpu_pressure, get_critical_servers. There are no execution,
SQL, filesystem, browser, built-in Groq, MCP, or dynamically loaded tools.

The answer includes tools_used, frozen reference time, requested window, freshness,
coverage, currency, request ID, and each tool's bounded backend result and actual window.
The requested top-level window may be null when defaults were used; per-tool windows
are authoritative. List limits are disclosed and do not represent fleet totals. Money
remains decimal strings. STALE/NO_DATA never silently become HEALTHY; unknown cost is
not zero. Incomplete/unequal comparisons must not become confident trend claims.
With an explicit selected window, compare_cost defaults to the same UTC period one day
earlier. Without one, it uses Phase 5 comparison modes. There is no guaranteed savings claim.

Limits: three tool-call rounds, at most three calls per round, at most one final explanation
request; 2,000-character questions; seven-day windows; bounded rows and 32,000-character
tool results. Unknown tools, invalid arguments, or failed analytics abort the request.
Provider 429 returns sanitized HTTP 429; timeouts 504; unavailable/configuration failures
503; malformed tool/provider responses 502. No automatic quota-consuming retries.
Whole-request deadlines complement provider timeouts and existing database statement
limits. Cancelling a request cannot forcibly terminate a database thread; statements
remain bounded by PostgreSQL timeouts. Logs contain tool names/counts/duration, never
questions, prompts, arguments, results or keys. Each tool reads a service snapshot;
multiple tool calls are not a single global snapshot.

## Small real demo

With port 8000 free and the provider key configured:

~~~powershell
.\.venv\Scripts\python.exe scripts/phase6_demo.py
# All seven questions, spaced to reduce free-tier rate limits:
.\.venv\Scripts\python.exe scripts/phase6_demo.py --questions 7 --delay-seconds 60
~~~

To resume after a rate limit, wait for quota recovery and use e.g.
`--start-question 3 --questions 5 --delay-seconds 60`. The harness itself never retries.

The script starts its own local API, checks readiness/OpenAPI, calls actual HTTP AI
endpoints, and stops only its own process. It never reads or displays .env contents or
the provider key. It writes answers/evidence to ignored .uv-cache/phase6-demo.json and
prints only question numbers, tool names, status and reference time. It stops on provider
errors rather than retrying. Comparison uses the existing clean Phase 4 comparison source.

Questions: How is our infrastructure doing? Which servers had CPU above 80%? Which servers
are costing us the most? Are there any underutilized servers? Which region has the most
critical servers? Did infrastructure cost increase compared with the previous equivalent
period? Which servers are under sustained CPU pressure?

Automated tests use fake providers and mocked HTTP transport, including PostgreSQL-backed
service integration; they consume no Groq quota. The LLM explanation remains generated
text: the attached backend evidence is the auditable source of truth.

Protocol reference: [Groq local tool calling](https://console.groq.com/docs/tool-use/overview).

Model deployment note: openai/gpt-oss-120b supports the existing local function-calling
contract; parallel tool calls remain disabled. Extra provider reasoning fields are ignored
by the existing response parser and are not returned as answers or evidence. See
[Groq tool support](https://console.groq.com/docs/tool-use/overview). Explicit GROQ_MODEL
environment overrides must also use the new model; changing a default does not replace
a configured override. GROQ_MODEL and GROQ_API_KEY remain backend-only.
