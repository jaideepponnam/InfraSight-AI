# InfraSight AI

### AI-Powered Cloud Infrastructure Intelligence

InfraSight AI transforms raw infrastructure telemetry into **trusted analytics and evidence-grounded AI insights**.

---

## The Flow

```text
     CLOUD INFRASTRUCTURE
              │
              ▼
      SERVER TELEMETRY
   CPU • Memory • Storage
      Health • Cost • Region
              │
              ▼
      ┌───────────────┐
      │  RAW INGESTION │
      └───────┬───────┘
              ▼
      ┌───────────────┐
      │   VALIDATION   │
      │ Quality Checks │
      └───────┬───────┘
              ▼
      ┌───────────────┐
      │ TRANSFORMATION │
      │ Health + Cost  │
      └───────┬───────┘
              ▼
      ┌───────────────┐
      │  POSTGRESQL    │
      │ Analytics Data │
      └───────┬───────┘
              │
        ┌─────┴─────┐
        ▼           ▼
   ┌─────────┐  ┌────────────┐
   │ FastAPI │  │ AI Analyst │
   └────┬────┘  └─────┬──────┘
        │             │
        └──────┬──────┘
               ▼
     INFRASTRUCTURE INTELLIGENCE
```

---

## What Can It Tell You?

**Infrastructure Health**  
Which servers are healthy, warning, critical, stale, or under pressure?

**Cost Intelligence**  
Which infrastructure is expensive but underutilized?

**Operational Analytics**  
Which regions or servers require attention?

**AI Analysis**  
Ask infrastructure questions in natural language and receive answers grounded in real analytics.

---

## AI Without Direct Database Access

```text
        USER QUESTION
              │
              ▼
         AI HARNESS
              │
              ▼
   APPROVED ANALYTICS TOOL
              │
              ▼
      ANALYTICS SERVICE
              │
              ▼
         POSTGRESQL
              │
              ▼
     STRUCTURED EVIDENCE
              │
              ▼
         AI ANSWER
```

The AI does **not** execute arbitrary SQL or receive database credentials.

---

## Built With

**Python · FastAPI · PostgreSQL · SQLAlchemy · React · TypeScript · Carbon · Docker · LLM Tool Calling**

---

## Demo Environment

The infrastructure fleet is simulated so the complete system can run without a commercial cloud account.

**Only the telemetry source is simulated.**

The ETL pipeline, validation, PostgreSQL storage, analytics, REST APIs, AI tool execution, and frontend run through the real application stack.

---

### The Idea

**Raw Infrastructure Data → Trusted Analytics → Evidence-Grounded AI**

> Reliable data first. AI second.

## Public deployment

Render static frontend + Render FastAPI service + Neon direct PostgreSQL + Cloudflare DNS. See [the deployment runbook](docs/deployment.md) for initialization, environment boundaries, CI, and exact domain configuration. Deployment is manual; no startup seeding is performed.

## InfraSight AI 2.0: SRE Milestone 1

The feature branch adds an admin-only incident engine with actual HTTP probes,
PostgreSQL evidence, deduplicated incidents, acknowledgement, and verified recovery.
Its first scenario is a controlled application-dependency HTTP 503 failure, not a
storage outage. It runs on demand without a background worker. Existing telemetry,
analytics, Scout and frontend features remain available.

SRE is disabled by default. Milestone 1 itself includes no SRE pages or Scout integration.
See [the Milestone 1 runbook](docs/sre_milestone1.md) for the API, limitations, and exact
local review instructions using a disposable database. Production deployment and
migration require separate approval.

## InfraSight AI 2.0: Scout incident intelligence (Milestone 3)

Scout now investigates persisted sandbox SRE incidents through its existing read-only
tool harness. The existing dashboard's **Investigate with Scout** link populates an
incident context without submitting a query. Evidence-backed summaries distinguish
historical recovery verification from current observation freshness. Analytics remains
available when SRE is disabled. See [the Milestone 3 guide](docs/scout_incidents.md) for
contracts, safeguards, limitations and disposable local validation instructions, and
[the dashboard guide](docs/sre_dashboard.md) for Milestone 2.
