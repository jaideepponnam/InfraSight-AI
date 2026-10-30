# Scout incident intelligence: Milestone 3

Scout investigates **recorded sandbox application-dependency HTTP 503 exercises**.
These are not actual storage outages. No continuous monitoring, independent
infrastructure root-cause diagnosis, or infrastructure control is added.
Overview, ETL/Pipeline, Scout analytics, and the read-only SRE dashboard remain available.

## Architecture and contracts

The existing React Scout page calls `POST /api/v1/ai/query` using the existing
public/demo `X-API-Key`. The existing `AnalyticsHarness`, Groq provider and allowlisted
tool registry handle both domains. Existing requests default to analytics and retain
their request behavior and response values.

Incident requests add an explicit scope:

```json
{
  "question": "Explain the observations, lifecycle events and recovery verification.",
  "analysis_scope": "incidents",
  "incident_id": "an-actual-recorded-incident-uuid"
}
```

`incident_id` is optional for listing. A selected ID cannot be overridden or broadened
by a tool call. Incident scope rejects ETL source/window/reference-time, currency,
freshness overrides, unknown parameters and invalid UUIDs. Server UTC and the recorded
policy establish freshness; historical ETL timestamps cannot make old probes fresh.
Incident response evidence keeps the existing envelope, with null window boundaries,
null currency, empty analytics coverage, and per-tool incident assessments. Analytics
currency remains a string and its evidence format is unchanged.

Available incident tools:

| Tool | Persisted evidence |
| --- | --- |
| `list_sre_incidents` | Lifecycle, severity, service/run IDs, timestamps, bounded pagination and total |
| `get_sre_incident` | One incident's metadata |
| `get_sre_incident_events` | Ordered event IDs, sequences, transitions, timestamps and allowed evidence references |
| `get_sre_incident_evidence` | Incident, exercise context, HTTP observations, recovery attempts and deterministic assessments |

The shared `SREQueries` service supplies the existing incident GET routes and Scout.
Existing GET response contracts are preserved, including the original incident title
and diagnostic payloads. Scout receives a separate restricted projection.
Queries run in independent PostgreSQL `REPEATABLE READ`, `READ ONLY` transactions.
Each investigation snapshot reads incident, events, probes and recovery attempts
consistently. Different tool calls can observe different versions; the final summary
does not combine evidence from differing incident versions.

## Fact grounding and freshness

Groq selects approved reads through the existing harness. **The displayed incident
answer is composed by backend code from those results, rather than displaying
unverified model prose.** This bounds factual claims and prevents a generated root
cause, action or service-health claim from replacing recorded facts. Existing analytics
answers continue using their existing model explanations.

Answers cite actual incident, event, probe and recovery attempt IDs and recorded
timestamps. Missing incidents, missing probes/attempts, tools not retrieved, unknown
policies and inconsistent verification evidence produce explicit uncertainty.

Current observation assessments are `HEALTHY`, `DEGRADED`, `STALE` or `UNKNOWN` under
the existing 15-second v1 policy. A fresh HTTP observation is on demand, not sustained
monitoring. Expired ACTIVE exercises cannot establish fresh health; read requests never
reconcile or finish them. Future timestamps and unsupported policies remain unknown.

Historical recovery is independently `VERIFIED`, `FAILED`, `PENDING`, `INTERRUPTED`
or `NOT_CONFIRMED`. Verification requires matching resolved lifecycle, successful run
and attempt, the recorded verification flag/policy, and three distinct matching healthy
post-action probe references with valid timing and the matching final lifecycle event.
Automatic fault expiration is not credited as authorized recovery. Historical `VERIFIED`
can coexist with `STALE` current observations.

The answer is a saved assessment at the server reference time. Its UI explicitly warns
that evidence ages and a new submission reassesses stored observations; submitting
does not create a probe. Provider round trips can consume the short freshness window.

## Frontend workflow

- In Scout, select **Recorded SRE incidents**. Leave the incident ID blank to list
  records, or supply an actual UUID for investigation.
- Incident Details offers **Investigate with Scout**, linking to
  `#/scout/incidents/{UUID}`. It populates the ID and investigation question only.
  Opening the link, selecting a suggestion, refreshing the page or changing scope
  never submits an AI query. Press **Analyze** explicitly.
- Incident investigation works independently of ETL availability. Its header shows
  stored observations instead of the analytics LIVE/ETL reference.
- Selecting Infrastructure analytics restores the existing analytics context path.

Useful questions include:

- "Which HTTP observations support this incident?" — recorded probe IDs, measured
  statuses/outcomes, durations and observation timestamps, if retrieved.
- "Explain the lifecycle events." — actual ordered transitions and event references.
- "Was recovery verified, and does that establish current health?" — separate historical
  verification and current freshness assessments, never inferring health from RESOLVED.
- "What remains unknown?" — explicit limits of the sandbox and missing evidence.

The incident answer is a structured factual summary of retrieved evidence. It does not
promise bespoke causal diagnosis or general conversational answers to unrelated prompts.

## Capability and payload boundaries

`SRE_ENABLED=false` disables incident schemas and execution and rejects incident queries
before any provider call. Analytics continues working. Incident and analytics toolsets
are isolated; the model cannot switch domain or expand a selected incident's scope.

Scout has no mutation service, admin headers, arbitrary SQL, URLs, commands, probe
execution, acknowledgement, recovery, exercise creation or reconciliation capability.
PostgreSQL enforces read-only transactions as additional protection. The shared runtime
database role still supports existing authorized admin operations outside Scout.

Provider evidence uses explicit field allowlists. Free-form incident titles, service
descriptions, exception/error strings and arbitrary evidence JSON are excluded. Known
enum values, typed IDs, timestamps, measurements and validated evidence references are
projected; unknown strings become UNKNOWN. Capability hashes, idempotency keys, database
URLs and API/provider credentials are never serialized into incident tool results.
Questions and persisted values are untrusted data; they cannot change capabilities.

Lists respect existing AI result limits and disclose partial results. Snapshot limits
are 64 events, 24 probes and three recovery attempts; excess evidence fails closed
instead of silently truncating verification proof. The harness retains its per-result
32,000-character limit and bounded tool rounds. No prompts or evidence bodies are logged.

This retains the existing public/demo read-key authorization model, not per-user or
tenant access control. Approved incident evidence is sent to the existing external
Groq provider. Only the two established public Vite configuration values are needed;
admin, provider and database credentials must remain outside the browser.

## Local validation without production

Use only a disposable local PostgreSQL instance, following
[the existing Milestone 1 procedure](sre_milestone1.md). Integration fixtures accept
only loopback PostgreSQL, create unique `infrasight_test_<uuid>` databases, migrate
those databases and drop them afterward. Never supply Neon or another existing
application database as a migration/test target.

From the repository root, with locked dependencies already installed:

```powershell
$env:APP_ENV = "test"
# Replace this example with the disposable local test cluster's URL only.
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55451/postgres"
$env:DATABASE_URL = $env:TEST_DATABASE_URL
uv run --frozen --no-sync pytest -q
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync python scripts/validate_deployment.py
git diff --check
cd frontend
npm.cmd test
npm.cmd run typecheck
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_API_READ_KEY = "ci-public-demo-key"
npm.cmd run build
```

Tests use mocked provider responses; no Groq credentials or external provider requests
are needed. Real HTTP exercise tests use temporary loopback Uvicorn listeners and
disposable PostgreSQL only. They prove actual 200/503 observations, projected provider
payloads, unchanged database contents after Scout requests, and database-enforced
read-only behavior. Frontend tests cover explicit submission, deep links, scope changes,
errors, invalid IDs and preserved analytics behavior.

No migrations, new dependencies/services, production configuration changes, deployments
or pushes are introduced by this milestone. Live Groq testing is deliberately skipped;
live AI generation and manual browser interaction have not been verified. Existing SRE
dashboard API discovery gaps documented in
[sre_dashboard.md](sre_dashboard.md) remain outside this milestone.

## Implementation validation

- Complete backend suite: **504 passed**, including 48 Scout incident unit/integration
  cases and the existing analytics, SRE, migration and HTTP exercise regressions.
- Complete frontend suite: **110 passed across 11 files**; 100 existing tests preserved.
- Explicit TypeScript check and production Vite build: passed. The build used a
  loopback origin and a fake public read key, with no API requests.
- Repository Ruff lint, CI-scoped formatting check, offline deployment validation,
  and Git whitespace checks: passed.
- PostgreSQL tests reused the existing disposable local cluster on port 55451 and
  created/dropped only fixture-owned test databases. The cluster was not reinitialized.
  Provider responses were mocked throughout; no Neon, Render or Groq service was used.

Nonblocking warnings: the installed Starlette test client uses a deprecated AnyIO
alias, and Vite reports an application chunk above 500 kB. No warning thresholds or
tests were weakened. No unresolved test failures remain. Visual review and a real
provider session remain separate review steps; automated tests do not establish those.
