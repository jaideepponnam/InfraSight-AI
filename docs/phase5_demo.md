# Phase 5: authenticated REST API demo

The API reuses Phase 4 analytics services. PostgreSQL stays at localhost:55432;
its Docker mapping remains 127.0.0.1:55432:5432. No database migration is required.

## Start manually

Set API_READ_KEY and API_ADMIN_KEY to different random values in your terminal environment
(or your ignored .env). Never commit these values. For example in PowerShell:

~~~powershell
$env:API_READ_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
$env:API_ADMIN_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
.\.venv\Scripts\python.exe -m uvicorn infrasight.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
~~~

Open http://127.0.0.1:8000/docs. Authorize ApplicationKey with your read key.
Authorize AdminKey additionally for ETL execution. Both keys are required for POST /api/v1/etl/run.
Health, readiness, Swagger, and OpenAPI remain public. No CORS is needed for server-side clients.

## Reproducible inspection

For historical analytics set:

- source_id: simulated-cloud
- as_of: 2026-10-11T19:33:00Z
- start: 2026-10-11T19:30:00Z
- end: 2026-10-11T19:33:00Z
- currency: USD
- limit: 100

1. GET /api/v1/analytics/overview: inspect health, cost, freshness, and coverage.
2. Repeat with current as_of: the historical fleet must become STALE, not healthy.
3. GET /api/v1/analytics/high-cpu: threshold=80, min_breach_count=1.
4. GET /api/v1/analytics/regions: compare regional current health and period cost.
5. GET /api/v1/analytics/cost-summary: inspect exact Decimal strings and top server.
6. GET /api/v1/analytics/underutilized and /cpu-pressure: min_samples=4 for this
   three-minute fixture. Normal defaults remain 20 samples and 80% coverage;
   underutilization/pressure default to a trailing 24-hour window.
7. GET /api/v1/servers?limit=2; repeat with offset=2. Inspect a returned server UUID.
8. GET /api/v1/etl/runs?source_id=simulated-cloud; inspect a returned run UUID.
9. POST /api/v1/etl/run with both keys and the body below. The response arrives
   after the cycle completes; HTTP 200 does not mean success unless status is SUCCEEDED.

~~~json
{"source":"simulator","start":"2026-10-11T19:30:00Z","end":"2026-10-11T19:33:00Z"}
~~~

Inspect inserted=0, duplicated=446, rejected=4. Repeat cost-summary: answers must not change.
The run history gains one entry; the committed watermark does not move backward.
Only simulator and optionally enabled host adapters are accepted. API ETL windows are
bounded to 600 seconds by default. Host replay reads stored events; it never invents history.

10. Remove the read key: a protected GET returns 401. Remove the admin key while
    keeping the read key: ETL POST returns 401 without executing a cycle.
11. GET /api/v1/servers?limit=101: expect 422 and matching body/header request ID.
12. Cost comparison: mode=explicit, source_id=simulated-cloud-phase4-comparison,
    the same current window, previous_start=2026-10-10T19:30:00Z and
    previous_end=2026-10-10T19:33:00Z. Inspect both coverage values and quality.

## Automated real HTTP verification

With port 8000 free:

~~~powershell
.\.venv\Scripts\python.exe scripts/phase5_demo.py
~~~

This starts its own loopback FastAPI process, uses ephemeral environment keys when
none are configured, exercises actual HTTP endpoints against the existing application
PostgreSQL data, and terminates only its own process. It preserves the fleet and
adds a replay audit entry. Reports/logs go to ignored .uv-cache/ and contain no keys.

Overview performs four SQL statements in one repeatable-read snapshot. Integration
instrumentation verifies the query count; fleet size does not cause per-server SQL calls.
All analytics windows are UTC, half-open, and bounded to seven days. Cost is observed
interval cost, split at period boundaries. Unknown cost remains null; currencies are never
combined or converted. Comparison quality prevents incomplete coverage becoming a
confident cost-increase claim. Historical dimensions reflect current inventory metadata.

## Verified HTTP results

The Phase 5 verification against the application database returned:

| Inspection | Actual result |
|---|---|
| Historical snapshot | 75 reporting; 64 healthy, 1 warning, 10 critical |
| Current snapshot of historical fleet | 75 STALE, zero current reporting servers |
| Strict CPU >80% | 11 servers, 43 breaches |
| Regional H/W/C | eu-de 21/0/4; us-east 22/0/3; us-south 21/1/3 |
| Observed three-minute cost | USD 1.03775797 |
| Highest-cost server | sim-075 |
| Short-window optimization / CPU-pressure candidates | 10 / 11, with min_samples=4 |
| Replay | 450 extracted, 446 accepted, 0 inserted, 446 duplicates, 4 rejected |
| Watermark after replay | Unchanged at 2026-10-11T19:33:00Z |
| Missing/invalid read key or missing admin key | HTTP 401 |
| limit=101 | HTTP 422 with matching body/header request ID |

Replay adds an audit run, so history counts grow with repeated demonstrations.
The short-window thresholds above are explicitly selected for the historical fixture.
All cost amounts are JSON decimal strings, including nested results. The API returns
FAILED ETL outcomes with HTTP 200 when a cycle completed and its failure was audited;
clients must inspect status/error_code. Pre-execution conflicts return 409; database
availability failures return 503.
