from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardSettings(BaseSettings):
    """Independent frontend configuration: no database or provider credential fields."""

    model_config = SettingsConfigDict(
        env_prefix="INFRASIGHT_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    api_base_url: str = "http://127.0.0.1:8000"
    api_key: SecretStr | None = None
    admin_key: SecretStr | None = None
    request_timeout_seconds: float = Field(default=12, ge=1, le=60)

    @field_validator("api_base_url")
    @classmethod
    def valid_url(cls, value):
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Use an HTTP(S) API URL without embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("API URL must not contain query parameters or fragments")
        return value.rstrip("/")
