"""Job submission.

``POST /v1/generate`` — the most-called endpoint, so it also carries a per-key
quota (100 requests/minute by default).

The handler does three things and delegates the rest: persist a job row, hand
the id to arq, and answer 202. Rendering happens in the worker, never in the
request. A GPU render takes seconds to minutes; holding an HTTP connection open
for that would exhaust the connection pool long before the GPU was busy.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import ApiKey, limiter
from app.db.session import SessionDep
from app.models.db import GenerationJob
from app.models.schemas import STATUS_QUEUED, GenerationSpec, JobSubmitResponse
from app.workers.queue import enqueue_job

log = get_logger(__name__)

router = APIRouter(prefix="/generate", tags=["generation"])

#: Seed space for un-seeded submissions. Two identical requests must not produce
#: identical audio, so a random base seed is drawn unless the caller seeds it.
_SEED_MODULUS = 2**31 - 1


def generate_limit() -> str:
    """Effective quota for ``POST /v1/generate``.

    Read from settings on every call rather than captured at import, so the
    limit is reconfigurable without a redeploy — and so tests can raise it.

    Returns:
        A slowapi limit string.
    """
    if not settings.rate_limit_enabled:
        return "100000/minute"
    return settings.generate_rate_limit


async def create_job(
    session: AsyncSession,
    spec: GenerationSpec,
    *,
    batch_id: str | None = None,
    recipe_id: str | None = None,
    base_seed: int | None = None,
) -> GenerationJob:
    """Persist a job row for a spec.

    Shared by ``/batch`` and ``/recipes/{id}/run`` so a job's shape never
    depends on which endpoint submitted it.

    Args:
        session: Open database session. The caller commits.
        spec: The validated spec.
        batch_id: Batch this job belongs to, if any.
        recipe_id: Recipe this job was launched from, if any.
        base_seed: Seed for the job. Random when omitted.

    Returns:
        The created job, with ``id`` assigned and flushed so it has a primary
        key even before commit.
    """
    job = GenerationJob(
        id=uuid.uuid4().hex,
        status=STATUS_QUEUED,
        spec=spec.model_dump(mode="json"),
        batch_size=spec.batch_size,
        base_seed=uuid.uuid4().int % _SEED_MODULUS if base_seed is None else base_seed,
        batch_id=batch_id,
        recipe_id=recipe_id,
        result_urls=[],
    )
    session.add(job)
    await session.flush()
    return job


@router.post(
    "",
    response_model=JobSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a generation job",
    description=(
        "Accepts a `GenerationSpec` and queues it for a worker. Returns 202 "
        "with a poll URL: generation is asynchronous, so no audio exists yet. "
        "Poll `GET /v1/jobs/{job_id}` for the result.\n\n"
        "Every hard constraint in the spec is enforced during rendering and "
        "verified afterwards; a job that could not meet one finishes as "
        "`complete_with_warnings` rather than failing."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "The spec is invalid or violates a hard constraint."
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Rate limit exceeded.",
            "headers": {"Retry-After": {"description": "Seconds to wait."}},
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "The API is unconfigured, or the job queue is unreachable."
        },
    },
)
@limiter.limit(generate_limit)
async def submit_generation(
    request: Request,
    spec: GenerationSpec,
    api_key: ApiKey,
    session: SessionDep,
) -> JobSubmitResponse:
    """Queue one generation job.

    Args:
        request: Incoming request, required by the rate limiter.
        spec: The validated generation spec.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The queued job's id, status, and poll URL.

    Raises:
        HTTPException: 503 if the queue is unreachable. The job row is marked
            failed in that case rather than left queued for something that will
            never come.
    """
    job = await create_job(session, spec)
    try:
        await enqueue_job(job.id)
    except ConnectionError as exc:
        # The row is rolled back with the transaction: a job the queue never
        # heard of is better absent than permanently "queued".
        await session.rollback()
        log.error("enqueue_failed", job_id=job.id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the job queue is unavailable; try again shortly",
        ) from exc
    await session.commit()

    log.info("job_queued", job_id=job.id, category=spec.category, batch_size=spec.batch_size)
    return JobSubmitResponse(
        job_id=job.id,
        status=STATUS_QUEUED,
        poll_url=f"/v1/jobs/{job.id}",
    )
