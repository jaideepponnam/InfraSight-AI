"""Measured HTTP policy for the controlled application dependency, not storage."""

from datetime import timedelta

POLICY_VERSION = "controlled-http-503-v1"
FAILURE_SAMPLES = 3
HEALTHY_SAMPLES = 3
FRESHNESS_SECONDS = 15
SERVICE_KEY = "controlled-application-dependency"
ACTION = "clear-controlled-dependency-fault"


def consecutive(probes, outcome, count, now, *, cleared=False):
    selected = list(probes)[-count:]
    if len(selected) != count:
        return False
    return all(
        p.outcome == outcome
        and now - timedelta(seconds=FRESHNESS_SECONDS) <= p.observed_at <= now
        and (not cleared or p.evidence.get("fault_state") == "cleared")
        for p in selected
    )
