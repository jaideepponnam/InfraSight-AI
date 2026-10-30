# Public interview deployment

**Feature-branch status:** SRE Milestone 1 adds migration 0003 but remains disabled
in render.yaml. These release instructions are for a future separately approved
deployment, not authorization to access production or migrate Neon. For review now,
use the disposable local procedure in [sre_milestone1.md](sre_milestone1.md).

**Frontend:** https://jaideepponnam.com → Render static site. **API:** https://api.jaideepponnam.com → Render Python web service → Neon PostgreSQL (direct TLS connection) → existing controlled Groq tools. The approved UI, analytics definitions, ETL and AI harness are unchanged. No automatic seeding, continuous worker, or new infrastructure is added.

## 1. Neon

Create a project/database in a region close to the Render backend. In Connect, disable connection pooling and copy the **direct** PostgreSQL connection string. Keep the TLS query parameters, including sslmode=require and channel_binding=require if provided. Standard postgres://, postgresql:// and existing postgresql+psycopg:// schemes are supported and normalized safely.

Use the direct endpoint for runtime, migrations, and CLI ingestion. A hostname containing -pooler is rejected: ETL holds a dedicated session-level advisory lock across batch commits. [Neon documents that transaction pooling does not support this lock](https://github.com/neondatabase/website/blob/main/content/docs/connect/connection-pooling.md). The existing SQLAlchemy pool remains small (2 + 2 overflow), with pre-ping and timeouts. The managed Neon endpoint is network-accessible; this free-tier setup protects database access with TLS and credentials kept on the backend. Do not expose the local Docker database or export database credentials to the frontend. Use a database role that owns the application's schema for this single-service prototype; a separated migration/runtime role is deferred.

## 2. Backend environment

Set these in Render's backend environment, never in source control:

| Name | Purpose / configuration |
| --- | --- |
| DATABASE_URL | Neon **direct TLS** URL; confidential |
| API_READ_KEY | Dedicated public-demo read credential; intentionally browser-visible via its frontend counterpart |
| API_ADMIN_KEY | Different confidential admin credential; never sent to the frontend |
| GROQ_API_KEY | Optional confidential provider credential; server-side only; omit for initial public staging |
| GROQ_MODEL | Existing supported model; blueprint supplies openai/gpt-oss-120b |
| APP_ENV | production |
| CORS_ALLOWED_ORIGINS | JSON array: ["https://jaideepponnam.com"] |
| DB_POOL_SIZE / DB_MAX_OVERFLOW | 2 / 2 |
| DB_CONNECT_TIMEOUT_SECONDS | 10 |
| DB_STATEMENT_TIMEOUT_MS | 10000 |
| LOG_LEVEL / HOST_ENABLED | INFO / false |
| UV_VERSION | 0.13.0 (blueprint pins the package manager) |

Existing ETL defaults remain: 75 servers, seed 7, 30-second intervals, 1% malformed events. Existing AI limits remain unchanged. Generate distinct high-entropy read and admin keys through a password manager; the application rejects identical configured keys. A missing read/admin key continues to fail closed on its endpoints. An unconfigured Groq provider cannot produce AI answers.

## 3. Render backend

After reviewing and manually publishing the changes to GitHub, create a Blueprint from render.yaml, or create the two services manually using its settings. No credentials appear in the Blueprint; sync:false entries must be supplied in Render. Auto-deployment is disabled so migrations and releases remain deliberate.

Backend: Python runtime, repository root, Free plan, main branch. .python-version selects Python 3.11. Build command:

~~~sh
uv sync --frozen --no-dev
~~~

Start command (Render Linux shell; PORT is supplied by Render):

~~~sh
uv run --frozen --no-sync python -m uvicorn infrasight.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
~~~

Health-check path: /health/ready. /health, /health/ready, /docs and /openapi.json remain public. Readiness tests database connectivity, not whether migration/seed initialization is complete. Custom domain: api.jaideepponnam.com. The existing Docker Compose PostgreSQL service is local development only (127.0.0.1:55432); Render uses the native Python runtime, not local Docker volumes.

## 4. Fresh database initialization

Perform this **once before making the demo available**, from a trusted local checkout/virtual environment. Render Free services do not provide shell access or pre-deploy migration hooks; local migration commands use the same application code. [Render free limitations](https://render.com/docs/free), [pre-deploy commands](https://render.com/docs/deploys).

Open a separate PowerShell terminal at the repository root. Supply the Neon URL without echoing it or saving it to shell history:

~~~powershell
$productionDatabase = Read-Host "Neon direct DATABASE_URL" -AsSecureString
$env:DATABASE_URL = [System.Net.NetworkCredential]::new('', $productionDatabase).Password
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
~~~

Expected migration head for this feature branch: **0003** (baseline: 0002). Do not run tests against Neon: integration tests require CREATEDB and deliberately migrate/drop uniquely named disposable databases.

Use the **existing ETL CLI**, not a second seed system. Ensure these scenario settings match the defaults used by Render in the same temporary terminal:

~~~powershell
$env:SIMULATOR_SERVER_COUNT = "75"
$env:SIMULATOR_SEED = "7"
$env:TELEMETRY_INTERVAL_SECONDS = "30"
$env:SIMULATOR_MALFORMED_RATE = "0.01"
~~~

 The two commands below each run one bounded three-minute simulator window. Seed the previous equivalent period first to support an honest cost comparison, then the selected historical snapshot:

~~~powershell
.\.venv\Scripts\python.exe -m infrasight.ingestion.cli run --source simulator --source-id simulated-cloud --start 2026-10-10T19:30:00Z --end 2026-10-10T19:33:00Z
.\.venv\Scripts\python.exe -m infrasight.ingestion.cli run --source simulator --source-id simulated-cloud --start 2026-10-11T19:30:00Z --end 2026-10-11T19:33:00Z
Remove-Item Env:DATABASE_URL
~~~

Close that terminal afterward. Six minutes of interval telemetry is modest: 75 servers, at most 900 raw events, intentional rejections, persisted ETL audit counters. Replaying a window is idempotent but adds another audit run/rejection attempt; do not replay unnecessarily. Do not run the broader phase4_demo.py script or the three-cycle demo CLI as a deployment seed. These are optional historical examples for simulated-cloud. The current React UI uses the latest successful run and the preceding hour, rather than a fixed snapshot.

Sequence: **fresh DB → approved migration head → bounded previous/current ETL windows → authenticated analytics verification → frontend available**. Start commands never migrate or seed. LIVE mode remains available but no scheduler is introduced; current wall-clock telemetry will legitimately be STALE until an operator runs an approved bounded current cycle.

## 5. Render frontend

Create a Static Site with root directory frontend, main branch, and:

- Build: npm ci && npm run build
- Publish: dist
- Node: 22.15.1
- SKIP_INSTALL_DEPS=true (the build installs locked dependencies explicitly)
- SPA rewrite: /* → /index.html
- Custom domain: jaideepponnam.com

Frontend build-time environment:

| Name | Configuration |
| --- | --- |
| VITE_API_BASE_URL | https://api.jaideepponnam.com |
| VITE_API_READ_KEY | Exactly the dedicated backend API_READ_KEY value |

**VITE_* values are browser-visible by design.** VITE_API_READ_KEY is a public/demo credential, not a confidential secret. Only the two named values are allowed into client code by Vite configuration. Never configure DATABASE_URL, API_ADMIN_KEY, GROQ_API_KEY, or variants of those keys on the static site. Both /api/v1/etl/run and /api/v1/demo/etl/run require the separate admin key in addition to the read key. The demo endpoint retains its fixed simulator and server-selected window of at most 120 seconds for trusted operators. Pipeline displays recorded history and a read-only explanation; its Refresh action only reads. No browser ETL mutation method remains. CORS is not authentication and does not prevent non-browser callers from using the public read key. Use only intentionally public demonstration data in staging.

Scout requests remain read-key authorized and can consume provider quota when configured. For initial public staging, omit GROQ_API_KEY on the backend; AI requests return 503 AI_NOT_CONFIGURED before contacting Groq. Incident pages and Scout navigation remain available, but no live AI answer is generated. Existing per-request bounds do not limit aggregate public usage. Review access and quota controls separately before enabling public AI. Publish the backend authorization fix before the public frontend; cached older clients can receive an authorization error from their old demo button. This change needs no schema migration or new environment variables and does not change SRE exercise authorization.

Production browser requests go directly to the configured HTTPS API origin with X-API-Key. Build validation rejects absent configuration, embedded URL credentials, paths, and insecure remote origins. Changing either Vite value requires a frontend rebuild. Local npm run dev retains the same-origin Vite proxy and existing localhost setup. Do not use Vite's development server as public hosting.

## 6. Cloudflare DNS

First attach each domain to its corresponding Render service, then use the **actual onrender.com targets displayed by Render**:

| Type | Name | Target | Initial proxy mode |
| --- | --- | --- | --- |
| CNAME | @ | frontend static site's onrender.com hostname | DNS only |
| CNAME | api | backend web service's onrender.com hostname | DNS only |
| CNAME | www | frontend hostname, if using Render's apex/www redirect | DNS only |

Cloudflare handles apex CNAME flattening. Replace conflicting A/AAAA/CNAME records **only for these web hostnames** after recording their old values; leave mail/MX/TXT records alone. Remove conflicting AAAA records for these hosts. Wait for Render's domain verification and TLS certificates. DNS-only is the simplest working configuration; proxying is optional after certificates are valid. If enabling proxying later, use Full (strict) TLS and do not cache authenticated /api responses. [Render's Cloudflare DNS instructions](https://render.com/docs/configure-cloudflare-dns).

## 7. Verification

- Confirm Render deploy logs are successful and /health returns 200.
- Confirm https://api.jaideepponnam.com/health/ready returns 200 and Alembic current matches the separately approved release revision.
- Test an analytics GET with the dedicated read key and the historical source/reference/window; missing key must remain 401.
- Confirm the browser OPTIONS preflight from https://jaideepponnam.com permits X-API-Key/Content-Type and returns that exact allow-origin. Other origins must not receive permission.
- Open https://jaideepponnam.com and inspect all three views. Confirm the Live reference matches the latest successful ETL run; verify reporting counts, observation-time coverage, cost currency and ETL audit runs from actual data.
- Do not trigger ETL or submit AI during deployment verification. Automated tests fake the provider and prove public-read credentials cannot trigger either ETL endpoint; authorized bounded demo behavior is verified with mocks.
- Confirm admin/database/provider credentials are absent from the frontend environment/build. Check browser network requests use api.jaideepponnam.com, not a local proxy.
- Before the interview, warm the free backend by opening /health/ready; a Render Free cold start can take about a minute, longer than the frontend's normal read timeout. Then refresh the app. [Render cold-start behavior](https://render.com/docs/free).

## 8. CI and rollback

.github/workflows/ci.yml has two jobs: PostgreSQL 16-backed backend tests (including migration downgrade/re-upgrade in disposable databases), Ruff, Alembic upgrade/check and offline deployment configuration checks; and locked frontend install, tests, typecheck and build. No production or Groq credentials are used. CI does not deploy.

Use Render's manual deploy/redeploy controls after CI passes. Redeploy backend before frontend when API-origin/key configuration changes, then verify both. App rollback does not roll back Neon data. This branch adds the additive SRE migration 0003; take an appropriate Neon backup/branch before any separately approved migration and prefer forward fixes. Keep SRE_ENABLED=false until schema and backend verification are complete. Omit SRE_PROBE_PORT on Render so probes inherit PORT. Never downgrade the production schema casually. A static-site rollback may restore an old public demo key, so keep backend/frontend key settings synchronized. The Streamlit fallback remains intact.
