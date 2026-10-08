"""Job status and history.

``GET /v1/jobs/{job_id}`` — the poll target of ``POST /v1/generate``.
``GET /v1/jobs`` — recent jobs, newest first.

Polls are always 200, even for a failed job: "the job failed" is an answer to
the question, not a failed request. Only an unknown id is a 404.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.core.security import ApiKey
from app.db.session import SessionDep
from app.models.db import GenerationJob
from app.models.schemas import (
    TERMINAL_STATUSES,
    GeneratedFile,
    GenerationResponse,
    GenerationSpec,
    JobList,
    JobListItem,
    JobStatus,
)

log = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _public_url(job_id: str, index: int, url: str) -> str:
    """Make one stored result URL fetchable by an API client.

    The local storage backend records ``file://`` URIs, which are paths on the
    *server's* filesystem and meaningless to a browser. Those are rewritten to
    the public file route; S3/HTTPS URLs are already fetchable and pass through
    untouched.

    Args:
        job_id: The job the variant belongs to.
        index: Zero-based position of the variant in ``result_urls``.
        url: The stored URL.

    Returns:
        A URL the client can GET.
    """
    if url.startswith("file://"):
        return f"/v1/files/{job_id}/{index}"
    return url


def _to_response(job: GenerationJob) -> GenerationResponse:
    """Project a job row onto the public response model.

    The worker's ``constraint_report`` holds per-variant measurements; the
    response's ``constraints_met`` is the flattened verdict across the batch.
    Files are only listed for a finished job — while one is queued or rendering
    the URLs are not there to give, and an empty list is the honest answer.
    The stored spec is echoed back so a client can rebuild constraint overlays
    without having kept its own copy of the request.
    """
    report = job.constraint_report or {}
    constraints_met: dict[str, bool] = dict(report.get("constraints_met") or {})
    files = (
        [
            GeneratedFile(url=_public_url(job.id, index, url))
            for index, url in enumerate(job.result_urls)
        ]
        if job.status in TERMINAL_STATUSES
        else []
    )
    try:
        spec: GenerationSpec | None = GenerationSpec.model_validate(job.spec)
    except ValidationError:
        # A spec written before a schema change: the job still polls fine, it
        # just cannot echo a document that no longer describes a valid request.
        log.warning("job_spec_no_longer_valid", job_id=job.id)
        spec = None
    return GenerationResponse(
        job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        files=files,
        constraints_met=constraints_met,
        spec=spec,
    )


def _to_list_item(job: GenerationJob) -> JobListItem:
    """Project a job row onto the list model.

    Args:
        job: The row to project.

    Returns:
        The poll response plus the row's batch/recipe links and timestamps.
    """
    base = _to_response(job)
    return JobListItem(
        **base.model_dump(),
        batch_id=job.batch_id,
        recipe_id=job.recipe_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get(
    "/{job_id}",
    response_model=GenerationResponse,
    summary="Poll a generation job",
    description=(
        "Returns the job's current status. While `queued` or `processing` the "
        "`files` list is empty. On `complete` or `complete_with_warnings` it "
        "carries every rendered variant's URL plus `constraints_met`, the "
        "per-constraint pass/fail map."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_404_NOT_FOUND: {"description": "No such job."},
    },
)
async def get_job(
    request: Request,
    job_id: str,
    api_key: ApiKey,
    session: SessionDep,
) -> GenerationResponse:
    """Return a job's status and, once finished, its result.

    Args:
        request: Incoming request.
        job_id: The job to look up.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The job's current state.

    Raises:
        HTTPException: 404 if the job does not exist.
    """
    job = await session.get(GenerationJob, job_id)
    if job is None:
        log.info("job_not_found", job_id=job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown job: {job_id}")
    return _to_response(job)


@router.get(
    "",
    response_model=JobList,
    summary="List recent jobs",
    description=(
        "Newest first, paginated, optionally filtered by status. Each item "
        "carries the echoed spec, the constraint verdict, and file URLs for "
        "finished jobs — everything a dashboard or library needs to render a "
        "job without a second request per row. `limit` is capped at 100."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
    },
)
async def list_jobs(
    request: Request,
    api_key: ApiKey,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Jobs to skip."),
    job_status: JobStatus | None = Query(
        default=None,
        alias="status",
        description="Only return jobs in this state.",
    ),
) -> JobList:
    """Return a page of generation jobs.

    Args:
        request: Incoming request.
        api_key: The caller's validated API key.
        session: Async database session.
        limit: Page size, 1 to 100.
        offset: Number of jobs to skip.
        job_status: Optional status filter, read from the ``status`` query
            parameter (``job_status`` would shadow nothing here, but the wire
            name is what clients expect).

    Returns:
        The page plus the total job count matching the filter.
    """
    query = select(GenerationJob)
    count_query = select(func.count()).select_from(GenerationJob)
    if job_status is not None:
        query = query.where(GenerationJob.status == job_status)
        count_query = count_query.where(GenerationJob.status == job_status)

    total_result = await session.execute(count_query)
    total = int(total_result.scalar_one())

    result = await session.execute(
        query.order_by(GenerationJob.created_at.desc(), GenerationJob.id)
        .limit(limit)
        .offset(offset)
    )
    items = [_to_list_item(job) for job in result.scalars()]
    return JobList(items=items, total=total, limit=limit, offset=offset)
