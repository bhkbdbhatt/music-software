"""Batch submission and progress.

``POST /v1/batch`` takes a list of specs and queues each as an independent job
sharing a ``batch_id``. ``GET /v1/batches`` lists them, newest first;
``GET /v1/batches/{batch_id}`` reports one group.

Batch endpoints are the cheapest way to saturate the GPU, hence a much tighter
quota than ``/generate``: 10 requests/minute per key, and 100 specs per request,
so one key can still queue 1000 jobs a minute if it really means it.

Progress is recomputed from the member jobs on every poll rather than
incremented. That costs a ``WHERE batch_id = ?`` scan — cheap, indexed, and it
means a worker crash cannot leave a batch reporting progress that never
happened.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import case, func, select

from app.api.v1.generate import create_job
from app.api.v1.jobs import _to_response
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import ApiKey, limiter
from app.db.session import SessionDep
from app.models.db import GenerationBatch, GenerationJob
from app.models.schemas import (
    STATUS_FAILED,
    SUCCESS_STATUSES,
    BatchList,
    BatchListItem,
    BatchProgressResponse,
    BatchRequest,
    BatchSubmitResponse,
)
from app.workers.queue import enqueue_job

log = get_logger(__name__)

router = APIRouter(tags=["batch"])


def batch_limit() -> str:
    """Effective quota for ``POST /v1/batch``.

    Returns:
        A slowapi limit string.
    """
    if not settings.rate_limit_enabled:
        return "100000/minute"
    return settings.batch_rate_limit


@router.post(
    "/batch",
    response_model=BatchSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a batch of generation jobs",
    description=(
        "Queues one job per spec, all sharing a `batch_id`. Specs are validated "
        "individually, so one bad spec rejects the whole request with 422 "
        "rather than half-queueing a batch.\n\n"
        "`options.max_concurrent` and `options.on_failure` are recorded on the "
        "batch and applied by the worker as it drains the group; the API does "
        "not throttle enqueueing itself.\n\n"
        "Rate limited to "
        f"{settings.batch_rate_limit} per API key."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "One or more specs are invalid."},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Rate limit exceeded."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "The API is unconfigured, or the job queue is unreachable."
        },
    },
)
@limiter.limit(batch_limit)
async def submit_batch(
    request: Request,
    batch: BatchRequest,
    api_key: ApiKey,
    session: SessionDep,
) -> BatchSubmitResponse:
    """Queue every spec in the batch.

    Args:
        request: Incoming request, required by the rate limiter.
        batch: The specs and execution options.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The batch id, job count, and poll URL.

    Raises:
        HTTPException: 503 if the queue is unreachable, in which case nothing is
            committed and no batch row is left behind.
    """
    batch_id = uuid.uuid4().hex
    session.add(
        GenerationBatch(
            id=batch_id,
            total_jobs=len(batch.specs),
            options=batch.options.model_dump(mode="json"),
        )
    )

    jobs = [await create_job(session, spec, batch_id=batch_id) for spec in batch.specs]

    try:
        for job in jobs:
            await enqueue_job(job.id)
    except ConnectionError as exc:
        # Nothing is committed, so no orphan rows and no half-queued batch.
        await session.rollback()
        log.error("batch_enqueue_failed", batch_id=batch_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the job queue is unavailable; try again shortly",
        ) from exc
    await session.commit()

    log.info(
        "batch_queued",
        batch_id=batch_id,
        jobs=len(jobs),
        parallel=batch.options.parallel,
        max_concurrent=batch.options.max_concurrent,
    )
    return BatchSubmitResponse(
        batch_id=batch_id,
        total_jobs=len(jobs),
        poll_url=f"/v1/batches/{batch_id}",
    )


@router.get(
    "/batches/{batch_id}",
    response_model=BatchProgressResponse,
    summary="Poll a batch's progress",
    description=(
        "Aggregate state of every job in the batch: how many finished, how "
        "many failed, and the per-job results for those that finished. Safe to "
        "poll repeatedly; each call recomputes from the database."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_404_NOT_FOUND: {"description": "No such batch."},
    },
)
async def get_batch(
    request: Request,
    batch_id: str,
    api_key: ApiKey,
    session: SessionDep,
) -> BatchProgressResponse:
    """Return a batch's aggregate status and results.

    Args:
        request: Incoming request.
        batch_id: The batch to inspect.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        Counts plus one response per job, in submission order.

    Raises:
        HTTPException: 404 if the batch does not exist.
    """
    batch_row = await session.get(GenerationBatch, batch_id)
    if batch_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown batch: {batch_id}"
        )

    result = await session.execute(
        select(GenerationJob)
        .where(GenerationJob.batch_id == batch_id)
        .order_by(GenerationJob.created_at, GenerationJob.id)
    )
    jobs = list(result.scalars())

    completed = sum(1 for job in jobs if job.status in SUCCESS_STATUSES)
    failed = sum(1 for job in jobs if job.status == STATUS_FAILED)

    return BatchProgressResponse(
        batch_id=batch_id,
        completed=completed,
        failed=failed,
        total=len(jobs),
        # Same projection as GET /v1/jobs/{id}, so a batch poll and a job poll
        # can never describe the same job differently.
        results=[_to_response(job) for job in jobs],
    )


@router.get(
    "/batches",
    response_model=BatchList,
    summary="List batches",
    description=(
        "Newest first, paginated, with per-batch completion counts. The counts "
        "are derived from the member jobs in a single grouped query, so they "
        "have the same never-stale guarantee as a poll. `limit` is capped at 100."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
    },
)
async def list_batches(
    request: Request,
    api_key: ApiKey,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Batches to skip."),
) -> BatchList:
    """Return a page of batches with their derived progress counts.

    Args:
        request: Incoming request.
        api_key: The caller's validated API key.
        session: Async database session.
        limit: Page size, 1 to 100.
        offset: Number of batches to skip.

    Returns:
        The page plus the total batch count.
    """
    total_result = await session.execute(select(func.count()).select_from(GenerationBatch))
    total = int(total_result.scalar_one())

    result = await session.execute(
        select(GenerationBatch)
        .order_by(GenerationBatch.created_at.desc(), GenerationBatch.id)
        .limit(limit)
        .offset(offset)
    )
    batches = list(result.scalars())

    # One grouped aggregate for the whole page rather than one query per batch:
    # a 100-row page must not cost 101 round trips. case() rather than
    # FILTER(...), which SQLite only gained in 3.30 and which the portable
    # spelling keeps off the upgrade path entirely.
    counts: dict[str, tuple[int, int, int]] = {}
    if batches:
        counts_result = await session.execute(
            select(
                GenerationJob.batch_id,
                func.count().label("total"),
                func.sum(case((GenerationJob.status.in_(SUCCESS_STATUSES), 1), else_=0)).label(
                    "completed"
                ),
                func.sum(case((GenerationJob.status == STATUS_FAILED, 1), else_=0)).label("failed"),
            )
            .where(GenerationJob.batch_id.in_([batch.id for batch in batches]))
            .group_by(GenerationJob.batch_id)
        )
        for batch_id, row_total, row_completed, row_failed in counts_result.all():
            counts[batch_id] = (int(row_completed or 0), int(row_failed or 0), int(row_total))

    items = [
        BatchListItem(
            batch_id=batch.id,
            completed=counts.get(batch.id, (0, 0, 0))[0],
            failed=counts.get(batch.id, (0, 0, 0))[1],
            # The stored total is authoritative for an empty count (a batch row
            # whose jobs were never committed); otherwise the derived total is
            # the same number the poll would report.
            total=counts.get(batch.id, (0, 0, batch.total_jobs))[2],
            created_at=batch.created_at,
        )
        for batch in batches
    ]
    return BatchList(items=items, total=total, limit=limit, offset=offset)
