# Phase 7: Infrastructure intelligence console

Install the frontend extra, then run FastAPI and Streamlit in separate terminals:

~~~powershell
.\.venv\Scripts\uv.exe sync --extra host --extra dashboard --python .\.venv\Scripts\python.exe --cache-dir .\.uv-cache
.\.venv\Scripts\python.exe -m uvicorn infrasight.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
.\.venv\Scripts\python.exe -m streamlit run src/infrasight/dashboard/app.py
~~~

Open http://127.0.0.1:8501. Configure server-side environment variables:
INFRASIGHT_API_BASE_URL=http://127.0.0.1:8000, INFRASIGHT_API_KEY (matches API_READ_KEY),
and optional INFRASIGHT_ADMIN_KEY (matches API_ADMIN_KEY). Values are never displayed.
The frontend configuration has no database or Groq fields; all data arrives over HTTP.

The graphite/navy console contains Overview, Infrastructure, Cost Analytics, AI Analyst,
and Data Pipeline. Historical demo defaults to simulated-cloud at 2026-10-11T19:33:00Z,
with the 19:30–19:33 UTC window. It is visibly labeled SNAPSHOT, not LIVE.
Switch to Live to evaluate current freshness; absent recent telemetry remains STALE.
Custom UTC windows, source/region/environment filters, currency and assessment thresholds
remain explicit. Historical assessments use four samples; normal live defaults use twenty.

Auto-refresh uses Streamlit fragments every 25 seconds. The AI page never auto-submits;
questions execute only through the Analyze button. Evidence can be expanded. Provider
rate limits/failures, invalid parameters and authorization errors have clean UI messages.
The AI API supports source/time/currency scope; region/environment filters must be included
in the question and this limitation is disclosed. Stored answers retain their original context.

Infrastructure has paginated health/telemetry tables, page-local search, health filtering,
server inspection, critical observations, CPU breaches, pressure and resource rankings.
Cost Analytics presents regional interval costs, equivalent-period comparisons, top cost
servers and first-class optimization cards. No guaranteed savings, fake time-series,
forecast, or unsupported environment totals are invented. Existing APIs expose summaries,
not utilization history; graphs use those actual summaries.

Money remains Decimal or strings in Python and tables. Cost chart source values and exact
tooltips remain strings; browser chart geometry uses quantitative scaling. Coverage is
observation-time coverage, separate from reporting-server counts. Currency is never converted.
STALE/NO_DATA remain separate from recorded health. Multi-source charts keep source cohorts
separate. Data Pipeline lists real audit runs and permits a confirmed synchronous cycle only
when an admin key is configured. Replaying the selected window is deliberate and auditable.

Focused tests cover the HTTP client, safe formatting and freshness presentation. Local UI
verification uses Streamlit AppTest against the real FastAPI, plus browser screenshots when
available. Verification never submits AI automatically or triggers ETL without confirmation.
No backend redesign, deployment, workers, commit or push belongs to this phase.


### Simple Pipeline demo

Pipeline displays recorded run counters and history with a read-only explanation.
Ingestion is managed by an operator; the browser has no Run Demo ETL action.
POST /api/v1/demo/etl/run requires both read and admin keys, just like general ETL.
It retains only simulated-cloud and a server-chosen current UTC window of at most
120 seconds. No client parameters, host source, replay controls, live database
browsing, scheduler, or new infrastructure is exposed. Refresh loads newly recorded
operator results. The database reference is fictional and collapsed by default;
it makes no data requests. Admin, database and provider secrets stay outside the browser.

The React dashboard now defaults to Live, with Overview, AI Analyst, and Pipeline
in the top header. After a new run, open Overview or AI Analyst, or use Refresh
analytics, then submit a new question. Existing answers are not rerun automatically
when the context changes. Display timestamps use CST;
API inputs and analytical windows remain UTC. No new Render variables are required;
deploy the backend before the frontend.


### Latest completed-run assessment

The React dashboard resolves the most recently requested successful simulated-cloud
ETL run before loading analytics. Health/reference time is pinned to its requested
window end; the selected analysis period is the preceding hour. Refresh or navigation
checks for a newer successful run after an operator completes ingestion. A running/failed
run never replaces the last successful assessment.
Freshness rules remain unchanged and are evaluated at the explicitly displayed run
reference, not the current wall clock. Without a successful run, the dashboard uses
current time and honestly displays missing/stale telemetry. There is no scheduler or
automatic AI resubmission. Avg shows duration-weighted recorded health percentages
in the selected hour, excludes unobserved time, and flags overlap as unavailable.
