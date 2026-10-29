"""Incident state policy, independent of HTTP, storage, and LLM availability."""

STATES = ("DETECTED", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATING", "VERIFYING", "RESOLVED")
TRANSITIONS = {
    "DETECTED": {"ACKNOWLEDGED"},
    "ACKNOWLEDGED": {"INVESTIGATING"},
    "INVESTIGATING": {"MITIGATING"},
    "MITIGATING": {"VERIFYING", "INVESTIGATING"},
    "VERIFYING": {"RESOLVED", "INVESTIGATING"},
    "RESOLVED": set(),
}


class SREError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def validate_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise SREError("SRE_INVALID_TRANSITION")
