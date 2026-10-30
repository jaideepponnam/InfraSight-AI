import type { DiagnosticEvidence, Incident, IncidentEvent, MonitoredService, SREEnvelope } from "../sre/types";
export const uid = (n: number) => "00000000-0000-4000-8000-" + String(n).padStart(12, "0");
export const epoch = Date.parse("2026-10-29T12:00:00Z");
export const at = (seconds: number) => new Date(epoch + seconds * 1000).toISOString();
export const now = epoch + 11_000;
export const service: MonitoredService = { id: uid(1), service_key: "controlled-application-dependency", description: "Controlled application-dependency HTTP 503 exercise; not a storage outage.", created_at: at(0) };
export const incident: Incident = { id: uid(3), service_id: service.id, run_id: uid(2), title: "Controlled application-dependency failure (HTTP 503); not a storage outage", severity: "SEV3", state: "RESOLVED", policy_version: "controlled-http-503-v1", detected_at: at(3), acknowledged_at: at(4), resolved_at: at(10), version: 7 };
export const evidence: DiagnosticEvidence = {
  run: { id: uid(2), service_id: service.id, scenario: "http-503", status: "SUCCEEDED", phase: "COMPLETE", fault_enabled: false, fault_expires_at: at(120), fault_cleared_at: at(7), deadline_at: at(120), finished_at: at(10), error_code: null, created_at: at(0) },
  probes: Array.from({ length: 10 }, (_, i) => ({
    id: uid(10 + i), run_id: uid(2), phase: i === 0 ? "BASELINE" : i < 7 ? "DETECTION" : "VERIFICATION",
    observed_at: at(i), duration_ms: "12.500", http_status: i === 0 || i >= 7 ? 200 : 503,
    outcome: i === 0 || i >= 7 ? "HEALTHY" : "HTTP_503", target_request_id: uid(50 + i), request_id: uid(5),
    evidence: { kind: "controlled-application-dependency", fault_state: i === 0 ? "baseline" : i < 7 ? "active" : "cleared", ...(i >= 4 ? { attempt_id: uid(4) } : {}) },
  })),
  recovery_attempts: [{ id: uid(4), incident_id: uid(3), action: "clear-controlled-dependency-fault", status: "SUCCEEDED", error_code: null, action_applied: true, evidence: { policy_version: "controlled-http-503-v1", before_probe_ids: [uid(14), uid(15), uid(16)], verification_probe_ids: [uid(17), uid(18), uid(19)], verified_recovery: true }, request_id: uid(5), started_at: at(4), finished_at: at(10) }],
};
export const events: IncidentEvent[] = ["DETECTED", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATING", "MITIGATING", "VERIFYING", "RESOLVED"].map((state, i, values) => ({
  id: uid(30 + i), incident_id: uid(3), sequence: i + 1, event_type: i === 4 ? "FAULT_CLEARED" : state, actor: i === 0 ? "admin-exercise-runner" : "admin-key",
  from_state: i ? values[i - 1] as Incident["state"] : null, to_state: state as Incident["state"], request_id: uid(5), evidence: i === 0 ? { probe_ids: [uid(11), uid(12), uid(13)] } : {}, created_at: at(3 + i),
}));
export function envelope<T>(data: T, meta: Partial<SREEnvelope<T>["meta"]> = {}): SREEnvelope<T> {
  return { data: structuredClone(data), meta: { request_id: uid(5), ...meta } };
}
export function activeRecords() {
  const activeIncident = { ...structuredClone(incident), state: "DETECTED" as const, resolved_at: null, acknowledged_at: null, version: 1 };
  const activeEvidence = structuredClone(evidence);
  activeEvidence.run = { ...activeEvidence.run, status: "ACTIVE", phase: "DETECTED", fault_enabled: true, fault_cleared_at: null, finished_at: null };
  activeEvidence.probes = activeEvidence.probes.slice(0, 4);
  activeEvidence.recovery_attempts = [];
  return { incident: activeIncident, evidence: activeEvidence };
}
