# Phase 3 demo: 75 servers through PostgreSQL ETL

## Preparation

Run from the repository root in Windows PowerShell. PostgreSQL must be the InfraSight-AI container bound to 127.0.0.1:55432; existing Windows PostgreSQL services on 5432/5433 are untouched.

    .\.venv\Scripts\uv.exe sync --locked --python .\.venv\Scripts\python.exe --cache-dir .\.uv-cache
    docker compose up -d --wait postgres
    .\.venv\Scripts\alembic.exe upgrade head

Configure .env with local credentials as described in README. The schema remains revision 0001.

## Exact reproducible demonstration

    .\.venv\Scripts\infrasight-etl.exe demo --start 2026-10-11T19:30:00Z

This command executes three genuine ETL cycles against PostgreSQL:

1. Initial window: [19:30,19:32) UTC, 75 servers, 30-second intervals, batches of 100.
2. Identical-window replay: same source/events, new run audit.
3. Incremental cycle as of 19:33 UTC: watermark minus 60-second overlap gives [19:31,19:33).

The first two cycles each extract 300 events: 297 valid and three rejected. Initial ingestion inserts 297 metrics; replay inserts zero and counts 297 duplicates. First-run invalid cases include a missing server ID, invalid environment, and an intentionally malformed timestamp that was still extracted through canonical interval metadata.

The command prints structured logs plus a report with all run IDs/counters, database totals, committed progress, rejected raw payloads/errors, and six observations for a CPU-spike server. These are database results, not mocked summaries.

The demo requires an unused source_id so first-ingestion counts remain meaningful. It never deletes existing rows or resets watermarks. To repeat the full initial-ingestion story after inspection, use a new collector identity:

    .\.venv\Scripts\infrasight-etl.exe demo --start 2026-10-11T19:30:00Z --source-id simulated-cloud-demo-2

Omit --start for a completed window immediately before the current time. The fixed historical example is reproducible; current runs demonstrate freshness. A later worker will automate invocation.

## Continue producing fresh telemetry

    .\.venv\Scripts\infrasight-etl.exe run --source simulator

Each invocation processes the next bounded window with overlap. After a long gap, repeat the command to catch up through capped windows. Live simulator values change with observation time while retaining stable replay identities.

## Explicit replay

    .\.venv\Scripts\infrasight-etl.exe replay --source simulator --start 2026-10-11T19:30:00Z --end 2026-10-11T19:32:00Z

Replay must not change raw/metric totals or regress the current watermark. It creates another audited run and rejection attempt evidence.

## Read-only PostgreSQL inspection

Open a shell on the project container:

    docker compose exec postgres psql -U infrasight -d infrasight

Inspect run statistics:

    SELECT id, status, requested_window_start, requested_window_end,
           records_extracted, records_accepted, records_inserted,
           records_duplicated, records_rejected, watermark_before, watermark_after
    FROM etl_runs WHERE source_id = 'simulated-cloud' ORDER BY requested_at;

Inspect progress:

    SELECT source_id, watermark, cursor, last_successful_run_id
    FROM ingestion_state WHERE source_id = 'simulated-cloud';

Inspect rejection evidence, including the malformed timestamp:

    SELECT r.source_event_id, r.payload->>'observed_at' AS raw_timestamp,
           q.validation_errors
    FROM data_quality_rejections q JOIN raw_telemetry r ON r.id = q.raw_telemetry_id
    WHERE r.source_id = 'simulated-cloud' ORDER BY q.rejected_at;

Inspect changing server history:

    SELECT s.external_server_id, m.observed_at, m.cpu_usage_percent,
           m.memory_usage_percent, m.resource_health, m.estimated_cost
    FROM infrastructure_metrics m JOIN servers s ON s.id = m.server_id
    WHERE s.source_id = 'simulated-cloud' AND s.external_server_id = 'sim-002'
    ORDER BY m.observed_at;

## Optional real host observation

    .\.venv\Scripts\uv.exe sync --locked --extra host --python .\.venv\Scripts\python.exe --cache-dir .\.uv-cache
    $env:HOST_ENABLED = "true"
    .\.venv\Scripts\infrasight-etl.exe run --source host
    Remove-Item Env:HOST_ENABLED

Host data is a distinct source, with NULL costs and unsupported optional measurements. Required unavailable measurements become audited rejections. Replay an already-captured host window with --source host and explicit --start/--end; this reads stored raw events rather than sampling old timestamps.

## Run checks

    .\.venv\Scripts\python.exe -m pytest -q tests/unit
    $env:TEST_DATABASE_URL = (Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
    .\.venv\Scripts\python.exe -m pytest -q tests/integration/test_etl_pipeline.py
    .\.venv\Scripts\python.exe -m pytest -q
    Remove-Item Env:TEST_DATABASE_URL
    .\.venv\Scripts\ruff.exe check .
    .\.venv\Scripts\ruff.exe format --check .

Tests create/drop only uniquely named disposable databases on the configured container. The actual demo preserves its records for inspection.

## Recorded verification result

Executed against the InfraSight-AI container on localhost:55432 using the fixed UTC window above. All three runs SUCCEEDED.

| Cycle | Run ID | Extracted | Accepted | Inserted | Duplicated | Rejected | Watermark after |
|---|---|---:|---:|---:|---:|---:|---|
| Initial | 9908484f-7235-4077-bcda-52c6cf6def1a | 300 | 297 | 297 | 0 | 3 | 2026-10-11T19:32:00Z |
| Replay | df2286ab-25dd-42eb-967d-7b655506cff8 | 300 | 297 | 0 | 297 | 3 | 2026-10-11T19:32:00Z |
| Incremental | 3f629aaf-6ea3-4878-94ff-d8a7fdc450b3 | 300 | 297 | 149 | 148 | 3 | 2026-10-11T19:33:00Z |

Final stored totals: 75 servers, 450 unique raw events, 446 unique metrics, and nine rejection-attempt rows. There are four distinct rejected raw events; replay and overlap explain repeated rejection evidence.

The original three rejected events were sim-019 at 19:30:30 (missing external_server_id), sim-044 at 19:31:00 (invalid environment), and sim-069 at 19:31:30 (payload observed_at = invalid-timestamp). The last case proves canonical interval selection preserved a malformed timestamp event for rejection auditing.

Server sim-002 CPU history: 93.28%, 92.58%, 91.97%, 91.49%, 38.43%, 38.03% across six 30-second observations. Derived health changed from CRITICAL to HEALTHY at 19:32 UTC.

Verification: 54 unit tests passed; 17 PostgreSQL ETL integration tests passed; complete suite 138 passed. Ruff lint and formatting passed. One pre-existing Starlette/AnyIO deprecation warning remains. An optional real host sample validated successfully with cost NULL; it was not inserted into the 75-server simulator demo.
