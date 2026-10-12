"""Start an isolated local API process and verify real PostgreSQL-backed HTTP answers."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from infrasight.config import get_settings


def main():
    settings = get_settings()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            raise RuntimeError("Port 8000 is occupied; stop your own API before this demo.")
    # Keys exist only in the process environment; neither reports nor logs contain them.
    env = os.environ.copy()
    env["API_READ_KEY"] = (
        settings.api_read_key.get_secret_value()
        if settings.api_read_key
        else secrets.token_urlsafe(32)
    )
    env["API_ADMIN_KEY"] = (
        settings.api_admin_key.get_secret_value()
        if settings.api_admin_key
        else secrets.token_urlsafe(32)
    )
    headers = {"X-API-Key": env["API_READ_KEY"]}
    admin_headers = {**headers, "X-Admin-Key": env["API_ADMIN_KEY"]}
    output = Path(".uv-cache")
    output.mkdir(exist_ok=True)
    report = {}
    with (output / "phase5-server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "infrasight.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--no-access-log",
            ],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url="http://127.0.0.1:8000", timeout=45) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(
                            "API process exited; inspect the ignored local server log."
                        )
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("API did not become available.")
                for path in ["/health", "/health/ready", "/docs", "/openapi.json"]:
                    response = client.get(path)
                    assert response.status_code == 200, path
                    report[path] = response.status_code
                params = {
                    "source_id": "simulated-cloud",
                    "as_of": "2026-10-11T19:33:00Z",
                    "start": "2026-10-11T19:30:00Z",
                    "end": "2026-10-11T19:33:00Z",
                    "limit": 100,
                }

                def get(name, path, query):
                    response = client.get(path, params=query, headers=headers)
                    assert response.status_code == 200, response.text
                    report[name] = response.json()
                    return report[name]

                get("historical_overview", "/api/v1/analytics/overview", params)
                get(
                    "current_overview",
                    "/api/v1/analytics/overview",
                    {**params, "as_of": datetime.now(UTC).isoformat()},
                )
                for name in [
                    "high-cpu",
                    "regions",
                    "cost-summary",
                    "underutilized",
                    "cpu-pressure",
                ]:
                    query = {**params}
                    if name in {"underutilized", "cpu-pressure"}:
                        query["min_samples"] = 4
                    get(name, "/api/v1/analytics/" + name, query)
                get(
                    "history_before",
                    "/api/v1/etl/runs",
                    {"source_id": "simulated-cloud", "limit": 100},
                )
                get(
                    "cost_comparison",
                    "/api/v1/analytics/cost-comparison",
                    {
                        "source_id": "simulated-cloud-phase4-comparison",
                        "mode": "explicit",
                        "as_of": params["as_of"],
                        "current_start": params["start"],
                        "current_end": params["end"],
                        "previous_start": "2026-10-10T19:30:00Z",
                        "previous_end": "2026-10-10T19:33:00Z",
                    },
                )
                before = report["cost-summary"]["data"]
                response = client.post(
                    "/api/v1/etl/run",
                    headers=admin_headers,
                    json={"source": "simulator", "start": params["start"], "end": params["end"]},
                )
                assert response.status_code == 200, response.text
                report["replay"] = response.json()
                after = get("cost_after_replay", "/api/v1/analytics/cost-summary", params)["data"]
                assert before == after
                report["analytics_unchanged_after_replay"] = True
                get(
                    "history_after",
                    "/api/v1/etl/runs",
                    {"source_id": "simulated-cloud", "limit": 100},
                )
                report["denied_read"] = client.get("/api/v1/servers").status_code
                report["denied_invalid_read"] = client.get(
                    "/api/v1/servers", headers={"X-API-Key": "invalid"}
                ).status_code
                report["denied_admin"] = client.post(
                    "/api/v1/etl/run", headers=headers, json={}
                ).status_code
                assert (
                    report["denied_read"]
                    == report["denied_invalid_read"]
                    == report["denied_admin"]
                    == 401
                )
                response = client.get("/api/v1/servers", params={"limit": 101}, headers=headers)
                assert response.status_code == 422
                report["validation"] = response.json()
                assert report["validation"]["request_id"] == response.headers["X-Request-ID"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    (output / "phase5-demo.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    historical, current = report["historical_overview"]["data"], report["current_overview"]["data"]
    summary = {
        "historical_health": {
            k: historical[k]
            for k in [
                "inventory_servers",
                "reporting_servers",
                "healthy_servers",
                "warning_servers",
                "critical_servers",
            ]
        },
        "current_stale_servers": current["stale_servers"],
        "high_cpu_servers": len(report["high-cpu"]["data"]),
        "high_cpu_breaches": sum(r["breach_count"] for r in report["high-cpu"]["data"]),
        "regional_health": [
            {
                k: r[k]
                for k in ["region_code", "healthy_servers", "warning_servers", "critical_servers"]
            }
            for r in report["regions"]["data"]
        ],
        "observed_cost": report["cost-summary"]["data"]["estimated_cost"],
        "currency": report["cost-summary"]["data"]["currency"],
        "highest_cost_server": report["cost-summary"]["data"]["top_cost_servers"][0][
            "external_server_id"
        ],
        "underutilized_candidates": len(report["underutilized"]["data"]),
        "cpu_pressure_servers": len(report["cpu-pressure"]["data"]),
        "history_before": report["history_before"]["meta"]["pagination"]["total"],
        "history_after": report["history_after"]["meta"]["pagination"]["total"],
        "replay": report["replay"]["data"],
        "denied_read": report["denied_read"],
        "denied_admin": report["denied_admin"],
        "validation": report["validation"],
        "analytics_unchanged_after_replay": report["analytics_unchanged_after_replay"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
