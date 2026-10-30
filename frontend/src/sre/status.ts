import type { DiagnosticEvidence, HTTPObservation, Incident } from "./types";

export type OperationalState = "HEALTHY" | "DEGRADED" | "UNKNOWN" | "STALE";
export interface Assessment {
  state: OperationalState; reason: string; probe: HTTPObservation | null;
}
// Mirrors backend rules.py for this version only; unknown policies cannot establish health.
export const FRESHNESS_MS = 15_000;
const supported = (incident: Incident) => incident.policy_version === "controlled-http-503-v1";

export function assessService(incident: Incident | undefined, evidence: DiagnosticEvidence | undefined, now: number): Assessment {
  const unknown = (reason: string, probe: HTTPObservation | null = null): Assessment => ({ state: "UNKNOWN", reason, probe });
  if (!incident || !evidence) return unknown("No service observation is available. Incident status alone does not establish health.");
  if (evidence.run.id !== incident.run_id || evidence.run.service_id !== incident.service_id) return unknown("Evidence does not match this incident and service.");
  const probes = [...evidence.probes].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at));
  const probe = probes[0] ?? null;
  if (!probe) return unknown("No HTTP observations have been recorded.");
  const time = Date.parse(probe.observed_at);
  if (!Number.isFinite(time) || time > now) return unknown("The observation time cannot be assessed against this browser's clock.", probe);
  if (!supported(incident)) return unknown("A freshness policy is not available for this observation.", probe);
  if (now - time > FRESHNESS_MS || (evidence.run.status === "ACTIVE" && Date.parse(evidence.run.deadline_at) <= now)) {
    return { state: "STALE", reason: "Stored evidence is outside the current observation window. Service health is not established.", probe };
  }
  if (probe.run_id !== evidence.run.id || !probe.target_request_id || probe.evidence.kind !== "controlled-application-dependency") {
    return unknown("The probe did not establish a response from the expected dependency.", probe);
  }
  if (probe.outcome === "HEALTHY" && probe.http_status === 200 && ["baseline", "cleared", "expired"].includes(String(probe.evidence.fault_state))) {
    return { state: "HEALTHY", reason: "HTTP 200 observed within the last 15 seconds. This is an on-demand observation.", probe };
  }
  if (probe.outcome === "HTTP_503" && probe.http_status === 503 && probe.evidence.fault_state === "active") {
    return { state: "DEGRADED", reason: "A controlled application-dependency HTTP 503 was observed within the last 15 seconds.", probe };
  }
  return unknown("The latest probe could not establish dependency health (" + probe.outcome + ").", probe);
}

export interface Verification {
  label: "Verified" | "Failed" | "Pending" | "Interrupted" | "Not confirmed";
  description: string;
}
export function recoveryVerification(incident: Incident, evidence: DiagnosticEvidence | undefined, now: number): Verification {
  if (!evidence) return { label: "Not confirmed", description: "Recovery evidence is unavailable." };
  const attempts = [...evidence.recovery_attempts].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
  const attempt = attempts[0];
  if (!attempt) return { label: "Pending", description: "No recovery attempt is recorded. An incident status does not prove recovery." };
  if (attempt.status === "FAILED") return { label: "Failed", description: "The latest recovery attempt failed. Verified recovery has not been established." };
  if (attempt.status === "INTERRUPTED" || (attempt.status === "RUNNING" && Date.parse(evidence.run.deadline_at) <= now)) {
    return { label: "Interrupted", description: "Recovery was interrupted or its deadline elapsed. The stored status may await admin reconciliation." };
  }
  if (attempt.status === "RUNNING") return { label: "Pending", description: "Recovery is recorded as running; successful verification is still pending." };
  const ids = attempt.evidence.verification_probe_ids;
  const verificationProbes = Array.isArray(ids) && ids.length >= 3 && new Set(ids).size === ids.length
    ? ids.map(id => evidence.probes.find(p => p.id === id)) : [];
  const corroborated = supported(incident) && incident.state === "RESOLVED" &&
    evidence.run.status === "SUCCEEDED" && evidence.run.id === incident.run_id &&
    evidence.run.service_id === incident.service_id &&
    attempt.evidence.verified_recovery === true && attempt.finished_at !== null &&
    incident.resolved_at !== null && evidence.run.finished_at !== null &&
    Date.parse(incident.resolved_at) >= Date.parse(attempt.finished_at) &&
    Date.parse(evidence.run.finished_at) >= Date.parse(attempt.finished_at) &&
    Date.parse(incident.resolved_at) <= now && Date.parse(evidence.run.finished_at) <= now &&
    Date.parse(attempt.finished_at) <= now && verificationProbes.length >= 3 &&
    verificationProbes.every(p => p && p.phase === "VERIFICATION" && p.outcome === "HEALTHY" &&
      p.http_status === 200 && p.target_request_id && p.run_id === incident.run_id &&
      p.evidence.kind === "controlled-application-dependency" && p.evidence.fault_state === "cleared" &&
      p.evidence.attempt_id === attempt.id && Date.parse(p.observed_at) >= Date.parse(attempt.started_at) &&
      Date.parse(p.observed_at) <= Date.parse(attempt.finished_at!));
  return corroborated
    ? { label: "Verified", description: "The backend recorded successful recovery with matching healthy post-action probes. This historical result does not establish current service health." }
    : { label: "Not confirmed", description: "The available lifecycle and probe records do not corroborate verified recovery. Refresh to check for updated evidence." };
}
