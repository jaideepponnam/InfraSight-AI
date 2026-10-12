# Phase 3: source adapters and transactional micro-batch ETL

## Scope

This phase adds a manually invoked one-cycle CLI/service. It deliberately creates no scheduler, analytics views, dashboard, AI, domain APIs, or migration. A later worker can invoke ETLPipeline.run_cycle periodically.

## Source contract

TelemetrySource exposes source_id, provider, historical/cursor capabilities, available_from, completed_until(now), and extract_batch(window, cursor, batch_size). Batches contain event envelopes, a next cursor, and a completion flag. The envelope provides stable source_event_id and canonical_observed_at independently of its JSON payload. Windows are half-open [start,end), with timezone-aware UTC boundaries. A source returns only bounded batches; empty/non-progressing nonterminal batches fail rather than loop indefinitely.

Source IDs identify stable collectors/accounts, not individual runs. The simulator uses simulated-cloud; the optional host adapter uses host-local. New provider adapters reuse the validation/loader/orchestrator and must translate provider-specific status/unit conventions into this contract.

## Simulator

The default fleet has 75 stable servers across us-south, us-east, and eu-de and dev/staging/prod. Seven profiles provide healthy behavior, CPU spikes, sustained memory pressure, intermittent failure/recovery, expensive underutilization, high network traffic, and growing demand. Regional price multipliers and alternating daily price factors create regional and day-over-day cost differences. Seed, server identity, and observation time determine values; extraction order/batch size do not.

Intervals are UTC-aligned within each day. The last interval is shortened at midnight if the configured duration does not divide a day. Extraction selection uses canonical interval metadata BEFORE any malformed payload mutations. Malformed observed_at values therefore remain in the correct source window and reach raw persistence and rejection validation.

Default malformed rate is 1%. A seeded periodic schedule selects approximately the configured fraction (effective period = round(1/rate), minimum 10); rate zero disables mutations. The five cases are CPU >100, missing external ID, invalid environment, invalid timestamp, and negative cost. Source event identity survives every mutation. Changing seed/fleet/interval settings under an existing source ID is not an event correction; use a new stable collector ID for incompatible scenario changes.

## Host measurements

psutil is an optional extra. Live capture primes CPU measurement, observes a bounded sampling duration, and reads memory, disk, network counters, and boot time. Network Mbps uses counter differences divided by actual monotonic elapsed seconds. Counter resets and inaccessible optional measurements become NULL. Cost/currency remain NULL. Host interval_seconds is the whole measured elapsed seconds; network rate uses the precise duration. Host samples are current observations, never manufactured historical samples.

The CLI captures a host event BEFORE selecting the cycle window. A bounded in-memory buffer allows repeated calls on a long-lived adapter; a fresh CLI invocation captures a new event. Historical host replay uses StoredHostTelemetrySource over already-preserved host raw events. Its time filtering relies on the fixed-width UTC timestamp format written by the host adapter, without casting arbitrary malformed provider payloads.

CPU, memory, and storage remain required by Phase 2. If unavailable, the raw host event is saved and rejected. The adapter never substitutes a fake zero. Host collection is disabled by default; HOST_ENABLED and the installed host extra are required for CLI live capture.

## Validation and policy

Pydantic validates finite values, percent ranges, source/server/region identity, enums, timezone-aware timestamps, cost/currency pairing, positive intervals, numeric precision, and completed-window membership. Permitted labels are normalized and identity strings trimmed. Structured errors retain field names and codes, excluding raw inputs/exception contexts.

Health policy v1:

- CRITICAL: FAILED, CPU >=90%, or memory >=90%.
- WARNING: otherwise DEGRADED, CPU >=80%, or memory >=80%.
- HEALTHY: otherwise.

Storage is not part of this policy. STOPPED alone is HEALTHY under the approved initial rule; server_status remains separately visible. Threshold changes require an explicit policy change and boundary tests.

## Source ownership

A dedicated physical PostgreSQL connection acquires pg_try_advisory_lock BEFORE creating/starting a run. It uses a SESSION-level lock, never pg_advisory_xact_lock. A NullPool engine keeps this connection out of the application's shared connection pool. It stays open across every batch commit and the final transaction. Ownership is checked before processing and before transaction completion using backend identity and pg_locks.

The signed 64-bit key is BLAKE2b(namespace + source_id) with an eight-byte digest, decoded in big-endian signed form. It is stable across processes and Python hash seeds. Extremely unlikely collisions conservatively serialize unrelated sources; SQL identities still keep their data separate.

Finally blocks explicitly unlock and physically close the dedicated session on every exit. On an unlock error the connection is invalidated/discarded. Closing the session releases PostgreSQL session locks. A busy source produces a clear error and creates no competing ETL run. Different source IDs can run independently.

## Batch transaction

For each batch, one database transaction:

1. Preserves original raw events with source/event conflict handling.
2. Reads the canonical stored payloads for all batch identities.
3. Validates each extracted attempt against that stored original.
4. Writes rejection evidence for invalid attempts.
5. Batch upserts regions and source-scoped server inventory.
6. Deduplicates candidates and inserts metrics with conflict handling.
7. Writes cumulative run counters and heartbeat.
8. Commits.

No per-event transactions or inventory lookups are used. Batch size defaults to 500 and is limited to 1000 to remain safely below PostgreSQL's bound-parameter limit for bulk metric inserts. Original raw payloads are never overwritten when an event ID repeats. Inventory first_seen_at moves earlier and last_seen_at moves later; older replay never replaces newer names/environments/regions.

Uniqueness constraints protect both repeated source events and repeated server/timestamp observations. Duplicate valid attempts count as accepted and duplicated; malformed duplicate attempts count as rejected. The rejection table has one evidence row per run/raw pair, so repeated invalid events in a batch may have fewer evidence rows than the rejected-attempt count.

## Progress and finalization

Timestamp adapters ignore previously completed page offsets when beginning a new/replayed window. Cursor values are still recorded for audit; the interface permits future cursor-based adapters. Incremental runs begin at committed watermark minus configured overlap, or a bounded initial lookback. Extraction end includes only completed intervals and is capped by ETL_MAX_WINDOW_SECONDS. Configuration requires room for overlap plus a new interval, preventing stalled catch-up windows. Explicit simulator window boundaries must align to source intervals.

Each successful batch commits independently. Only the final transaction marks the run SUCCEEDED and updates ingestion_state. Watermarks/cursors never regress during older replay; last_successful_run_id may identify that replay attempt. Rejected events count as processed and do not block the watermark.

On failure, the active batch rolls back, earlier batches remain durable, and committed progress stays unchanged. A later retry re-extracts safely. Finalization rollback is tested. If a final commit already succeeded but its acknowledgement/later logging fails, recovery checks persisted status and never rewrites that success as FAILED.

## Counters and errors

For successful runs: extracted = accepted + rejected; accepted = inserted + duplicated. Counters are updated together in the same transaction as their batch. Failed results report durable counters read from the database when reachable.

Only TransientSourceError is retried with bounded exponential backoff plus jitter at the SAME window/cursor. Permanent extraction failures and database failures fail the cycle. Database exceptions are not indiscriminately retried. Error records/logs contain sanitized categories and exception types, not raw provider/connection messages. A database outage can prevent failure auditing; that limitation is logged honestly. Hard process termination may leave RUNNING audit rows; abandoned-job recovery belongs to the future worker.

## Configuration and execution

See .env.example for all settings. TELEMETRY_INTERVAL_SECONDS controls simulator generation cadence; ETL_BATCH_SIZE controls transaction size, and overlap/lookback/max-window settings control extraction volume. Invocation cadence will belong to the later worker. Exit code 0 means a successful cycle; 1 means failure or invalid configuration/source selection. No database schema changes occur during ETL execution.

## Verification

Unit tests cover deterministic behavior, malformed metadata, policy boundaries, bounded retries, configuration limits, and optional host collection. PostgreSQL tests use a separate disposable ETL database because the pipeline intentionally commits batches. They cover replay, duplicate observation identities, raw evidence preservation, rejected attempts, partial failures, batch/finalization rollback, watermark/inventory monotonicity, source isolation, and session locks across commits. Existing schema/migration tests use their own separate disposable database.
