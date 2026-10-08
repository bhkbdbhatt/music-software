"""arq worker configuration.

Run with ``arq app.workers.queue.WorkerSettings``. The same settings object is
used by the API in tests to run tasks inline, which is why ``generate_sample``
is registered here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging
from app.workers.tasks import JobContext, generate_sample


async def startup(ctx: JobContext) -> None:
    """Prepare the worker process.

    Configures logging and creates the job table when running against SQLite in
    development; production relies on Alembic migrations instead.
    """
    configure_logging()
    if settings.database_url.startswith("sqlite"):
        from app.db.session import create_all

        await create_all()


async def shutdown(ctx: JobContext) -> None:
    """Release process resources on worker shutdown."""
    from app.db.session import dispose_engine
    from app.services.generation import reset_generator

    reset_generator()
    await dispose_engine()


class WorkerSettings:
    """arq's settings object: what to run, and where to run it."""

    # arq reads these off the class, so they stay as class attributes; the list
    # is never mutated, hence the ClassVar annotation rather than a plain one.
    functions: ClassVar[list[Callable[..., Coroutine[Any, Any, Any]]]] = [generate_sample]
    on_startup: ClassVar[Callable[[JobContext], Coroutine[Any, Any, None]]] = startup
    on_shutdown: ClassVar[Callable[[JobContext], Coroutine[Any, Any, None]]] = shutdown
    # Three attempts is the retry budget inside the task; arq's own max_tries
    # adds process-level recovery (a worker killed mid-job) on top of it.
    max_tries: ClassVar[int] = 3
    job_timeout: ClassVar[int] = 900
    keep_result: ClassVar[int] = 3600
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)


async def enqueue_job(job_id: str) -> str | None:
    """Queue a generation job for a worker.

    Called by the API, which has no business holding a worker-side connection
    of its own. Opens a short-lived pool per call: the API enqueues far less
    often than the worker dequeues, and a long-lived pool here would be one
    more thing to leak on shutdown.

    Args:
        job_id: The job to run.

    Returns:
        The arq job id, which for arq is the caller's ``job_id`` argument.

    Raises:
        ConnectionError: If Redis cannot be reached. Callers have already
            committed the job row by this point, so they mark it failed rather
            than leaving a job queued that nothing will ever pick up.
            ``ConnectionError`` is deliberate: it is the classification the
            worker's own retry policy already treats as transient, so one
            vocabulary covers both layers.
    """
    from arq import create_pool

    try:
        pool = await create_pool(WorkerSettings)
    except Exception as exc:  # redis errors, DNS failures, auth failures
        raise ConnectionError(f"could not reach the arq broker: {exc}") from exc
    try:
        job = await pool.enqueue_job("generate_sample", job_id)
        return job.job_id
    finally:
        await pool.aclose()
