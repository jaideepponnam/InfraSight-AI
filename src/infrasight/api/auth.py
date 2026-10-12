import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

read_scheme = APIKeyHeader(name="X-API-Key", scheme_name="ApplicationKey", auto_error=False)
admin_scheme = APIKeyHeader(name="X-Admin-Key", scheme_name="AdminKey", auto_error=False)


def verify(provided, expected):
    if expected is None or not expected.get_secret_value():
        raise HTTPException(503, "AUTH_NOT_CONFIGURED")
    if provided is None or not hmac.compare_digest(
        provided.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(401, "INVALID_API_KEY")


def require_read(request: Request, key: str | None = Depends(read_scheme)):
    verify(key, request.app.state.settings.api_read_key)


def require_admin(request: Request, key: str | None = Depends(admin_scheme)):
    verify(key, request.app.state.settings.api_admin_key)
