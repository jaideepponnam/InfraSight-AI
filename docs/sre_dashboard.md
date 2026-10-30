# SRE Dashboard: Milestone 2

Milestone 2 adds a read-only React/TypeScript/IBM Carbon operations workspace on
feature/sre-incident-engine. Overview, Pipeline and Scout retain their existing data
flows. No backend, database, deployment, dependency, environment-file or credential
changes are required by this milestone. SRE_ENABLED remains disabled by default.

## Pages and sources

| Page | Address | Actual API sources |
| --- | --- | --- |
| Live Operations | #/operations | GET /api/v1/sre/services, /incidents?limit=100&offset=0, incident-linked /evidence |
| Incident Center | #/incidents | GET /api/v1/sre/incidents with state/limit/offset; GET /services |
| Incident Details | #/incidents/{UUID} | GET /incidents/{id}, /events, /evidence; GET /services |

The service registry supplies names/descriptions, not health. Live Operations joins
the newest incident in the loaded records to its evidence. Evidence fan-out is capped
at 12 services. The newest 100 incidents are loaded for operations context, and the
UI explicitly discloses truncation. There is no claim that bounded records are fleet
totals. The open-record count explicitly refers to loaded incidents; total recorded
incidents comes from backend meta.total. Incident Center uses backend pagination (20 records per page), flat meta fields
total/limit/offset, and lifecycle filtering. It respects the API's maximum offset.

Details show metadata, measured HTTP outcomes and decimal durations, observation
timestamps, lifecycle events in backend sequence order, recovery attempts and their
verification evidence, exercise deadlines, and sanitized correlation payloads.
Individual evidence/timeline/registry failures do not discard available metadata.
A 401/403 clears protected results and shows read-access failure. Disabled SRE,
loading, missing incidents, invalid links, malformed responses and empty results are
distinct states. Resource identity checks prevent cross-incident evidence mixing.

Hash navigation supports direct links, Back to Incident Center and browser history.
The SRE header shows Read only / Stored observations instead of the ETL LIVE reference.
It never borrows an old telemetry timestamp for operational health.

## Evidence interpretation

The frontend validates SRE envelopes and record fields against the Milestone 1 schemas.
It preserves NUMERIC durations as strings and uses ISO observation instants separately
from local retrieval timestamps. Existing fixed CST display conventions are retained.

For backend policy controlled-http-503-v1, current evidence uses the same 15-second
freshness window as rules.py. Unknown policy versions cannot establish current health.
An in-browser clock updates the assessment every second without generating API calls:

- HEALTHY: a recent, matching HTTP 200 observation of the controlled dependency.
- DEGRADED: a recent, matching controlled HTTP 503 observation.
- STALE: latest evidence is older than the window, or an ACTIVE exercise has expired.
- UNKNOWN: no accessible observation, mismatched identity, unsupported policy, future
  timestamp, timeout, transport failure, invalid response, or no incident-linked evidence.

These are evidence assessments, not continuous monitoring or an availability SLO.
An empty incident list does not establish healthy services. Refresh retrieves stored
records; it does not run probes or extend sample freshness.

Recovery is shown as Verified only when the resolved lifecycle, succeeded exercise,
succeeded recovery attempt, backend verified_recovery flag, and matching healthy
post-action probe references corroborate each other. Failed, running, interrupted
and uncorroborated outcomes remain distinct. A historical Verified result can coexist
with STALE current evidence. Automatic fault expiration is not credited as verified
recovery. Concurrent lifecycle/timeline changes prompt a refresh warning.

## Security and scope

All new SRE methods issue GET requests using the existing public/demo read key. There
are no SRE mutation buttons, admin headers, admin inputs, browser-stored credentials,
provider calls, or privileged Vite variables. Existing legacy simulator ETL and Scout
actions retain their prior behavior. Backend authorization and CORS are unchanged.

Runtime pages contain no fixture incident data. Static examples exist only under
frontend/src/test, where fetch or the read methods are mocked. They are not imported
by the application build. Untrusted titles/descriptions/evidence are rendered as text.

Responsive layouts use Carbon spacing/color tokens, IBM Plex, Carbon tables, tiles,
tags, selects, accordions, notifications and buttons. Tables scroll within labelled
keyboard-focusable regions; narrow screens stack service/detail panels and allow
navigation scrolling. Incident headings receive focus on navigation.

## Backend gaps intentionally left unchanged

The existing API supports useful incident investigation but does not expose:

1. A per-service latest observation/status endpoint independent of incidents. Baselines
   and failed exercises that never create an incident cannot be discovered from /services.
2. A run collection or per-service latest-run endpoint. /demo-runs/{id} needs a known ID.
3. Server-evaluated freshness/reference time and policy metadata in read responses.
   The frontend currently mirrors v1's 15 seconds and depends on the browser clock.
4. Service-scoped incident filtering, fleet-wide open-incident aggregates, or an atomic
   incident/evidence/timeline snapshot. Operations joins bounded records client-side;
   detail reads can legitimately span a concurrent update.

These gaps are surfaced as unknown/stale/partial data, not filled with fabricated
health. No endpoints or mutation authorization were expanded to make the UI look live.

## Local review without production

For a real local database and genuine exercise evidence, use the disposable procedure
in [sre_milestone1.md](sre_milestone1.md). Run any admin exercise commands only from that
trusted local terminal. Do not transfer its admin key to the frontend.

With that local backend running, use a separate PowerShell terminal:

~~~powershell
cd frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
# Set only the local backend's public/demo read key:
$env:VITE_API_READ_KEY = "your-local-public-read-key"
npm.cmd run dev -- --host 127.0.0.1 --port 5192 --strictPort
~~~

Open http://127.0.0.1:5192/#/operations and #/incidents. An enabled backend with no
records shows empty/unknown states. A disabled backend shows an explicit disabled
notice. Real exercise evidence will normally become stale after 15 seconds; refresh
does not manufacture new observations.

Verification commands, from frontend:

~~~powershell
npm.cmd test
npm.cmd run typecheck
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_API_READ_KEY = "ci-public-demo-key"
npm.cmd run build
~~~

Builds do not call the API. New tests cover GET-only integration, actual response
shapes, malformed/unauthorized/disabled responses, status ageing, recovery proof,
partial failures, filtering/pagination, deep links, browser-history events, late
responses, and preserved legacy navigation.

A connected browser was unavailable during the initial implementation session.
The repository owner subsequently completed local visual review and confirmed the
recorded incident renders correctly; see the owner-reported verification below.

## Validation results

- Frontend: 100 tests passed across 10 files (50 preserved and 50 added).
- Explicit TypeScript typecheck: passed.
- Production Vite build: passed with a local API origin and a fake public read value;
  no backend or production requests are made by the build.
- Backend unit regressions: 295 passed. Backend code/schema are unchanged, so the
  PostgreSQL integration suite was not rerun for this frontend-only milestone.
- Offline deployment configuration validation and git diff --check: passed.
- The first full frontend run had one ambiguous RESOLVED text selector, because the
  service card and incident table both correctly display the status. The assertion
  was scoped to the service card; no product behavior or expectation was bypassed.
- Remaining warnings: the existing Vite bundle-size warning and backend
  Starlette/AnyIO deprecation. The initial browser connection was unavailable; the
  subsequent owner-reported local verification is recorded below.
- Source review found no runtime fixture imports, SRE mutation controls, admin
  credential handling, or browser storage. Build artifacts/dependencies remain ignored.
- No production changes, deployments, pushes, or merges were performed. These
  implementation results preceded the separately requested final local commit.

## Local verification reported by the owner

Before the final Milestone 2 commit, the repository owner confirmed visual review
against the isolated local PostgreSQL database and successful completion of one
real controlled application-dependency HTTP 503 exercise:

- The incident reached RESOLVED.
- The recovery attempt reached SUCCEEDED with verified recovery.
- Ten actual HTTP observations were recorded: one baseline 200, six 503 responses,
  and three healthy verification 200 responses.
- Live Operations, Incident Center and Incident Details rendered correctly; the
  frontend distinguished stale current evidence from historically verified recovery.

This records the owner's reported verification, rather than claiming a separate
agent-run exercise. No production access or service/credential changes are part
of the final frontend review and commit.

## File inventory

Created:

- `docs/sre_dashboard.md`
- `frontend/src/sre/IncidentCenter.tsx`
- `frontend/src/sre/IncidentDetails.tsx`
- `frontend/src/sre/IncidentTable.tsx`
- `frontend/src/sre/LiveOperations.tsx`
- `frontend/src/sre/contracts.ts`
- `frontend/src/sre/shared.tsx`
- `frontend/src/sre/sre.scss`
- `frontend/src/sre/status.ts`
- `frontend/src/sre/types.ts`
- `frontend/src/test/sre-api.test.ts`
- `frontend/src/test/sre-pages.test.tsx`
- `frontend/src/test/sre-status.test.ts`
- `frontend/src/test/sre.fixtures.ts`

Modified:

- `frontend/README.md`
- `frontend/src/App.tsx`
- `frontend/src/AppHeader.tsx`
- `frontend/src/api.ts`
- `frontend/src/main.tsx`
- `frontend/src/styles.scss`
- `frontend/src/test/AppHeader.test.tsx`
- `frontend/src/test/setup.ts`
