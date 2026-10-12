# InfraSight-AI

Cloud infrastructure intelligence platform: telemetry extraction → validated ETL → PostgreSQL analytics → controlled AI tools → operations dashboard.

## Current milestone: Phase 2

Implemented: installable Python 3.11 backend, validated environment settings, structured JSON logging, FastAPI health endpoints, pooled PostgreSQL sessions, and Alembic foundation.

Phase 2 adds seven domain tables and Alembic revision 0001. ETL, analytics views, AI, and the dashboard remain future phases. No automatic Git commits are made.

## Local development (Windows PowerShell)

Prerequisites: Python 3.11 and Docker Desktop using Linux containers. Run commands from the repository root. The existing virtual environment can be reused.

1. Create the environment if needed and install the dependency manager:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install uv

2. Install exactly the locked dependencies (no shell activation required):

    .\.venv\Scripts\uv.exe sync --locked --python .\.venv\Scripts\python.exe --cache-dir .\.uv-cache

3. Create local configuration:

    Copy-Item .env.example .env

   Replace POSTGRES_PASSWORD and the password in DATABASE_URL with the same local secret. URL-encode special characters in the URL password. Never commit .env. PostgreSQL initialization credentials apply only when the persistent volume is first created; changing .env alone does not rotate an existing database password.

4. Start Docker Desktop, then PostgreSQL. InfraSight-AI uses host port 55432, leaving the existing Windows PostgreSQL services on ports 5432 and 5433 untouched. Set DATABASE_URL to postgresql+psycopg://infrasight:<URL-encoded-password>@localhost:55432/infrasight for FastAPI running directly from Windows/VS Code.

    docker compose up -d --wait postgres

5. Verify Alembic connectivity and start FastAPI from Windows/VS Code:

    .\.venv\Scripts\alembic.exe upgrade head
    .\.venv\Scripts\alembic.exe current
    .\.venv\Scripts\uvicorn.exe infrasight.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log

   Use the factory entry point in VS Code too. Disabling Uvicorn access logs avoids duplicate request logging; application logs already contain request IDs and timing.

Open http://127.0.0.1:8000/docs for API documentation.

- GET /health returns 200 when the API process is alive, even if PostgreSQL is unavailable.
- GET /health/ready performs SELECT 1 and returns 200 or a sanitized 503 response.
- Both return an X-Request-ID header. Unexpected failures return a sanitized 500 response with the ID.

## Configuration

.env.example lists all Phase 1 settings. DATABASE_URL is required. Only the postgresql+psycopg driver is accepted. Pool limits, connection timeout, pool checkout timeout, and PostgreSQL statement timeout are bounded and configurable. Settings redact the database URL in representations and validation error strings.

A SQLAlchemy engine is created during application lifespan and disposed at shutdown. Sessions close after each request and roll back uncommitted work. Future write services must explicitly commit transactions. No implicit schema creation occurs on startup.

## Database exposure and deployment

Compose binds PostgreSQL to **127.0.0.1:55432:5432** for the Windows API process. It is not bound to a public host interface. Remove the ports mapping in production and use private networking. A future containerized API will use postgres:5432 rather than localhost:55432; the container itself continues listening on port 5432. The current Compose database user is a local-development bootstrap owner; production least-privilege roles will be introduced with domain migrations.

The persistent volume survives docker compose down. Do not use down -v unless intentionally deleting local database data.

Authentication and production ingress are later milestones. Run the current API on localhost.

## Checks

    .\.venv\Scripts\ruff.exe check .
    .\.venv\Scripts\ruff.exe format --check .
    .\.venv\Scripts\python.exe -m pytest -q

Database tests skip unless TEST_DATABASE_URL is explicitly set. After configuring .env and starting PostgreSQL:

    $env:TEST_DATABASE_URL = (Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    .\.venv\Scripts\python.exe -m pytest -q -m integration
    .\.venv\Scripts\alembic.exe current
    Remove-Item Env:TEST_DATABASE_URL

Integration tests check connectivity, transaction cleanup, readiness, schema constraints, deduplication, restricted deletes, and migration downgrade/re-upgrade. New schema tests automatically create and remove a uniquely named disposable database on the configured container; the local bootstrap account needs CREATEDB permission. They never downgrade the application database. Alembic current should report 0001 (head). Run alembic check to verify metadata consistency. See [the data dictionary](docs/data_dictionary.md) for all columns, constraints, indexes, and source_id conventions.

## Layout

- src/infrasight/api: HTTP routes and health schemas.
- src/infrasight/db: engine, session dependency, and seven domain models.
- src/infrasight/config.py: environment settings.
- src/infrasight/logging.py: structured logging.
- migrations: Alembic environment and revision template.
- tests/unit and tests/integration: foundation checks.

## Design rationale

A modular monolith keeps future ingestion, analytics, and AI business logic together while allowing separate API and worker processes. PostgreSQL provides a durable relational analytics store. Explicit migrations avoid hidden startup schema changes. Separate liveness/readiness endpoints distinguish process availability from dependency availability. Bounded pools/timeouts and secret-safe structured logs provide operational foundations before features are added.
