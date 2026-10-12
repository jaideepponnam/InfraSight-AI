from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from infrasight.api.errors import install_handlers
from infrasight.api.health import router
from infrasight.api.router import router as business_router
from infrasight.config import Settings, get_settings
from infrasight.db.session import create_database_engine, create_session_factory
from infrasight.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        logger.info("application_started", environment=settings.app_env)
        try:
            yield
        finally:
            engine.dispose()
            logger.info("application_stopped")

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)
    app.include_router(business_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid4())
        tokens = structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.reset_contextvars(**tokens)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # Exception messages can contain credentials; log only the type.
        request_id = getattr(request.state, "request_id", str(uuid4()))
        logger.error("request_failed", request_id=request_id, error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "The request could not be completed.",
                    "details": [],
                },
                "request_id": request_id,
            },
        )

    original_openapi = app.openapi

    def openapi_with_combined_admin_security():
        schema = original_openapi()
        schema["paths"]["/api/v1/etl/run"]["post"]["security"] = [
            {"ApplicationKey": [], "AdminKey": []}
        ]
        return schema

    app.openapi = openapi_with_combined_admin_security
    install_handlers(app)
    return app
