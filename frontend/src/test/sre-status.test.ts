import { describe, expect, it } from "vitest";
import { assessService, recoveryVerification } from "../sre/status";
import { activeRecords, at, epoch, evidence, incident, now, uid } from "./sre.fixtures";

describe("operational evidence interpretation", () => {
  it("does not infer health from a service registration or incident state", () => {
    expect(assessService(undefined, undefined, now).state).toBe("UNKNOWN");
    expect(assessService(incident, undefined, now).state).toBe("UNKNOWN");
    const empty = structuredClone(evidence); empty.probes = [];
    expect(assessService(incident, empty, now).state).toBe("UNKNOWN");
  });
  it("distinguishes fresh success, controlled failure and stale evidence", () => {
    expect(assessService(incident, evidence, now).state).toBe("HEALTHY");
    const active = activeRecords();
    expect(assessService(active.incident, active.evidence, now).state).toBe("DEGRADED");
    expect(assessService(incident, evidence, epoch + 24_000).state).toBe("HEALTHY");
    expect(assessService(incident, evidence, epoch + 24_001).state).toBe("STALE");
    expect(assessService(active.incident, active.evidence, epoch + 130_000).state).toBe("STALE");
  });
  it("does not treat future samples or unsupported policies as current health", () => {
    expect(assessService(incident, evidence, epoch).state).toBe("UNKNOWN");
    expect(assessService({ ...incident, policy_version: "future-policy" }, evidence, now).state).toBe("UNKNOWN");
  });
  it("rejects mismatched service/run and unauthenticated target observations", () => {
    const changed = structuredClone(evidence);
    changed.run.service_id = uid(999);
    expect(assessService(incident, changed, now).state).toBe("UNKNOWN");
    changed.run.service_id = incident.service_id;
    changed.probes.at(-1)!.target_request_id = null;
    expect(assessService(incident, changed, now).state).toBe("UNKNOWN");
  });
  it("uses the newest observation and never substitutes an older healthy one", () => {
    const changed = structuredClone(evidence);
    changed.probes.reverse();
    changed.probes[0].outcome = "TIMEOUT";
    changed.probes[0].http_status = null;
    expect(assessService(incident, changed, now).state).toBe("UNKNOWN");
    expect(changed.probes[0].observed_at).toBe(at(9));
  });
});

describe("recovery verification", () => {
  it("requires terminal timestamps to corroborate the recovered lifecycle", () => {
    expect(recoveryVerification({ ...incident, resolved_at: null }, evidence, now).label).toBe("Not confirmed");
    const changed = structuredClone(evidence); changed.run.finished_at = null;
    expect(recoveryVerification(incident, changed, now).label).toBe("Not confirmed");
  });
  it("keeps historical verified recovery separate from current stale health", () => {
    expect(recoveryVerification(incident, evidence, epoch + 100_000).label).toBe("Verified");
    expect(assessService(incident, evidence, epoch + 100_000).state).toBe("STALE");
  });
  it("requires linked post-action observations and a resolved lifecycle", () => {
    const changed = structuredClone(evidence);
    changed.recovery_attempts[0].evidence.verification_probe_ids = [uid(999), uid(998), uid(997)];
    expect(recoveryVerification(incident, changed, now).label).toBe("Not confirmed");
    expect(recoveryVerification({ ...incident, state: "VERIFYING" }, evidence, now).label).toBe("Not confirmed");
    expect(recoveryVerification(incident, undefined, now).label).toBe("Not confirmed");
  });
  it("does not equate an applied action or automatic expiry with verification", () => {
    const changed = structuredClone(evidence);
    changed.recovery_attempts[0].evidence.verified_recovery = false;
    expect(recoveryVerification(incident, changed, now).label).toBe("Not confirmed");
    changed.recovery_attempts[0].evidence.verified_recovery = true;
    changed.probes.at(-1)!.evidence.fault_state = "expired";
    expect(recoveryVerification(incident, changed, now).label).toBe("Not confirmed");
  });
  it.each(["FAILED", "RUNNING", "INTERRUPTED"] as const)("interprets a %s attempt", status => {
    const changed = structuredClone(evidence);
    changed.recovery_attempts[0].status = status;
    expect(recoveryVerification(incident, changed, now).label).toBe(
      status === "FAILED" ? "Failed" : status === "RUNNING" ? "Pending" : "Interrupted",
    );
  });
  it("handles absent attempts and expired execution without inventing resolution", () => {
    const active = activeRecords();
    expect(recoveryVerification(active.incident, active.evidence, now).label).toBe("Pending");
    const changed = structuredClone(evidence);
    changed.recovery_attempts[0].status = "RUNNING";
    expect(recoveryVerification(incident, changed, epoch + 121_000).label).toBe("Interrupted");
  });
  it("accepts verified re-examination without claiming another applied action", () => {
    const changed = structuredClone(evidence);
    changed.recovery_attempts[0].action_applied = false;
    expect(recoveryVerification(incident, changed, now).label).toBe("Verified");
  });
});
