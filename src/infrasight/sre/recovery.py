"""The only recovery action changes the matching sandbox row, never infrastructure."""

from infrasight.sre.lifecycle import SREError
from infrasight.sre.repository import utcnow


def clear_fault(run):
    now = utcnow()
    if run.fault_enabled:
        if run.fault_expires_at is None or run.fault_expires_at <= now:
            raise SREError("SRE_FAULT_ALREADY_EXPIRED")
        run.fault_enabled = False
        run.fault_cleared_at = now
        return True
    if run.fault_cleared_at is None:
        raise SREError("SRE_NO_RECOVERY_ACTION")
    # A different recovery request can reverify an earlier action; it cannot claim it again.
    return False
