# Phase 4 measured query plans

## Method

PostgreSQL 16 in the InfraSight-AI Docker environment. A disposable database was migrated to 0002 and populated through Phase 3 ETL with 75 servers and 9,000 clean 30-second observations spanning one hour. ANALYZE updated statistics. Each statement ran once to warm the fixture, then EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) captured the second execution. scripts/phase4_explain.py reproduces the workbench and saves full plans in the ignored .uv-cache directory.

These are measured warm-fixture SQL execution times, not HTTP latency, production SLAs, or predictions for millions of observations.

| Query | Execution ms | Planning ms | Output rows | Shared buffer hits |
|---|---:|---:|---:|---:|
| Latest row: lateral | 1.222 | 0.671 | 75 | 881 |
| Latest row: DISTINCT ON | 12.113 | 0.383 | 75 | 190 |
| High CPU: last five minutes | 2.154 | 0.505 | 11 | 981 |
| Cost ranking: one hour | 45.155 | 1.519 | 20 | 18,170 |
| Daily weighted summary | 118.383 | 2.222 | 9 | 9,145 |

## Decisions from actual plans

### Latest row

Lateral lookup performed bounded index probes using ix_infrastructure_metrics_server_observed_desc with LIMIT 1. DISTINCT ON read/sorted 9,000 rows using quicksort before returning 75 rows. Both returned identical server/timestamp/CPU tuples. The lateral strategy was approximately ten times faster for this fleet/history shape, so it is used by the view and historical query.

The historical query currently goes through the approved inventory/fact views; its plan includes both an inventory-view latest probe and a historical probe. This keeps the reader contract consistent and remained inexpensive in this measurement. Large-fleet changes should be measured rather than assumed.

### High CPU

The planner used per-server bitmap index/heap scans on the existing server/time index, retrieving ten observations per server (750 total) for the five-minute range. The source inventory has only 75 rows, so sequential scans of inventory/three-region lookup tables were reasonable. A CPU-only index was not justified: CPU varies frequently, and time/server predicates already bound the scan.

### Cost ranking

The existing server/time index selected the hour's relevant measurements. The query aggregated and unioned coverage ranges, then used a top-N heapsort for ranked results. Reading/aggregating the contributing facts is necessary; another index does not precompute interval allocations or coverage. At 45 ms for this bounded workload, additional write/storage overhead was not justified.

### Daily summary

The plan used existing server/region primary keys, memoized region lookup, the existing metric server/time index, and per-observation UTC day segmentation. It produced nine region/environment cohorts in about 118 ms. The remaining work is arithmetic, segmentation, and aggregation over actual facts, not an unindexed point lookup. This measurement did not justify a materialized view or another index.

## Existing-index assessment

- Server/time descending: actually used by latest, breach, cost, and daily queries.
- Observation-time/server: remains useful for broader time-first workloads; this source-scoped fixture chose server/time access instead. Its absence from these particular plans is not proof it is globally unnecessary.
- Source/external identity and region/environment: existing inventory support; tiny inventory scans are often cheaper in this fixture.
- No indexes were added or removed. Domain-model metadata remains unchanged.

A new index would need a demonstrated predicate/order bottleneck and a measurable benefit against its additional insertion cost, disk usage, and cache pressure. No such case emerged in these measurements. Re-profile as retention, source count, or fleet size grows; normal views remain the current implementation.
