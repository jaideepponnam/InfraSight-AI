// Runtime read-contract checks. Keep these independent of the HTTP client.
import { INCIDENT_STATES } from "./types";
import type {
  DiagnosticEvidence, ExerciseRun, HTTPObservation, Incident, IncidentEvent,
  MonitoredService, RecoveryAttempt, SREEnvelope,
} from "./types";

type ObjectValue = Record<string, unknown>;
const object = (v: unknown): v is ObjectValue =>
  !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string";
const instant = (v: unknown): v is string =>
  text(v) && Number.isFinite(Date.parse(v)) && /(?:Z|[+-]\d{2}:\d{2})$/.test(v);
const nullableTime = (v: unknown) => v === null || instant(v);
const nullableText = (v: unknown) => v === null || text(v);
const integer = (v: unknown): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= 0;
export const isUUID = (v: unknown): v is string =>
  text(v) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const oneOf = (v: unknown, values: readonly string[]) => text(v) && values.includes(v);

export const isService = (v: unknown): v is MonitoredService =>
  object(v) && isUUID(v.id) && text(v.service_key) &&
  text(v.description) && instant(v.created_at);

export const isIncident = (v: unknown): v is Incident =>
  object(v) && isUUID(v.id) && isUUID(v.service_id) && isUUID(v.run_id) &&
  text(v.title) && v.severity === "SEV3" && oneOf(v.state, INCIDENT_STATES) &&
  text(v.policy_version) && instant(v.detected_at) &&
  nullableTime(v.acknowledged_at) && nullableTime(v.resolved_at) &&
  integer(v.version) && v.version > 0;

export const isRun = (v: unknown): v is ExerciseRun =>
  object(v) && isUUID(v.id) && isUUID(v.service_id) && v.scenario === "http-503" &&
  oneOf(v.status, ["ACTIVE", "SUCCEEDED", "FAILED", "INTERRUPTED"]) &&
  oneOf(v.phase, ["CREATED", "BASELINE", "FAULT", "DETECTED", "RECOVERY", "COMPLETE"]) &&
  typeof v.fault_enabled === "boolean" && nullableTime(v.fault_expires_at) &&
  nullableTime(v.fault_cleared_at) && instant(v.deadline_at) &&
  nullableTime(v.finished_at) && nullableText(v.error_code) && instant(v.created_at);

export const isProbe = (v: unknown): v is HTTPObservation =>
  object(v) && isUUID(v.id) && isUUID(v.run_id) &&
  oneOf(v.phase, ["BASELINE", "DETECTION", "VERIFICATION"]) && instant(v.observed_at) &&
  text(v.duration_ms) && /^\d+(?:\.\d+)?$/.test(v.duration_ms) &&
  (v.http_status === null || (integer(v.http_status) && v.http_status >= 100 && v.http_status <= 599)) &&
  oneOf(v.outcome, ["HEALTHY", "HTTP_503", "UNEXPECTED_HTTP", "TIMEOUT", "TRANSPORT_ERROR", "INVALID_RESPONSE"]) &&
  (v.target_request_id === null || isUUID(v.target_request_id)) &&
  isUUID(v.request_id) && object(v.evidence);

export const isRecovery = (v: unknown): v is RecoveryAttempt =>
  object(v) && isUUID(v.id) && isUUID(v.incident_id) &&
  v.action === "clear-controlled-dependency-fault" &&
  oneOf(v.status, ["RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED"]) &&
  nullableText(v.error_code) && typeof v.action_applied === "boolean" &&
  object(v.evidence) && isUUID(v.request_id) && instant(v.started_at) &&
  nullableTime(v.finished_at);

export const isEvent = (v: unknown): v is IncidentEvent =>
  object(v) && isUUID(v.id) && isUUID(v.incident_id) &&
  integer(v.sequence) && v.sequence > 0 && text(v.event_type) && text(v.actor) &&
  (v.from_state === null || oneOf(v.from_state, INCIDENT_STATES)) &&
  oneOf(v.to_state, INCIDENT_STATES) && isUUID(v.request_id) &&
  object(v.evidence) && instant(v.created_at);

export const arrayOf = <T>(validate: (v: unknown) => v is T) =>
  (v: unknown): v is T[] => Array.isArray(v) && v.every(validate);

export function isEvidence(v: unknown): v is DiagnosticEvidence {
  if (!object(v) || !isRun(v.run) ||
      !arrayOf(isProbe)(v.probes) || !arrayOf(isRecovery)(v.recovery_attempts)) return false;
  const run = v.run;
  return v.probes.every(p => p.run_id === run.id);
}

export function checked<T>(value: unknown, validate: (v: unknown) => v is T): SREEnvelope<T> {
  if (!object(value) || !object(value.meta) ||
      !isUUID(value.meta.request_id) || !validate(value.data)) {
    throw new TypeError("Invalid SRE read response.");
  }
  for (const key of ["total", "limit", "offset"]) {
    if (value.meta[key] !== undefined && value.meta[key] !== null && !integer(value.meta[key])) {
      throw new TypeError("Invalid SRE pagination metadata.");
    }
  }
  return value as unknown as SREEnvelope<T>;
}
