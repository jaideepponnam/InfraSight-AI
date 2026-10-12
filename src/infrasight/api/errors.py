import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from infrasight.ai.provider import AIError


def response(request, status, code, message, details=None):
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status,
        headers={"X-Request-ID": request_id},
        content={
            "error": {"code": code, "message": message, "details": details or []},
            "request_id": request_id,
        },
    )


def install_handlers(app):
    @app.exception_handler(AIError)
    async def ai_error(request: Request, exc):
        structlog.get_logger(__name__).warning("ai_request_failed", error_code=exc.code)
        result = response(
            request,
            exc.status,
            exc.code,
            "AI analytics could not complete; no answer was generated.",
        )
        if exc.status == 429:
            result.headers["Retry-After"] = "30"
        return result

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc):
        code = (
            exc.detail
            if isinstance(exc.detail, str) and exc.detail.isupper()
            else "NOT_FOUND"
            if exc.status_code == 404
            else "REQUEST_FAILED"
        )
        return response(
            request,
            exc.status_code,
            code,
            {
                401: "Missing or invalid API key.",
                403: "Administrative access is required.",
                404: "The requested resource was not found.",
                409: "This source is already running.",
                503: "The requested service is unavailable.",
            }.get(exc.status_code, "The request could not be completed."),
        )

    async def validation_error(request: Request, exc):
        details = [{"field": ".".join(map(str, e["loc"])), "code": e["type"]} for e in exc.errors()]
        return response(
            request, 422, "INVALID_PARAMETERS", "Check the request parameters.", details
        )

    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ValidationError, validation_error)

    @app.exception_handler(ValueError)
    async def invalid_value(request: Request, exc):
        return response(
            request, 422, "INVALID_PARAMETERS", "Check the requested window and parameters."
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc):
        structlog.get_logger(__name__).error(
            "database_request_failed", error_type=type(exc).__name__
        )
        return response(
            request, 503, "DATABASE_UNAVAILABLE", "The database is temporarily unavailable."
        )
