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
