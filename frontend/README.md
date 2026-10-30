# InfraSight AI interview frontend

React, TypeScript, Vite and IBM Carbon. Overview, Scout and Pipeline are preserved.
Milestone 2 adds Live Operations, Incident Center and nested Incident Details.
The Streamlit dashboard remains an independent fallback.

## SRE operations workspace

The new SRE pages consume only the Milestone 1 GET APIs. They show real service,
incident, HTTP evidence, timeline and recovery records. Health is unknown without
supporting evidence and becomes stale as observations age; a resolved incident
does not imply current healthy operation. Refresh reads stored records without
starting probes. No SRE mutation controls or admin credentials are included.

See [the SRE Dashboard runbook](../docs/sre_dashboard.md) for data sources, status
rules, backend limitations, tests and local review. Direct links use #/operations,
#/incidents and #/incidents/{UUID}. SRE_ENABLED remains disabled by default on the
backend; this frontend does not enable it or create demonstration records.

## Run locally

From the repository root, with project PostgreSQL on localhost:55432:

```powershell
.\.venv\Scripts\python.exe -m uvicorn infrasight.main:create_app --factory --host 127.0.0.1 --port 8001 --reload
```

Keep backend credentials in the ignored backend environment file. In another terminal:

```powershell
cd frontend
npm.cmd ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
# Set VITE_API_BASE_URL=http://127.0.0.1:8001 privately in .env.local.
# Set VITE_API_READ_KEY to match the backend demo read key; do not print it.
npm.cmd run dev
```

Open http://127.0.0.1:5173. Keep existing unrelated services untouched; if this
frontend port is occupied, run npm.cmd run dev -- --port 5174 instead.

## Assessment and presentation

The Live assessment uses the most recently requested successful simulated-cloud
ETL run's window end as its reference. It remains stable until a newer successful
run is loaded via navigation, Refresh, or completion of Run Demo ETL. Running and
failed runs do not replace it. The analysis window is the hour preceding that
reference, with a 20-sample minimum for relevant AI tools. Freshness is evaluated
at that reference using the existing 120-second threshold. With no successful
run, current time is used and missing/stale telemetry is shown honestly.

The health dropdown has exactly Live and Avg. Live shows server health counts;
Avg shows duration-weighted recorded health percentages for the selected hour.
Missing time is excluded and coverage is disclosed; overlapping intervals make
Avg unavailable. Timestamp display is fixed CST (UTC-6), while API parameters
and database timestamps remain UTC. No scheduler or automatic AI submission runs.

Scout suggestions populate the question only. Analyze explicitly submits it.
Answers retain their original reference and evidence. The Pipeline database sample
is fictional, collapsed by default, and never loads real database contents.

## Data and security

Development uses Vite's same-origin /api/v1 proxy to VITE_API_BASE_URL.
Production uses the configured HTTPS API origin directly. See the
[deployment runbook](../docs/deployment.md).

VITE_* values are browser-visible. VITE_API_READ_KEY is an intentional public/demo
credential. Never include admin, database or provider secrets in frontend settings.
General POST /api/v1/etl/run still requires both read and admin keys. The separate
POST /api/v1/demo/etl/run accepts the read key only for simulated-cloud and a
server-selected current window of at most 120 seconds. It rejects client parameters
and cannot ingest host metrics. No replay or unrestricted mutation controls exist.

Money remains exact strings/Decimal values; Number conversion is used only for
chart geometry. Coverage percentages and server reporting counts are distinct.

Consumed endpoints:

- GET /api/v1/analytics/overview
- GET /api/v1/analytics/regions
- GET /api/v1/analytics/average-health (only when Avg is selected)
- GET /api/v1/etl/runs (latest history and successful-run reference)
- POST /api/v1/demo/etl/run (explicit button click)
- POST /api/v1/ai/query (explicit Analyze action)

## Verification

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Tests mock fetch and AI responses. Browser verification must not trigger real AI
or production ETL. No frontend authentication framework or additional infrastructure
is introduced. InfraSight AI is independent and uses no IBM logos or affiliation.
