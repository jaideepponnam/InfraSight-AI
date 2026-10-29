"""Validate deployment configuration offline without reading credentials."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def load_yaml(path):
    try:
        # Preserve GitHub's 'on' key and YAML boolean text; no object construction.
        return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        raise SystemExit(f"Invalid YAML structure: {path}") from None


def main():
    blueprint = load_yaml("render.yaml")
    services = {item["name"]: item for item in blueprint["services"]}
    require(
        set(services) == {"infrasight-api", "infrasight-frontend"},
        "Expected exactly two Render services",
    )
    api, frontend = services["infrasight-api"], services["infrasight-frontend"]
    require(
        api["runtime"] == "python" and api["plan"] == "free",
        "Backend must use native free Python service",
    )
    require(api["healthCheckPath"] == "/health/ready", "Backend readiness health check missing")
    require(api["domains"] == ["api.jaideepponnam.com"], "Unexpected API domain")
    require(
        "--frozen --no-dev" in api["buildCommand"],
        "Backend must install locked runtime dependencies",
    )
    require(
        "--port $PORT" in api["startCommand"] and "--workers 1" in api["startCommand"],
        "Backend must bind Render PORT with one worker",
    )
    require(
        not any(word in api["startCommand"] for word in ("infrasight-etl", "alembic", "--reload")),
        "Startup must not migrate, seed, or reload",
    )
    api_env = {item["key"]: item for item in api["envVars"]}
    for name in ("DATABASE_URL", "API_READ_KEY", "API_ADMIN_KEY", "GROQ_API_KEY"):
        require(
            api_env[name].get("sync") == "false" and "value" not in api_env[name],
            f"Configure {name} in Render, never source control",
        )
    require(
        json.loads(api_env["CORS_ALLOWED_ORIGINS"]["value"]) == ["https://jaideepponnam.com"],
        "Production CORS must allow only the frontend origin",
    )
    require(
        api_env["SRE_ENABLED"].get("value") == "false",
        "SRE must remain disabled until a separately approved release",
    )
    require("SRE_PROBE_PORT" not in api_env, "Hosted probes must inherit Render PORT")
    require(
        frontend["runtime"] == "static" and frontend["rootDir"] == "frontend",
        "Expected React static site",
    )
    require(frontend["staticPublishPath"] == "dist", "Expected Vite dist output")
    require(frontend["domains"] == ["jaideepponnam.com"], "Unexpected frontend domain")
    frontend_env = {item["key"]: item for item in frontend["envVars"]}
    require(
        set(frontend_env)
        <= {"NODE_VERSION", "SKIP_INSTALL_DEPS", "VITE_API_BASE_URL", "VITE_API_READ_KEY"},
        "Unexpected frontend environment variable",
    )
    require(
        frontend_env["VITE_API_BASE_URL"]["value"] == "https://api.jaideepponnam.com",
        "Incorrect frontend API origin",
    )
    require(
        frontend_env["VITE_API_READ_KEY"].get("sync") == "false",
        "Public demo credential must be configured explicitly",
    )
    require(
        frontend["routes"] == [{"type": "rewrite", "source": "/*", "destination": "/index.html"}],
        "SPA fallback missing",
    )
    require(
        all(item["autoDeployTrigger"] == "off" for item in services.values()),
        "Deployment must remain manually controlled",
    )
    require(
        (ROOT / ".python-version").read_text().strip() == "3.11", "Project requires Python 3.11"
    )
    require(
        (ROOT / "uv.lock").exists() and (ROOT / "frontend/package-lock.json").exists(),
        "Dependency locks missing",
    )
    workflow = load_yaml(".github/workflows/ci.yml")
    require(set(workflow["jobs"]) == {"backend", "frontend"}, "Expected two CI jobs")
    require(
        set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"},
        "Unexpected CI triggers",
    )
    require(workflow["permissions"] == {"contents": "read"}, "CI permissions must be read-only")
    require(
        workflow["jobs"]["backend"]["services"]["postgres"]["image"] == "postgres:16-alpine",
        "CI PostgreSQL version mismatch",
    )
    backend_steps = " ".join(step.get("run", "") for step in workflow["jobs"]["backend"]["steps"])
    frontend_steps = " ".join(step.get("run", "") for step in workflow["jobs"]["frontend"]["steps"])
    require(
        all(
            command in backend_steps
            for command in ("ruff check", "alembic upgrade head", "alembic check", "pytest")
        ),
        "Backend CI guarantees missing",
    )
    require(
        all(
            command in frontend_steps
            for command in ("npm ci", "npm test", "npm run typecheck", "npm run build")
        ),
        "Frontend CI guarantees missing",
    )
    print("Render blueprint and CI configuration validation passed (offline).")


if __name__ == "__main__":
    main()
