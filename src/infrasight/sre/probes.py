"""Actual HTTP probes. Never accept a URL, arbitrary header, or response body from a caller."""

from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from uuid import UUID

import httpx

from infrasight.sre.rules import SERVICE_KEY


class HTTPProbe:
    def __init__(self, settings):
        self.port = settings.sre_probe_port
        self.timeout = settings.sre_probe_timeout_seconds

    def observe(self, run_id, token):
        started = perf_counter()
        observed = datetime.now(UTC)
        status, target_id, evidence = None, None, {"kind": SERVICE_KEY}
        outcome = "INVALID_RESPONSE"
        # No environment proxies, redirects, API keys, cookies, or provider credentials.
        try:
            with httpx.Client(
                timeout=self.timeout, trust_env=False, follow_redirects=False
            ) as client:
                with client.stream(
                    "GET",
                    f"http://127.0.0.1:{self.port}/_sre-demo/{run_id}/dependency",
                    headers={"X-SRE-Probe": token},
                ) as response:
                    status = response.status_code
                    body = b""
                    for chunk in response.iter_bytes(chunk_size=512):
                        body += chunk
                        if len(body) > 2048:
                            break
                    if len(body) <= 2048:
                        import json

                        data = json.loads(body)
                        target_id = UUID(response.headers["X-Request-ID"])
                        if (
                            isinstance(data, dict)
                            and data.get("kind") == SERVICE_KEY
                            and data.get("run_id") == str(run_id)
                            and data.get("fault_state")
                            in {"baseline", "active", "cleared", "expired"}
                        ):
                            evidence["fault_state"] = data["fault_state"]
                            outcome = (
                                "HTTP_503"
                                if status == 503 and data["fault_state"] == "active"
                                else "HEALTHY"
                                if status == 200 and data["fault_state"] != "active"
                                else "UNEXPECTED_HTTP"
                            )
        except httpx.TimeoutException:
            outcome = "TIMEOUT"
        except httpx.TransportError:
            outcome = "TRANSPORT_ERROR"
        except (ValueError, KeyError, TypeError):
            outcome = "INVALID_RESPONSE"
        return {
            "observed_at": observed,
            "duration_ms": Decimal(str(round((perf_counter() - started) * 1000, 3))),
            "http_status": status,
            "outcome": outcome,
            "target_request_id": target_id,
            "evidence": evidence,
        }
