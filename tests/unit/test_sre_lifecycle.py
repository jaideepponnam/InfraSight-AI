from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from infrasight.sre.lifecycle import STATES, TRANSITIONS, SREError, validate_transition
from infrasight.sre.recovery import clear_fault
from infrasight.sre.rules import consecutive


@pytest.mark.parametrize("current", STATES)
@pytest.mark.parametrize("target", STATES)
def test_only_declared_transitions(current, target):
    if target in TRANSITIONS[current]:
        validate_transition(current, target)
    else:
        with pytest.raises(SREError):
            validate_transition(current, target)


def test_consecutive_policy_requires_fresh_complete_samples():
    now = datetime.now(UTC)
    probes = [SimpleNamespace(outcome="HTTP_503", observed_at=now, evidence={}) for _ in range(3)]
    assert consecutive(probes, "HTTP_503", 3, now)
    assert not consecutive(probes[:2], "HTTP_503", 3, now)
    probes[1].outcome = "TIMEOUT"
    assert not consecutive(probes, "HTTP_503", 3, now)
    probes[1].outcome = "HTTP_503"
    probes[1].observed_at = now - timedelta(seconds=16)
    assert not consecutive(probes, "HTTP_503", 3, now)
    probes[1].observed_at = now + timedelta(seconds=1)
    assert not consecutive(probes, "HTTP_503", 3, now)


def test_expiry_does_not_count_as_verified_recovery():
    now = datetime.now(UTC)
    probes = [
        SimpleNamespace(outcome="HEALTHY", observed_at=now, evidence={"fault_state": "expired"})
        for _ in range(3)
    ]
    assert not consecutive(probes, "HEALTHY", 3, now, cleared=True)
    for probe in probes:
        probe.evidence["fault_state"] = "cleared"
    assert consecutive(probes, "HEALTHY", 3, now, cleared=True)
    run = SimpleNamespace(fault_enabled=True, fault_expires_at=now - timedelta(seconds=1))
    with pytest.raises(SREError, match="SRE_FAULT_ALREADY_EXPIRED"):
        clear_fault(run)
