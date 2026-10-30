import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_name: str = "InfraSight-AI"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "https://jaideepponnam.com",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)

    # These configure parameterized services; public view defaults are visible SQL constants.
    analytics_freshness_seconds: int = Field(default=120, ge=1, le=86400)
    analytics_max_window_days: int = Field(default=7, ge=1, le=7)
    analytics_max_results: int = Field(default=100, ge=1, le=100)

    api_read_key: SecretStr | None = None
    api_admin_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    groq_model: str = Field(default="openai/gpt-oss-120b", min_length=1, max_length=128)
    groq_timeout_seconds: float = Field(default=20, ge=1, le=60)
    ai_request_timeout_seconds: float = Field(default=60, ge=1, le=120)
    ai_max_result_rows: int = Field(default=20, ge=1, le=50)
    ai_max_analytics_tool_rounds: int = Field(default=3, ge=1, le=3)

    etl_api_max_window_seconds: int = Field(default=600, ge=90, le=3600)
    demo_public_etl_enabled: bool = False

    # Loopback is the hosted application's own listener, never a client-selected URL.
    sre_enabled: bool = False
    sre_probe_port: int = Field(
        default_factory=lambda: int(os.getenv("PORT", "10000")), ge=1024, le=65535
    )
    sre_probe_timeout_seconds: float = Field(default=2, ge=0.1, le=5)
    sre_run_deadline_seconds: int = Field(default=120, ge=30, le=120)
    sre_cooldown_seconds: int = Field(default=60, ge=0, le=3600)

    etl_batch_size: int = Field(default=500, ge=1, le=1000)
    etl_overlap_seconds: int = Field(default=60, ge=0, le=3600)
    etl_initial_lookback_seconds: int = Field(default=120, ge=1, le=86400)
    etl_max_window_seconds: int = Field(default=3600, ge=1, le=86400)
    etl_source_max_attempts: int = Field(default=3, ge=1, le=10)
    etl_retry_base_seconds: float = Field(default=0.25, ge=0, le=10)
    etl_retry_max_seconds: float = Field(default=5, ge=0, le=60)
    telemetry_interval_seconds: int = Field(default=30, ge=1, le=3600)
    simulator_server_count: int = Field(default=75, ge=50, le=100)
    simulator_seed: int = 7
    simulator_malformed_rate: float = Field(default=0.01, ge=0, le=0.1)
    host_enabled: bool = False
    host_source_id: str = "host-local"
    host_external_server_id: str = "local-host"
    host_region_code: str = "local"
    host_environment: Literal["dev", "staging", "prod"] = "dev"
    host_disk_path: str = "."
    host_sample_seconds: int = Field(default=1, ge=1, le=30)

    @model_validator(mode="after")
    def validate_ingestion_bounds(self):
        if self.etl_max_window_seconds < self.etl_overlap_seconds + self.telemetry_interval_seconds:
            raise ValueError("ETL maximum window must fit overlap plus one telemetry interval")
        if self.etl_initial_lookback_seconds < self.telemetry_interval_seconds:
            raise ValueError("Initial lookback must include at least one telemetry interval")
        return self

    @model_validator(mode="after")
    def separate_api_keys(self):
        if (
            self.api_read_key
            and self.api_admin_key
            and self.api_read_key.get_secret_value() == self.api_admin_key.get_secret_value()
        ):
            raise ValueError("Read and admin API keys must be different")
        return self

    @field_validator("host_source_id", "host_external_server_id", "host_region_code")
    @classmethod
    def nonblank_host_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Host identifiers must not be blank")
        return value.strip()

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            origin = urlsplit(value)
            if (
                origin.scheme not in {"http", "https"}
                or not origin.hostname
                or origin.username is not None
                or origin.password is not None
                or origin.path
                or origin.query
                or origin.fragment
                or "*" in value
            ):
                raise ValueError("CORS requires explicit HTTP origins without paths or wildcards")
        return values

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = (
                url.drivername in {"postgres", "postgresql", "postgresql+psycopg"}
                and url.host
                and url.database
            )
        except Exception:
            valid = False
        if not valid:
            raise ValueError("A PostgreSQL psycopg URL with host and database is required")
        if url.host.lower().endswith(".neon.tech"):
            if "-pooler" in url.host.lower():
                raise ValueError("Use the Neon direct endpoint to preserve session advisory locks")
            if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Neon connections require TLS in the connection URL")
        normalized = url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
        return SecretStr(normalized)


@lru_cache
def get_settings() -> Settings:
    return Settings()
