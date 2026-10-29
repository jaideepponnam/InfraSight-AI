"""Private loopback probe target, isolated from readiness and all telemetry routes."""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from infrasight.db.models.sre import SREDemoRun
from infrasight.sre.repository import token_hash, utcnow
from infrasight.sre.rules import SERVICE_KEY

router = APIRouter(include_in_schema=False)


@router.get("/_sre-demo/{run_id}/dependency")
def dependency(
    run_id: UUID,
    request: Request,
    token: Annotated[str | None, Header(alias="X-SRE-Probe", max_length=128)] = None,
):
    if (
        not request.app.state.settings.sre_enabled
        or request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or not token
        or request.query_params
    ):
        raise HTTPException(404, "NOT_FOUND")
    with request.app.state.session_factory() as session:
        run = session.get(SREDemoRun, run_id)
        now = utcnow()
        if (
            run is None
            or run.status != "ACTIVE"
            or run.deadline_at <= now
            or not hmac.compare_digest(token_hash(token), run.probe_token_hash)
        ):
            raise HTTPException(404, "NOT_FOUND")
        fault_active = (
            run.fault_enabled and run.fault_expires_at is not None and run.fault_expires_at > now
        )
        state = (
            "active"
            if fault_active
            else "cleared"
            if run.fault_cleared_at
            else "expired"
            if run.fault_enabled
            else "baseline"
        )
        return JSONResponse(
            status_code=503 if fault_active else 200,
            headers={"Cache-Control": "no-store"},
            content={"kind": SERVICE_KEY, "run_id": str(run.id), "fault_state": state},
        )
