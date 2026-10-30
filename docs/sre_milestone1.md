# InfraSight AI 2.0: Milestone 1

## What the exercise demonstrates

An admin initiates a controlled **application-dependency HTTP 503 failure**. This is
not a storage outage. The workload returns actual 200/503 responses through the API's
HTTP listener; probes measure status, duration and correlation IDs. PostgreSQL persists
the lifecycle and evidence. No continuous worker or local service is needed for a
future hosted demonstration.

Existing ETL, analytics, Scout, React/Carbon, Streamlit and health routes are preserved.
No React SRE pages, AI incident tools, paid service or new dependency is introduced.
SRE_ENABLED defaults to false, including in render.yaml.

## Behavior and safety

Creation performs one healthy baseline probe, enables the exercise-specific expiring
fault, then requires three fresh consecutive 503 responses before creating an incident.
The synchronous response contains an ACTIVE run in DETECTED phase. An admin must
acknowledge it and explicitly request recovery before the 120-second default deadline.

Normal lifecycle:
DETECTED â†’ ACKNOWLEDGED â†’ INVESTIGATING â†’ MITIGATING â†’ VERIFYING â†’ RESOLVED.

Recovery collects three new diagnostic probes before the fixed
clear-controlled-dependency-fault action and three healthy post-action probes.
Samples must be at most 15 seconds old and identify the correct workload and run.
These short observations are not a sustained availability SLO. Timeouts, stale/missing
samples, unexpected responses and fault expiration cannot establish verified recovery.

Failed verification leaves an INVESTIGATING incident and FAILED recovery attempt.
A new recovery idempotency key can reverify an earlier applied action without
crediting the action twice. Anticipated recovery failures return HTTP 200 with a FAILED
attempt; always inspect status. Unexpected execution errors return a sanitized 503
and retain failure audit state when the database is available.

PostgreSQL row locks serialize short control transactions; locks/connections are released
during HTTP work. Partial unique indexes enforce one active exercise per service,
one active incident per fingerprint, and one running recovery per incident. Fingerprints
include the exercise ID: repeated detection deduplicates within an exercise, while a
separate exercise has its own incident.

Idempotency-Key must be a UUID for creation and recovery. Repeating it returns the
existing resource, including RUNNING while an original request is still executing.
Repeated acknowledgement does not create another audit event.

At most 24 probes and three recovery attempts are permitted per exercise/incident.
The default creation cooldown is 60 seconds. Clients cannot select URLs, ports,
service identities, commands, SQL, fault duration or alternate recovery actions.

The fixed probe destination is loopback at the server-controlled listener port.
The hidden target requires a loopback caller and an ephemeral run capability. Only its
SHA-256 hash is stored. Capabilities rotate per operation and are revoked at completion
or reconciliation. Admin credentials are never forwarded to the workload. Probes disable
redirects and environment proxies, cap response bodies and retain only approved fields.

An interrupted process needs no worker to finish cleanup. At the deadline the target
stops honoring the fault. The next SRE admin request marks expired ACTIVE work INTERRUPTED,
revokes its capability, interrupts unfinished attempts, and records unverified recovery.
GET requests never mutate state: an expired run can remain stored as ACTIVE until that
reconciliation. Interrupted incidents remain open, rather than claiming recovery.
A new exercise can then run.

## Endpoints

Prefix: /api/v1/sre. All GETs require X-API-Key. **Every POST requires both X-API-Key
and X-Admin-Key.** No privileged credential belongs in React, Vite, browser storage or URLs.
CORS does not permit admin/idempotency headers. The separate /api/v1/demo/etl/run
also requires both read and admin keys. An additional /api/v1/demo/public-etl/run
supports the Pipeline Run ETL button only when DEMO_PUBLIC_ETL_ENABLED=true
(default false), using the public read key and fixed simulator bounds. This opt-in
ETL operation has no cooldown and does not create SRE services or incidents.
SRE exercise endpoints, deadlines, cooldown and admin authorization are unchanged.

| Method | Path | Contract |
| --- | --- | --- |
| GET | /services | Fixed service metadata; initially empty |
| GET | /incidents | Optional state, limit 1â€“100, offset 0â€“10000 |
| GET | /incidents/{id} | State, policy and timestamps |
| GET | /incidents/{id}/events | Ordered audit history |
| GET | /incidents/{id}/evidence | Run, probes and recovery attempts |
| GET | /demo-runs/{id} | Stored execution phase, status and deadline |
| POST | /demo-runs | {} or {"scenario":"http-503"}; UUID Idempotency-Key |
| POST | /demo-runs/{id}/probe | {}; new detection probes, incident deduplication |
| POST | /incidents/{id}/acknowledge | {}; explicit admin acknowledgement |
| POST | /incidents/{id}/recover | {} or fixed action; UUID Idempotency-Key |

Unknown JSON fields and mutation query parameters are rejected. Conflicts return 409,
invalid parameters 422, cooldown/budget limits 429, and disabled/unavailable SRE 503.
All responses carry request IDs. The hidden /_sre-demo/{run_id}/dependency GET is
capability-protected, returns 404 without authorization, and is excluded from OpenAPI.

## Database

Migration 0003 follows 0002 and adds six tables:

| Table | Records |
| --- | --- |
| sre_services | Fixed service identity and scenario description |
| sre_demo_runs | Scenario, phase/status, idempotency, hashed capability, fault and deadline |
| sre_probe_results | Phase, observation time, duration, HTTP outcome, correlation IDs, evidence |
| sre_incidents | Run/service, fingerprint, severity, policy, lifecycle, timestamps, version |
| sre_incident_events | Sequence, actor role, transition, request ID, evidence references |
| sre_recovery_attempts | Action, idempotency, execution/verification outcome and timestamps |

Foreign keys use RESTRICT. Constraints validate states, scenarios, actions, timing,
sequence, durations and HTTP ranges. No legacy table/view or production row is changed.
The first explicit exercise creates service metadata; startup never migrates or seeds.
The migration contains frozen DDL, independent of mutable model definitions.

Migration tests preserve every row in all seven populated legacy tables and retain
analytics views across SRE upgrade/downgrade/re-upgrade. Integration fixtures reject
remote hosts and connection-target query overrides and create/drop only new
infrasight_test_<uuid> databases. Tests need a local CREATEDB role; existing analytics
permission tests also create temporary roles.

## Exact local review (PowerShell)

Use a fresh terminal at the repository root on feature/sre-incident-engine. These
commands use a new disposable local PostgreSQL 16 container, never Neon or the
existing Compose volume. Local services are for development only; the eventual
hosted demonstration uses Render and Neon.

Check the branch and ports, then start the review database:

~~~powershell
git branch --show-current
if (Get-NetTCPConnection -LocalPort 55439,8000 -State Listen -ErrorAction SilentlyContinue) {
    throw "A review port is already occupied."
}
docker run --rm --name infrasight-sre-review -e POSTGRES_USER=infrasight -e POSTGRES_PASSWORD=review-only-password -e POSTGRES_DB=infrasight_sre_review -p 127.0.0.1:55439:5432 -d postgres:16-alpine -c timezone=UTC
~~~

Wait until this succeeds:

~~~powershell
docker exec infrasight-sre-review pg_isready -U infrasight -d infrasight_sre_review
~~~

Select the local URL, install locked dependencies, and verify:

~~~powershell
$reviewDb = "postgresql+psycopg://infrasight:review-only-password@127.0.0.1:55439/infrasight_sre_review"
$env:DATABASE_URL = $reviewDb
$env:TEST_DATABASE_URL = $reviewDb
$env:APP_ENV = "test"
uv sync --frozen --all-extras
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/validate_deployment.py
~~~

Migrate only that explicitly selected local database. Generate local-only keys in
memory and start the API; no production key is needed:

~~~powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
$env:SRE_ENABLED = "true"
$env:SRE_PROBE_PORT = "8000"
$env:SRE_RUN_DEADLINE_SECONDS = "120"
$env:SRE_COOLDOWN_SECONDS = "0"
$env:API_READ_KEY = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$env:API_ADMIN_KEY = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$env:GROQ_API_KEY = ""
$env:LOG_LEVEL = "WARNING"
$reviewPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$reviewApi = Start-Process -FilePath $reviewPython -ArgumentList @("-m","uvicorn","infrasight.main:create_app","--factory","--host","127.0.0.1","--port","8000","--no-access-log") -WindowStyle Hidden -PassThru
~~~

Run the lifecycle in the same terminal within the 120-second exercise deadline:

~~~powershell
$base = "http://127.0.0.1:8000/api/v1/sre"
$readHeaders = @{ "X-API-Key" = $env:API_READ_KEY }
$adminHeaders = @{ "X-API-Key" = $env:API_READ_KEY; "X-Admin-Key" = $env:API_ADMIN_KEY }
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod "http://127.0.0.1:8000/health/ready" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw "Local review API did not become ready." }
$createHeaders = $adminHeaders.Clone()
$createHeaders["Idempotency-Key"] = [guid]::NewGuid().ToString()
$run = Invoke-RestMethod "$base/demo-runs" -Method Post -Headers $createHeaders -ContentType "application/json" -Body "{}"
$incidents = Invoke-RestMethod "$base/incidents" -Headers $readHeaders
$incident = $incidents.data | Where-Object { $_.run_id -eq $run.data.id }
$incident | Format-List
Invoke-RestMethod "$base/incidents/$($incident.id)/acknowledge" -Method Post -Headers $adminHeaders -ContentType "application/json" -Body "{}"
$recoverHeaders = $adminHeaders.Clone()
$recoverHeaders["Idempotency-Key"] = [guid]::NewGuid().ToString()
Invoke-RestMethod "$base/incidents/$($incident.id)/recover" -Method Post -Headers $recoverHeaders -ContentType "application/json" -Body "{}"
Invoke-RestMethod "$base/incidents/$($incident.id)/events" -Headers $readHeaders | ConvertTo-Json -Depth 12
Invoke-RestMethod "$base/incidents/$($incident.id)/evidence" -Headers $readHeaders | ConvertTo-Json -Depth 12
~~~

Expected: DETECTED then RESOLVED, one SUCCEEDED recovery attempt and ten measured
probes: one baseline 200, six 503s including pre-action confirmation, and three
verified 200s. Evidence contains timing and correlation IDs, never keys/capabilities.

Stop only the review process/container created above:

~~~powershell
Stop-Process -Id $reviewApi.Id
docker stop infrasight-sre-review
Remove-Item Env:API_ADMIN_KEY,Env:API_READ_KEY,Env:DATABASE_URL,Env:TEST_DATABASE_URL
~~~

To verify the unchanged frontend in a separate terminal:

~~~powershell
cd frontend
npm ci
npm test
$env:VITE_API_BASE_URL = "https://api.jaideepponnam.com"
$env:VITE_API_READ_KEY = "ci-public-demo-key"
npm run build
~~~

Frontend tests mock fetch; the build does not call production APIs.

## Future release preparation and limitations

This implementation does not authorize a deployment. Render retains two existing
services with auto-deploy off and SRE_ENABLED=false. Startup does not migrate/seed.
No production Neon access, credential change, merge, or deployment is needed to review.

A separately approved release should review CI and migration 0003, prepare an
appropriate backup/branch, apply the additive migration through a trusted environment,
release while SRE is disabled, then enable deliberately. On Render omit SRE_PROBE_PORT
to inherit PORT. Retain one worker, the small connection pool and Neon's direct TLS
URL; legacy ETL requires session advisory locks. App rollback does not revert data.

Application-level isolation shares API resources and cannot independently observe a
total API/Render outage. Free hosting can sleep/restart. Shared keys attribute actions
to roles rather than individuals. Audit history is append-only through application
operations, but a privileged database role can alter it. Expired/interrupted incidents
remain open if recovery was not verified. Retention/pruning, per-user RBAC, independent
probes, React SRE pages and Scout incident integration are later work.

## Verification results

- Full backend suite: 456 passed against temporary PostgreSQL 16; no integration skips.
- Existing frontend suite: 50 passed across seven files.
- Frontend typecheck and production build: passed using a fake public build key.
- Ruff lint, CI formatting scope, offline deployment validation: passed.
- Existing warnings: Starlette/AnyIO deprecated BlockingPortal alias; Vite bundle over 500 kB.
- Initial legacy timestamp test failure was corrected by explicitly selecting UTC in
  disposable fixtures; the test assertion was retained. Windows sandbox restrictions
  required dependency installation/frontend commands to run with approved escalation.
- No production Neon, provider, or application API requests, credential changes,
  merges, pushes, or deployments were performed. Dependencies/lockfiles were not changed.

## File inventory

Created:

- `docs/sre_milestone1.md`
- `migrations/versions/0003_create_sre_schema.py`
- `src/infrasight/api/sre.py`
- `src/infrasight/api/sre_demo.py`
- `src/infrasight/db/models/sre.py`
- `src/infrasight/sre/__init__.py`
- `src/infrasight/sre/lifecycle.py`
- `src/infrasight/sre/probes.py`
- `src/infrasight/sre/recovery.py`
- `src/infrasight/sre/repository.py`
- `src/infrasight/sre/rules.py`
- `src/infrasight/sre/schemas.py`
- `src/infrasight/sre/services.py`
- `tests/integration/test_sre_demo.py`
- `tests/integration/test_sre_incidents.py`
- `tests/integration/test_sre_migrations.py`
- `tests/unit/test_sre_lifecycle.py`
- `tests/unit/test_sre_security.py`

Modified:

- `.env.example`
- `.github/workflows/ci.yml`
- `README.md`
- `docs/data_dictionary.md`
- `docs/deployment.md`
- `render.yaml`
- `scripts/validate_deployment.py`
- `src/infrasight/api/dependencies.py`
- `src/infrasight/api/errors.py`
- `src/infrasight/api/router.py`
- `src/infrasight/config.py`
- `src/infrasight/db/models/__init__.py`
- `src/infrasight/main.py`
- `tests/integration/conftest.py`
- `tests/integration/test_analytics_migrations.py`
- `tests/integration/test_database.py`
- `tests/integration/test_migrations.py`
- `tests/unit/test_config.py`
