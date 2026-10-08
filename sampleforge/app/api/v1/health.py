"""Liveness and readiness.

``GET /v1/health`` is the only unauthenticated endpoint: a load balancer or
uptime probe has no API key, and gating health checks behind auth means a
misconfigured key takes the service out of rotation instead of reporting the
misconfiguration.

It answers three questions a caller actually asks — is the process up, is the
model loaded, is the GPU there — and never fails. A missing GPU is not an error,
it is information: a CPU-only deployment is a legitimate configuration. Anything
that *does* fail (an unreachable broker) is reported as ``degraded`` while the
status stays 200, so monitoring alerts on the field rather than on a 5xx that
would take the instance out of rotation.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import HealthResponse
from app.services.generation import is_generator_loaded

log = get_logger(__name__)

router = APIRouter(tags=["health"])

#: Redis list arq pushes job ids onto.
ARQ_QUEUE_KEY = "arq:queue"


def gpu_available() -> bool:
    """Whether a CUDA device is usable.

    Imported lazily and defensively: torch is a heavy optional dependency, and a
    health check must not be the thing that turns a missing install into a
    crash.
    """
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - torch raises more than ImportError here
        # A broken CUDA driver surfaces as a RuntimeError from
        # torch.cuda.is_available(), and an absent torch as ImportError. A
        # health check answers "can we use a GPU" either way.
        return False


async def queue_depth() -> int | None:
    """How many jobs are waiting in the arq queue.

    Returns:
        The queue length, or ``None`` if the broker is unreachable. ``None``
        rather than 0 because "cannot tell" and "empty" lead to different
        decisions.
    """
    try:
        from redis.asyncio import from_url

        client = from_url(settings.redis_url)
        try:
            return int(await client.llen(ARQ_QUEUE_KEY))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "unknown"
        # Connection refused, DNS failure, auth error, timeout: all of them mean
        # the same thing to a health check, which is that the depth is unknown.
        log.warning("queue_depth_unavailable", error=str(exc))
        return None


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description=(
        "Reports process liveness, whether the generator is loaded, whether a "
        "GPU is available, the arq queue depth, and the service version. "
        "Always 200 — degraded components are reported in the body, not as an "
        "HTTP error."
    ),
)
async def health() -> HealthResponse:
    """Return the service's health.

    Returns:
        Status, model/GPU/queue detail, and version.
    """
    depth = await queue_depth()
    gpu = gpu_available()
    loaded = is_generator_loaded()

    degraded: list[str] = []
    if depth is None:
        degraded.append("job queue is unreachable")
    if not gpu and settings.device.startswith("cuda"):
        # Configured for CUDA with no CUDA present: the worker will fail every
        # job at load time, so say so now rather than at the first request.
        degraded.append("device is set to cuda but no GPU is available")

    if degraded:
        log.warning("health_degraded", reasons=degraded)
    return HealthResponse(
        status="degraded" if degraded else "ok",
        model_loaded=loaded,
        gpu_available=gpu,
        queue_depth=depth,
        version=settings.version,
        detail="; ".join(degraded) if degraded else None,
    )
