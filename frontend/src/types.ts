// Contracts inspected in api/schemas.py, api/operations.py and ai/schemas.py.
export type Numeric = string | null;
export type Health = "HEALTHY" | "WARNING" | "CRITICAL" | "STALE" | "NO_DATA";
export interface Coverage {
  estimated_cost: Numeric;
  currency: string;
  observation_count: number;
  reporting_server_count: number;
  expected_server_count: number;
  coverage_fraction: Numeric;
  cost_coverage_fraction: Numeric;
  overlap_detected: boolean;
}
export interface Server {
  server_id: string;
  server_name: string;
  region_code: string;
  environment: string;
  effective_health?: Health;
  cpu_usage_percent?: Numeric;
  estimated_cost?: Numeric;
}
export interface Overview {
  inventory_servers: number;
  reporting_servers: number;
  healthy_servers: number;
  warning_servers: number;
  critical_servers: number;
  stale_servers: number;
  no_data_servers: number;
  average_cpu_percent: Numeric;
  average_memory_percent: Numeric;
  average_storage_percent: Numeric;
  observed_cost: Numeric;
  latest_telemetry_timestamp: string | null;
  coverage: Coverage;
  highest_cpu_server: Server | null;
  highest_cost_server: Server | null;
}
export interface Region
  extends Pick<
    Overview,
    | "inventory_servers"
    | "reporting_servers"
    | "healthy_servers"
    | "warning_servers"
    | "critical_servers"
    | "stale_servers"
    | "no_data_servers"
    | "average_cpu_percent"
    | "average_memory_percent"
    | "average_storage_percent"
    | "latest_telemetry_timestamp"
  > {
  region_code: string;
  source_id: string;
  period_cost: Record<string, unknown>;
}
export interface Run {
  requested_window_start?: string;
  requested_window_end?: string;
  run_id: string;
  source_id: string;
  status: string;
  records_extracted: number;
  records_accepted: number;
  records_inserted: number;
  records_duplicated: number;
  records_rejected: number;
  started_at: string | null;
  finished_at: string | null;
  watermark_after: string | null;
}
export interface Envelope<T> {
  data: T;
  meta: {
    request_id: string;
    pagination?: { total: number; limit: number; offset: number };
    warnings?: string[];
  };
}
export interface Context {
  mode: "SNAPSHOT" | "LIVE";
  source_id: string;
  reference_time: string;
  start: string;
  end: string;
  currency: string;
  freshness_seconds: number;
  min_samples: number;
}
export interface ToolEvidence {
  tool: string;
  arguments: Record<string, unknown>;
  reference_time: string;
  window: Record<string, string | null>;
  freshness: Record<string, unknown>;
  coverage: Record<string, unknown>[];
  currency: string | null;
  returned_rows: number;
  result: Record<string, unknown>;
  warnings: string[];
}
export interface AIResponse {
  answer: string;
  request_id: string;
  evidence: {
    tools_used: string[];
    reference_time: string;
    window: Record<string, string | null>;
    freshness: Record<string, unknown>;
    coverage: Record<string, unknown>[];
    currency: string;
    tool_results: ToolEvidence[];
  };
}

export interface DemoETLResult {
  run_id: string;
  source_id: string;
  status: "SUCCEEDED" | "FAILED";
  window_start: string;
  window_end: string;
  watermark_before: string | null;
  watermark_after: string | null;
  counts: { extracted: number; accepted: number; inserted: number; duplicated: number; rejected: number };
  error_code: string | null;
}

export interface AverageHealth {
  scope_kind: "fleet" | "region";
  source_id: string | null;
  region_code: string | null;
  observation_count: number;
  healthy_fraction: Numeric;
  warning_fraction: Numeric;
  critical_fraction: Numeric;
  coverage_fraction: Numeric;
  health_overlap_detected: boolean;
}
