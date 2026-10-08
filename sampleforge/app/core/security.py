"""API authentication and rate limiting.

Two things every endpoint but ``/v1/health`` shares: proof the caller holds an
API key, and a quota so one client cannot monopolise the GPU queue. Both live
here so the route modules stay thin.

Key comparison is constant-time. The values are secrets and the endpoint is
unauthenticated by definition, so a timing oracle that leaked one byte per
request would be enough to recover a key.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from slowapi import Limiter
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def api_key_key_func(request: Request) -> str:
    """slowapi key function: one quota per API key, not per IP.

    The client-address fallback only matters for unauthenticated requests — an
    invalid key gets its own bucket rather than sharing the attacker's, so a
    flood of bad keys cannot exhaust a legitimate client's quota.

    Args:
        request: The incoming request.

    Returns:
        A stable bucket identifier.
    """
    key = request.headers.get(settings.api_key_header)
    if key:
        return f"apikey:{key}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


#: Shared limiter. Storage is in-process, so quotas are per worker process —
#: correct for a single API container, and the thing to swap for Redis storage
#: if the API is ever scaled horizontally.
limiter = Limiter(key_func=api_key_key_func)


async def require_api_key(
    x_api_key: Annotated[
        str | None,
        Header(
            alias=settings.api_key_header,
            description="API key identifying the caller.",
            auto_error=False,
        ),
    ] = None,
) -> str:
    """Validate the caller's API key.

    Args:
        x_api_key: Value of the configured key header, injected by FastAPI.

    Returns:
        The validated key, for logging and as the rate-limit bucket.

    Raises:
        HTTPException: 401 when the header is missing or the key is unknown;
            503 when no keys are configured at all.
    """
    if not settings.api_keys:
        log.error("api_unconfigured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "no API keys are configured; set SAMPLEFORGE_API_KEYS before "
                "serving authenticated endpoints"
            ),
        )
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {settings.api_key_header} header",
            headers={"WWW-Authenticate": settings.api_key_header},
        )
    if not any(secrets.compare_digest(x_api_key, valid) for valid in settings.api_keys):
        log.warning("api_key_rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers={"WWW-Authenticate": settings.api_key_header},
        )
    return x_api_key


#: Dependency form, for route signatures. ``Depends`` rather than ``Security``:
#: this is one opaque check, not a composed security scheme, and declaring it as
#: a scheme would put an API-key box in the Swagger UI that does nothing.
ApiKey = Annotated[str, Depends(require_api_key)]


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render slowapi's ``RateLimitExceeded`` as a 429 with a Retry-After hint.

    Args:
        request: The rejected request.
        exc: The exception slowapi raised.

    Returns:
        A JSON 429 response.
    """
    detail = getattr(exc, "detail", "rate limit exceeded")
    log.warning("rate_limited", path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": f"rate limit exceeded: {detail}"},
        headers={"Retry-After": "60"},
    )


__all__ = [
    "ApiKey",
    "api_key_key_func",
    "limiter",
    "rate_limit_exceeded_handler",
    "require_api_key",
]
