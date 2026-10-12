# Phase 4 analytics contract

## Architecture

PostgreSQL normal views expose curated facts. Parameterized repository queries apply runtime windows, reference times, freshness, currency, and policy thresholds. AnalyticsService validates inputs and returns a shared result envelope. Future FastAPI, AI tools, and the dashboard will call this same service.

No public view reads current_setting or requires set_config. No query parameter is persisted in a pooled connection. Services use bound values; the only dynamic resource ordering is an internal allowlist for CPU or memory. Comparisons use one repeatable-read snapshot. Output timestamps are normalized to UTC and Decimal monetary values serialize as strings without precision loss.

## Business definitions

| Term | Meaning |
|---|---|
| LATEST | Greatest observed_at among intervals completed by the reference time; never ingestion order |
| CURRENT | Latest completed interval ended within the requested freshness threshold, inclusive |
| STALE | An observation exists, but completion age exceeds that threshold |
| NO_DATA | No completed observation exists at the reference time |
| TODAY | UTC calendar day containing the explicit reference time |
| HIGH CPU | CPU strictly greater than the requested threshold; default >80% |
| DAILY COST | Sum of estimated interval costs allocated to a UTC day, separately by currency |
| REPORTING SERVER | Distinct server contributing measurements to the period; current reporting additionally requires freshness |
| UNDERUTILIZED | Optimization candidate meeting utilization, samples, interval coverage, freshness, health, and selected-currency price rules |
| CPU PRESSURE | Fraction of contributing observations above the threshold, with sufficient samples and coverage |
| COST INCREASE | Positive same-currency difference between comparable, sufficiently covered periods |

The ETL health rule remains >=80% WARNING and >=90% CRITICAL for CPU/memory (or DEGRADED/FAILED status). A CPU reading exactly 80% is WARNING but does not breach an above-80 question. These are deliberately different definitions.

## Shared assumptions and limitations

- Current inventory names, regions, and environments label historical facts; this is not historical inventory versioning.
- as_of is an event-time assessment, not reconstruction of what was stored/known at that past instant. Late arrivals may revise historical answers.
- Interval start is observed_at; interval end is observed_at + interval_seconds. Runtime queries exclude intervals not completed by as_of.
- Missing optional measurements/cost are NULL, never fake zero. SUM of unknown costs stays NULL.
- Cost is an interval estimate, not a repeatedly summed hourly rate. Partial-window/day allocation assumes uniform cost within that interval.
- Allocation uses cumulative NUMERIC differences so adjacent day segments reconcile to the stored interval amount. Rounding belongs to final presentation.
- Daily utilization is weighted by observed duration; missing intervals do not become zero utilization. Current fleet/regional utilization is an equal-server average among fresh reporters, not absolute capacity consumption.
- Counts of reporting servers cannot be summed blindly across days or currencies. Daily observations crossing midnight contribute to both days.
- Interval union coverage does not inflate when intervals overlap. Overlap is exposed as an anomaly; pressure/optimization candidates exclude it, and monetary reports warn rather than silently discard potentially meaningful records.
- The SQL schema guarantees unique observation starts, not interval non-overlap. Phase 3 adapters produce non-overlapping intervals; future providers must preserve that contract.
- Monetary comparisons/rankings require one currency. Fleet cost reports separate currencies; there is no FX conversion.

## analytics.latest_server_metrics

Purpose: inventory-preserving latest telemetry dataset.

Important columns: server_id/external_server_id/name, source_id, provider, region identity/display name, environment, first/last seen, metric_id, observed_at, interval_end, resource percentages, network Mbps, uptime seconds, status, recorded health, interval estimated cost/currency/duration, reference_time, observation_age_seconds, completion_age_seconds, freshness_threshold_seconds, is_current, freshness.

Business meaning: one row per inventory server. A LEFT LATERAL bounded descending index lookup selects the latest completed observation. The view uses statement_timestamp() and a visible 120-second default. NO_DATA rows keep inventory fields with NULL measurements.

Example question: What is the latest known CPU/status for each server?

Assumptions: completed intervals are the available telemetry evidence; ties cannot occur because server/observed_at is unique.

Limitations: latest does not imply current; custom as_of/thresholds belong to the service, not this view. Cost here represents only that observation interval.

## analytics.server_health_summary

Purpose: safe default wall-clock health.

Important columns: server/region/source/environment labels, latest CPU/memory/storage/status, observed_at/interval_end, recorded_resource_health, effective_health, freshness, completion age, visible threshold/reference.

Business meaning: effective_health is NO_DATA without a sample, STALE when expired, otherwise the ETL-recorded health. Old HEALTHY records cannot silently count as currently healthy.

Example question: How many servers are currently healthy, warning, critical, stale, or missing telemetry?

Assumptions: same 120-second visible view default; runtime policy overrides use bound service parameters.

Limitations: health is operational telemetry evidence, not an availability/SLA guarantee. STOPPED alone remains HEALTHY under the approved ETL policy unless resource thresholds apply; status remains visible.

## analytics.high_resource_usage

Purpose: reusable validated observation facts for threshold and window queries.

Important columns: metric/server identities and approved inventory labels; observation/interval boundaries; CPU/memory/storage/network/uptime; status/health; estimated interval cost/currency/duration.

Business meaning: every cleaned metric, without a hardcoded CPU threshold. Repository queries bound observation windows, completion reference, thresholds, grouping, and result limits.

Example question: Which servers had CPU above 80% in the selected UTC window?

Assumptions: cleaned metrics and database uniqueness are authoritative. Payloads and ETL/rejection errors are excluded.

Limitations: the view itself is a dataset, not a threshold-filtered answer. No raw payload/provenance IDs are exposed except the safe metric identifier.

## analytics.daily_infrastructure_summary

Purpose: daily infrastructure activity, weighted utilization, and priced evidence.

Grain: UTC day/source/provider/region/environment/currency cohort.

Important columns: reporting_server_count, observation_count, observation_seconds, average CPU/memory/storage/network, warning/critical observations, estimated_cost, priced_observation_count, priced_observation_seconds.

Business meaning: averages weight each day's interval segment by duration. Optional network averages exclude missing network values from both numerator and denominator. Cost is that day's allocated interval amount. The NULL currency cohort preserves unpriced telemetry.

Example question: What utilization, health activity, and estimated costs did a region report yesterday?

Assumptions: segments clipped to explicit UTC boundaries; regular simulator/host intervals do not overlap.

Limitations: observation_seconds is summed evidence, not deduplicated fleet coverage. Use service interval-union coverage for eligibility and anomaly checks. Currency-cohort counts are not necessarily additive distinct fleet counts.

## analytics.daily_cloud_cost_summary

Purpose: trustworthy retained daily interval-cost ledger.

Grain: UTC day/server/source/provider/region/environment/currency.

Important columns: estimated_cost, observation_count, priced_observation_count, observation_seconds, inventory labels.

Business meaning: costs are allocated across midnight and summed as NUMERIC. Replaying ETL creates no duplicate metric facts, so it cannot inflate this ledger.

Example question: Which server accumulated the most estimated USD cost on a selected UTC day?

Assumptions: uniform cost within an interval; current inventory labels are used.

Limitations: these are estimates, not provider invoices. Unknown costs remain NULL. Selected/as_of windows and overlap caveats are handled by the service.

## analytics.region_usage_summary

Purpose: inspectable default current regional resource/health snapshot.

Grain: source/provider/region/environment/latest-observation currency cohort; each inventory server belongs to one current cohort, including NULL.

Important columns: inventory/reporting counts, fresh-server average CPU/memory/storage, healthy/warning/critical/stale/no-data counts, latest observation time, oldest completion age, visible reference/default threshold, latest_interval_estimated_cost, priced_current_server_count, cost_min/max_interval_seconds, cost_basis.

Business meaning: resource means and recorded health counts include fresh reporters only. Cost is explicitly SUM_OF_FRESH_LATEST_INTERVALS, with represented interval durations visible. It is not today's cost or an hourly rate. Selected-period regional cost is obtained from the cost dataset/service, separately from these counts.

Example question: Which regions have the most currently critical reporting servers?

Assumptions: view defaults use actual query clock and 120 seconds; custom historical regional health is a service query.

Limitations: percentages are utilization, not absolute capacity. Do not compare snapshot cost as a common-duration bill when cost interval durations differ. Do not substitute it for daily/window totals.

## Private helper: analytics._daily_metric_intervals

Splits metric intervals at UTC midnight using integer day offsets and explicit UTC conversion. Exposes clipped segment boundaries, duration, measurements, and allocated cost for the two daily views. It is not granted directly to a future reader role.

## Parameterized service queries

Scope: explicit as_of, freshness_seconds, optional source/region/environment, limit. Window: start < end <= as_of, at most seven days. Limits are 1..100; configuration can tighten them. Service factory defaults freshness from ANALYTICS_FRESHNESS_SECONDS; view defaults remain visible SQL constants.

Methods: health, fleet_totals, regional_health, critical_servers, top_cpu, top_memory, high_cpu_breaches, highest_cost_servers, fleet_costs, sustained_cpu_pressure, underutilized, compare_cost, compare_completed_days, compare_today.

Fleet costs expose observed/priced samples, reporting/expected inventory counts, and overall scoped telemetry_coverage_fraction. This coverage is union duration summed across servers divided by scoped current inventory count x period length; it is not an FX-normalized monetary coverage claim. Unknown-cost cohorts remain visible. Counts are integers; monetary/coverage decimals retain precision.

### Optimization policy

Explicit assessment window, normally 24 hours; defaults: at least 20 observations, >=80% union-time coverage, weighted CPU <10%, weighted memory <20%, no CRITICAL evidence in the window, latest effective HEALTHY, selected-currency priced coverage >=80%, estimated cost >=0.01 units of selected currency (USD default), no overlap anomaly.

A caller must explicitly choose the window and currency-specific minimum. The demo uses a declared three-minute/four-sample policy. Results mean OPTIMIZATION_CANDIDATE, requiring workload/business review. No shutdown action or guaranteed savings is inferred.

### CPU pressure policy

Default CPU >80%, at least 20 observations, >=80% union coverage, and >=50% of observations breached. Return fraction, count, peak, weighted mean, first/last breach, and coverage. Fraction is observation-based, not percentage of elapsed time when sampling intervals vary. The demo explicitly uses four minimum samples.

### Cost comparison policy

Completed UTC days compare yesterday to the day before. Equivalent elapsed days compare today [00:00,as_of) with yesterday's matching elapsed duration. Full-yesterday mode marks unequal-duration comparisons. Explicit equivalent selected windows are also supported.

Compare one currency, with >=80% selected-currency fleet-time coverage by default. Population uses scoped current inventory, not reconstructed historical provisioning. UNKNOWN_COST, INSUFFICIENT_COVERAGE, OVERLAPPING_INTERVALS, and UNEQUAL_DURATION suppress confident directional/percentage claims. Observed amount differences remain inspectable when both amounts exist. A zero known baseline never produces a fabricated percentage; positive current amount yields INCREASE_FROM_ZERO.

## Security contract

A future NOLOGIN/read-only role needs USAGE on analytics and SELECT on only the six public views. Ordinary views resolve underlying relations using their owner; the reader receives no raw/core table or private-helper access. No production role/password is created by migration 0002. Role access is dataset/column curation, not tenant isolation. Disposable-role integration tests prove permitted reads and denied internal reads.
