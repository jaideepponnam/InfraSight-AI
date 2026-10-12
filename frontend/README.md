# InfraSight AI — interview frontend

React + TypeScript + Vite with IBM Carbon components. Three views: Overview, AI Analyst, Pipeline. Streamlit remains an independent fallback; backend behavior is unchanged.

## Run locally

From the repository root (PostgreSQL is already configured on localhost:55432):

```powershell
.\.venv\Scripts\python.exe -m uvicorn infrasight.main:create_app --factory --host 127.0.0.1 --port 8000
```

The existing backend environment must configure API_READ_KEY. Do not print or commit it.

In another terminal:

```powershell
cd frontend
npm.cmd install
Copy-Item .env.example .env.local
# Edit .env.local privately: VITE_API_READ_KEY must match backend API_READ_KEY.
npm.cmd run dev
```

Open http://127.0.0.1:5173. If ports are occupied, leave existing services untouched: use API port 8001, set VITE_API_BASE_URL=http://127.0.0.1:8001 privately, and run npm.cmd run dev -- --port 5174 (http://127.0.0.1:5174). Default SNAPSHOT scope: simulated-cloud, 2026-10-11 19:30–19:33 UTC, reference 19:33, freshness 120 seconds, assessment minimum 4 samples. LIVE uses the previous hour and a 20-sample minimum; it does not imply telemetry is fresh. Refresh explicitly retrieves current data. Suggestions populate the question only; Analyze explicitly calls AI.

## Data and security

Development browser requests use same-origin /api/v1 paths through Vite’s proxy to VITE_API_BASE_URL (default http://127.0.0.1:8000). Production builds and Vite preview call the configured API origin directly. FastAPI permits explicit configured origins and retains localhost development support. Render static hosting needs no Vite proxy; see [the deployment runbook](../docs/deployment.md).

VITE_* configuration is browser-visible by design. VITE_API_READ_KEY is a public/demo credential, not a confidential secret. Match the dedicated backend read key; never configure admin, database or provider secrets on the static site. The application’s ETL endpoints retain separate admin authorization.

Money is parsed with decimal.js and never converted to Number. Number conversion is used only for utilization bar geometry. Coverage and freshness use backend values; reporting counts and observation-time percentages are distinct. The two compact visualizations use accessible CSS bars, avoiding an extra chart stack.

Consumed endpoints:

- GET /api/v1/analytics/overview
- GET /api/v1/analytics/regions
- GET /api/v1/etl/runs (latest 8)
- POST /api/v1/ai/query (explicit submission only)

## Verification

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

Tests fake fetch/provider responses. No real AI calls or ETL writes are needed. Deferred: automatic refresh, conversation persistence, inventory editing and extended dashboards.

Design references: [Carbon React](https://www.carbondesignsystem.com/getting-started/developing/carbon-core/react), [Vite proxy](https://vite.dev/config/server-options#server-proxy). InfraSight AI is an independent project and uses no IBM branding.
