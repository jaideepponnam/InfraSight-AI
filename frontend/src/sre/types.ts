// Mirrors src/infrasight/sre/schemas.py. SRE pagination is flat in meta.
export const INCIDENT_STATES = ["DETECTED", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATING", "VERIFYING", "RESOLVED"] as const;
export type IncidentState = typeof INCIDENT_STATES[number];
export interface SREEnvelope<T> {
  data: T;
  meta: { request_id: string; total?: number | null; limit?: number | null; offset?: number | null };
}
export interface MonitoredService {
  id: string; service_key: string; description: string; created_at: string;
}
export interface Incident {
  id: string; service_id: string; run_id: string; title: string; severity: "SEV3";
  state: IncidentState; policy_version: string; detected_at: string;
  acknowledged_at: string | null; resolved_at: string | null; version: number;
}
export interface ExerciseRun {
  id: string; service_id: string; scenario: "http-503";
  status: "ACTIVE" | "SUCCEEDED" | "FAILED" | "INTERRUPTED";
  phase: "CREATED" | "BASELINE" | "FAULT" | "DETECTED" | "RECOVERY" | "COMPLETE";
  fault_enabled: boolean; fault_expires_at: string | null; fault_cleared_at: string | null;
  deadline_at: string; finished_at: string | null; error_code: string | null; created_at: string;
}
export interface HTTPObservation {
  id: string; run_id: string; phase: "BASELINE" | "DETECTION" | "VERIFICATION";
  observed_at: string; duration_ms: string; http_status: number | null;
  outcome: "HEALTHY" | "HTTP_503" | "UNEXPECTED_HTTP" | "TIMEOUT" | "TRANSPORT_ERROR" | "INVALID_RESPONSE";
  target_request_id: string | null; request_id: string; evidence: Record<string, unknown>;
}
export interface IncidentEvent {
  id: string; incident_id: string; sequence: number; event_type: string; actor: string;
  from_state: IncidentState | null; to_state: IncidentState; request_id: string;
  evidence: Record<string, unknown>; created_at: string;
}
export interface RecoveryAttempt {
  id: string; incident_id: string; action: "clear-controlled-dependency-fault";
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "INTERRUPTED";
  error_code: string | null; action_applied: boolean; evidence: Record<string, unknown>;
  request_id: string; started_at: string; finished_at: string | null;
}
export interface DiagnosticEvidence {
  run: ExerciseRun; probes: HTTPObservation[]; recovery_attempts: RecoveryAttempt[];
}
