"""FastAPI application factory.

Run with ``uvicorn app.main:app``. Everything the app needs is wired here: the
v1 router, the rate limiter, and the exception handlers that turn slowapi's and
SQLAlchemy's exceptions into the HTTP contract in the OpenAPI schema.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.security import limiter, rate_limit_exceeded_handler
from app.db.session import create_all, dispose_engine

log = get_logger(__name__)

DESCRIPTION = """
Machine-readable sample generation with **hard, verified constraints**.

Submit a `GenerationSpec` and get back a job id; poll it for rendered files and
a per-constraint pass/fail map. Every spectral and temporal constraint is
enforced during rendering and measured afterwards, so `constraints_met` is
evidence rather than intent.

* `POST /v1/generate` — queue one job
* `GET /v1/jobs/{job_id}` — poll it
* `POST /v1/batch`, `GET /v1/batches/{batch_id}` — many at once
* `/v1/recipes` — save and reuse specs
* `GET /v1/health` — liveness (unauthenticated)

Authenticated endpoints take an `X-API-Key` header. Recipe reads are open;
everything else requires a key.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare and tear down process-wide resources.

    Creates tables when running against SQLite so a developer can start with no
    migration step; production uses Alembic.
    """
    configure_logging()
    log.info(
        "api_starting",
        environment=settings.environment,
        storage_backend=settings.storage_backend,
    )
    if settings.database_url.startswith("sqlite"):
        await create_all()
    try:
        yield
    finally:
        await dispose_engine()
        log.info("api_stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        A configured app with the v1 router, limiter, and handlers installed.
    """
    app = FastAPI(
        title="SampleForge",
        version=settings.version,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "health", "description": "Liveness and readiness."},
            {"name": "generation", "description": "Queue generation jobs."},
            {"name": "jobs", "description": "Poll job status and results."},
            {"name": "batch", "description": "Submit and track batches of jobs."},
            {"name": "recipes", "description": "Save and reuse generation specs."},
        ],
    )

    # slowapi reads the limiter off app.state; the 429 handler turns its
    # exception into the documented response.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Report a database failure as 503 without leaking the SQL.

        A psycopg or asyncpg error message can carry the query and its
        parameters, which is a schema and a data leak in one. The detail stays
        in the log, keyed to nothing an untrusted caller controls.
        """
        log.error("database_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "the database is unavailable; try again shortly"},
        )

    app.include_router(api_router)
    return app


app = create_app()


def _openapi_schema() -> dict:
    """Build the OpenAPI document, surfacing broken responses at import time.

    Building it here is a cheap smoke test that every route's models are
    coherent. A missing model or a bad response type raises during
    development rather than the first time a client fetches ``/openapi.json``.
    """
    return app.openapi()


_openapi_schema()
