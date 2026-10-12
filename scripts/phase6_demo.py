"""Small real-Groq HTTP demo. No keys, prompts, answers, or provider internals are logged."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from infrasight.config import get_settings

QUESTIONS = [
    "How is our infrastructure doing?",
    "Which servers had CPU above 80%?",
    "Which servers are costing us the most?",
    "Are there any underutilized servers?",
    "Which region has the most critical servers?",
    "Did infrastructure cost increase compared with the previous equivalent period?",
    "Which servers are under sustained CPU pressure?",
]


def main():
    parser = argparse.ArgumentParser(description="Real Groq/PostgreSQL HTTP verification")
    parser.add_argument("--questions", type=int, choices=range(1, 8), default=1)
    parser.add_argument("--delay-seconds", type=float, default=60)
    parser.add_argument("--start-question", type=int, choices=range(1, 8), default=1)
    args = parser.parse_args()
    if args.start_question + args.questions - 1 > len(QUESTIONS):
        parser.error("Selected questions exceed the seven-question demo")
    settings = get_settings()
    if not settings.groq_api_key:
        print(json.dumps({"status": "BLOCKED", "code": "AI_NOT_CONFIGURED"}))
        return 2
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            print(json.dumps({"status": "BLOCKED", "code": "LOCAL_PORT_OCCUPIED"}))
            return 2
    env = os.environ.copy()
    # Inherit GROQ_API_KEY normally; the application settings also support ignored .env.
    # Never extract, inspect, print or persist the actual provider key here.
    if not settings.api_read_key:
        env["API_READ_KEY"] = secrets.token_urlsafe(32)
    headers = {
        "X-API-Key": env["API_READ_KEY"]
        if "API_READ_KEY" in env
        else settings.api_read_key.get_secret_value()
    }
    output = Path(".uv-cache")
    output.mkdir(exist_ok=True)
    results = []
    with (output / "phase6-server.log").open("w", encoding="utf-8") as log:
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
            with httpx.Client(base_url="http://127.0.0.1:8000", timeout=70) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Local API process did not start.")
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Local API did not become ready.")
                assert client.get("/health/ready").status_code == 200
                spec = client.get("/openapi.json")
                assert spec.status_code == 200 and "/api/v1/ai/query" in spec.json()["paths"]
                for index, question in enumerate(
                    QUESTIONS[args.start_question - 1 : args.start_question - 1 + args.questions],
                    args.start_question,
                ):
                    context = {
                        "question": question,
                        "source_id": "simulated-cloud",
                        "reference_time": "2026-10-11T19:33:00Z",
                        "start": "2026-10-11T19:30:00Z",
                        "end": "2026-10-11T19:33:00Z",
                        "min_samples": 4,
                    }
                    if index == 6:
                        context["source_id"] = "simulated-cloud-phase4-comparison"
                    response = client.post("/api/v1/ai/query", headers=headers, json=context)
                    body = response.json()
                    if response.status_code == 200:
                        assert body["answer"] and body["evidence"]["tools_used"]
                        assert body["request_id"] == response.headers["X-Request-ID"]
                        result = {
                            "question_number": index,
                            "status": 200,
                            "tools": body["evidence"]["tools_used"],
                            "response": body,
                        }
                        results.append(result)
                        print(
                            json.dumps(
                                {
                                    "question_number": index,
                                    "status": 200,
                                    "tools": result["tools"],
                                    "reference_time": body["evidence"]["reference_time"],
                                }
                            ),
                            flush=True,
                        )
                    else:
                        result = {
                            "question_number": index,
                            "status": response.status_code,
                            "code": body.get("error", {}).get("code", "AI_DEMO_FAILED"),
                        }
                        results.append(result)
                        print(json.dumps(result), flush=True)
                        # Do not retry errors or consume more quota with an unavailable provider.
                        break
                    if index < args.start_question + args.questions - 1:
                        time.sleep(max(0, min(args.delay_seconds, 60)))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    (output / "phase6-demo.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if len(results) == args.questions and all(r["status"] == 200 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
