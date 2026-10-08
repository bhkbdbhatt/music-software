"""The arq task that renders a generation job end to end.

One job in, one or more stored files out:

1. load the job row and its spec
2. render one variant per batch item, each from its own seed
3. enforce the spec's hard constraints on every variant
4. encode to the requested format
5. upload and record the URLs
6. mark the job ``complete``, ``complete_with_warnings``, or ``failed``

Design notes worth knowing before changing anything here:

**Everything CPU-bound goes to a thread.** Inference, constraint enforcement,
and encoding are all CPU/GPU work; running any of them on the event loop would
stall every other job in the worker. :func:`asyncio.to_thread` is used for this
— the same mechanism as Starlette's ``run_in_threadpool``, without depending on
Starlette in a process that has no HTTP server.

**Failures are classified, not just caught.** A missing checkpoint and a
transient S3 503 are both exceptions, but retrying the first wastes GPU time
forever while retrying the second is the whole point of the retry policy. See
:func:`_is_transient`.

**Constraint misses are not failures.** The job still delivers audio and is
marked ``complete_with_warnings`` with the failing constraints named. A caller
that wants only flawless variants checks ``constraints_met``; one that wants
"the file no matter what" gets the file.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import bind_context, clear_context, get_logger
from app.db.session import get_session_factory
from app.generation.base import GenerationError, ModelLoadError
from app.models.db import GenerationBatch, GenerationJob
from app.models.schemas import (
    STATUS_COMPLETE,
    STATUS_COMPLETE_WITH_WARNINGS,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    TERMINAL_STATUSES,
    GenerationSpec,
)
from app.services.constraint import ConstraintReport, enforce_constraints, violations
from app.services.encoding import encode_audio
from app.services.generation import get_generator
from app.services.storage import (
    Storage,
    TransientStorageError,
    build_key,
    content_type_for,
    get_storage,
)

log = get_logger(__name__)

T = TypeVar("T")

#: Seed range. Kept inside int32 so generators can use it without surprises.
_SEED_MODULUS = 2**31 - 1

#: Longest error string stored on a job row.
_MAX_ERROR_LENGTH = 1024

#: Error recorded when the generator's weights cannot be loaded.
MODEL_LOAD_FAILED = "model_load_failed"

#: Error recorded when a job id does not exist.
JOB_NOT_FOUND = "job_not_found"

#: Error recorded on siblings cancelled by a ``on_failure="stop"`` batch.
BATCH_STOPPED = "batch_stopped_by_sibling_failure"

#: Batch failure policy: cancel the rest of the group.
ON_FAILURE_STOP = "stop"


#: arq's worker context: whatever ``on_startup`` left behind, or a Redis handle
#: in some deployments. Typed as a mapping because the task does not read it —
#: the point is to keep arq's calling convention explicit without pinning a
#: version-specific type that is not part of arq's public API.
JobContext = dict[str, object]


class TransientJobError(RuntimeError):
    """A failure that exhausted its retries.

    Raised once the retry budget is spent, so the caller sees one exception type
    regardless of how many attempts were made.
    """


@dataclass(frozen=True, slots=True)
class RenderedVariant:
    """One finished variant of a job, before it is written to the job row."""

    index: int
    seed: int
    key: str
    url: str
    size_bytes: int
    report: ConstraintReport
    failed_constraints: tuple[str, ...]


# ----------------------------------------------------------------------
# Seeding
# ----------------------------------------------------------------------
def derive_seed(base_seed: int, variant: int, diversity: float) -> int:
    """Pick the seed for one variant of a batch.

    ``diversity == 0`` returns ``base_seed`` for every variant, which is the
    only way to honour "0 = identical": the generator is seeded, so the same
    seed is the same audio. Any non-zero diversity draws an independent seed,
    and the *magnitude* of the diversity is applied inside the generator, which
    reads ``spec.diversity`` — the seed alone cannot express "a bit different"
    versus "completely different", because any two distinct seeds are equally
    unrelated as far as a diffusion or VAE sampler is concerned.

    Deterministic in all three arguments, so a job can be replayed exactly.

    Args:
        base_seed: The job's seed.
        variant: Zero-based index within the batch.
        diversity: ``spec.diversity``, 0 to 1.

    Returns:
        A seed in ``[0, 2**31 - 1]``.
    """
    if diversity <= 0.0:
        return base_seed % _SEED_MODULUS
    rng = random.Random(f"{base_seed}:{variant}")
    return rng.randrange(0, _SEED_MODULUS)


# ----------------------------------------------------------------------
# Retry policy
# ----------------------------------------------------------------------
def _is_transient(exc: BaseException) -> bool:
    """Whether an exception is worth retrying.

    Retries transient network and storage failures, plus the timeouts and
    connection resets that surface as :class:`OSError`. Deliberately *not*
    retried: :class:`ModelLoadError` (a bad checkpoint will still be bad),
    :class:`GenerationError` (a rejected input will be rejected again), and
    :class:`ValueError` (a bad spec or bad audio is the caller's problem).

    Args:
        exc: The exception just raised.

    Returns:
        ``True`` if the operation should be retried.
    """
    if isinstance(exc, TransientStorageError):
        return True
    if isinstance(exc, (ModelLoadError, GenerationError, ValueError)):
        return False
    return isinstance(exc, OSError | TimeoutError)


def retry_delay(attempt: int) -> float:
    """Backoff delay before retry number ``attempt`` (1-based), in seconds.

    Exponential from ``retry_base_delay_seconds``, capped at
    ``retry_max_delay_seconds``, with +/-10% jitter so a batch of jobs that
    failed together does not retry in lockstep.

    Args:
        attempt: The attempt that just failed, counting from 1.

    Returns:
        Seconds to wait before the next attempt.
    """
    delay = settings.retry_base_delay_seconds * (2 ** (attempt - 1))
    delay = min(delay, settings.retry_max_delay_seconds)
    return delay * random.uniform(0.9, 1.1)


async def _with_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    description: str,
    job_id: str,
) -> T:
    """Run an async operation, retrying transient failures with backoff.

    Args:
        operation: Zero-argument callable returning an awaitable.
        description: What is being attempted, for logs and error messages.
        job_id: The job, for logging.

    Returns:
        The operation's result.

    Raises:
        TransientJobError: If every attempt failed with a transient error.
        Exception: The last exception, unchanged, if it was not transient.
    """
    attempts = settings.job_max_attempts
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if not _is_transient(exc):
                raise
            if attempt >= attempts:
                raise TransientJobError(
                    f"{description} failed after {attempts} attempts: {exc}"
                ) from exc
            delay = retry_delay(attempt)
            log.warning(
                "retrying",
                job_id=job_id,
                description=description,
                attempt=attempt,
                delay_s=round(delay, 3),
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable: retry loop exited without a result")


# ----------------------------------------------------------------------
# Job persistence
# ----------------------------------------------------------------------
async def _load_job(job_id: str) -> GenerationJob | None:
    """Fetch a job row, or ``None`` if it does not exist."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        return result.scalar_one_or_none()


async def _update_job(job_id: str, **fields: Any) -> None:
    """Apply field updates to a job row in its own transaction.

    Args:
        job_id: The job to update.
        **fields: Column values to set. ``None`` values are written as-is, so a
            field can be cleared.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(GenerationJob, job_id)
        if job is None:
            raise LookupError(f"job {job_id} disappeared mid-flight")
        for key, value in fields.items():
            setattr(job, key, value)
        await session.commit()


async def _stop_siblings(job_id: str) -> int:
    """Cancel the rest of a batch when it is configured to stop on failure.

    Only meaningful for jobs that belong to a batch whose ``on_failure`` option
    is ``"stop"``. Siblings still sitting at ``queued`` are moved to ``failed``;
    one already ``processing`` in another worker is left alone, because killing
    it is not this worker's decision and its result would race this write.

    Cancelling the queue entry itself is deliberately not attempted: arq has no
    supported "remove this pending job" call, and the DB row is what every poll
    reads. Marking the row is the reliable half of the operation, and the task
    skips jobs that are already terminal when it picks them up.

    Args:
        job_id: The job that just failed.

    Returns:
        How many sibling rows were cancelled.
    """
    factory = get_session_factory()
    async with factory() as session:
        failed_job = await session.get(GenerationJob, job_id)
        if failed_job is None or failed_job.batch_id is None:
            return 0

        batch = await session.get(GenerationBatch, failed_job.batch_id)
        if batch is None:
            return 0
        options = batch.options or {}
        if options.get("on_failure") != ON_FAILURE_STOP:
            return 0

        result = await session.execute(
            select(GenerationJob).where(
                GenerationJob.batch_id == failed_job.batch_id,
                GenerationJob.id != job_id,
                GenerationJob.status == STATUS_QUEUED,
            )
        )
        siblings = list(result.scalars())
        for sibling in siblings:
            sibling.status = STATUS_FAILED
            sibling.error = BATCH_STOPPED
        if siblings:
            await session.commit()
            log.warning(
                "batch_stopped",
                batch_id=failed_job.batch_id,
                failed_job_id=job_id,
                cancelled=len(siblings),
            )
        return len(siblings)


async def _mark_failed(
    job_id: str,
    error: str,
    variants: list[RenderedVariant] | None = None,
) -> None:
    """Record a terminal failure.

    Any variants that did render are kept on the row. Their audio is already in
    storage, so discarding the URLs would throw away the only evidence of what
    went wrong — and a batch that failed on its fourth variant is worth reading
    the first three of.

    Args:
        job_id: The job to fail.
        error: Human-readable cause, truncated to the column's width.
        variants: Variants completed before the failure.
    """
    message = error[:_MAX_ERROR_LENGTH]
    log.error("job_failed", job_id=job_id, error=message)
    fields: dict[str, Any] = {"status": STATUS_FAILED, "error": message}
    if variants:
        fields["result_urls"] = [variant.url for variant in variants]
        fields["constraint_report"] = {
            "variants": [
                {
                    "index": variant.index,
                    "seed": variant.seed,
                    "failed_constraints": list(variant.failed_constraints),
                    "measurements": {
                        name: dict(measurement) for name, measurement in variant.report.items()
                    },
                }
                for variant in variants
            ],
            "constraints_met": {},
            "failed_constraints": sorted(
                {name for variant in variants for name in variant.failed_constraints}
            ),
        }
    await _update_job(job_id, **fields)

    # Cancellation is part of failing: a "stop" batch is defined by the first
    # failure taking the rest of the group with it.
    await _stop_siblings(job_id)


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
async def _render_variant(
    *,
    spec: GenerationSpec,
    variant: int,
    seed: int,
    generator: Any,
    storage: Storage,
    job_id: str,
) -> RenderedVariant:
    """Render, constrain, encode, and upload one variant.

    Steps 3 to 6 of the job flow. The blocking stages are handed to worker
    threads so the event loop stays free for other jobs.

    Args:
        spec: The job's validated spec.
        variant: Zero-based batch index.
        seed: Seed for this variant, from :func:`derive_seed`.
        generator: A loaded generator.
        storage: Where the encoded file goes.
        job_id: The job, for keys and logging.

    Returns:
        The stored variant, including its constraint report.

    Raises:
        TransientJobError: If a transient failure outlived its retries.
        GenerationError: If inference failed.
        ValueError: If encoding was handed unusable audio.
    """
    log.info("variant_start", job_id=job_id, variant=variant, seed=seed)

    # --- 3. generate (CPU/GPU-bound, off the loop) -----------------------
    raw_audio = await _with_retries(
        lambda: _generate_in_thread(generator, spec, seed),
        description=f"generate(variant={variant})",
        job_id=job_id,
    )

    # --- 4. constraint enforcement --------------------------------------
    sr = spec.sample_rate
    processed, report = await asyncio.to_thread(enforce_constraints, raw_audio, sr, spec)
    failed = tuple(violations(report))
    if failed:
        # Not an error: the file is still delivered, and the caller decides
        # whether a constraint miss makes it unusable.
        log.warning(
            "variant_constraints_unmet",
            job_id=job_id,
            variant=variant,
            constraints=list(failed),
        )

    # --- 5. encode -------------------------------------------------------
    data = await asyncio.to_thread(encode_audio, processed, sr, spec)

    # --- 6. upload -------------------------------------------------------
    key = build_key(job_id, variant, spec.format)

    async def _upload() -> Any:
        return await storage.upload(key, data, content_type=content_type_for(spec.format))

    stored = await _with_retries(_upload, description=f"upload(variant={variant})", job_id=job_id)

    log.info(
        "variant_done",
        job_id=job_id,
        variant=variant,
        url=stored.url,
        size_bytes=stored.size_bytes,
    )
    return RenderedVariant(
        index=variant,
        seed=seed,
        key=stored.key,
        url=stored.url,
        size_bytes=stored.size_bytes,
        report=report,
        failed_constraints=failed,
    )


async def _generate_in_thread(generator: Any, spec: GenerationSpec, seed: int) -> Any:
    """Await ``generator.generate`` from a worker thread.

    Inference is synchronous PyTorch work behind an async interface. Handing it
    to :func:`asyncio.to_thread` keeps it off the job's event loop; because a
    coroutine may only be awaited by the loop that created it, this driver
    starts a private loop on the worker thread and runs the coroutine there.

    The coroutine is created inside the thread rather than passed in, so it is
    bound to the loop that will run it.

    Args:
        generator: The loaded generator.
        spec: The job's spec.
        seed: Seed for this variant.

    Returns:
        The raw rendered audio.
    """

    async def _run() -> Any:
        return await generator.generate(spec, seed=seed)

    return await asyncio.to_thread(lambda: asyncio.run(_run()))


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
async def generate_sample(ctx: JobContext, job_id: str) -> str:
    """arq entry point: render one generation job.

    Registered in :mod:`app.workers.queue` and enqueued by the API.

    Args:
        ctx: arq's context object. Unused today; kept as the arq contract and
            the place to reach job metadata.
        job_id: The job to run.

    Returns:
        The job id, on success.

    Raises:
        ValueError: If ``job_id`` is unknown. This is a client error, so it is
            raised rather than recorded on a row that does not exist; arq's
            ``max_tries`` still applies.
    """
    bind_context(job_id=job_id)
    try:
        log.info("job_start")

        # --- 1 & 2. load the job and its spec -----------------------------
        job = await _load_job(job_id)
        if job is None:
            log.error("job_missing")
            raise ValueError(f"unknown job: {job_id}")

        # Already terminal. A "stop" batch cancels siblings by writing `failed`
        # to their rows while their arq entries are still queued, and arq has no
        # way to remove a pending job — so this task can legitimately be handed
        # a job that a sibling already cancelled. Rendering it would spend GPU
        # time producing audio nobody will read, and would overwrite the
        # cancellation with a success.
        if job.status in TERMINAL_STATUSES:
            log.info("job_skipped_already_terminal", status=job.status)
            return job_id

        spec = GenerationSpec.model_validate(job.spec)
        batch_size = min(job.batch_size or spec.batch_size, settings.max_batch_size)
        await _update_job(job_id, status=STATUS_PROCESSING, error=None)
        log.info(
            "job_processing",
            category=spec.category,
            format=spec.format,
            batch_size=batch_size,
            diversity=spec.diversity,
        )

        # --- model load: failure here is its own error code --------------
        try:
            generator = await get_generator()
        except ModelLoadError as exc:
            await _mark_failed(job_id, MODEL_LOAD_FAILED)
            log.error("model_load_failed", error=str(exc))
            return job_id

        storage = get_storage()

        # --- 8. batch loop ------------------------------------------------
        variants: list[RenderedVariant] = []
        for index in range(batch_size):
            seed = derive_seed(job.base_seed, index, spec.diversity)
            try:
                variants.append(
                    await _render_variant(
                        spec=spec,
                        variant=index,
                        seed=seed,
                        generator=generator,
                        storage=storage,
                        job_id=job_id,
                    )
                )
            except (GenerationError, ModelLoadError) as exc:
                # A variant that cannot be rendered fails the whole job: a
                # half-delivered batch is worse than an explicit failure.
                await _mark_failed(job_id, str(exc) or type(exc).__name__, variants)
                return job_id
            except Exception as exc:
                # Last line of defence: an unexpected error from encoding,
                # storage, or the constraint pipeline must still leave the job
                # in a terminal state with a diagnosable message, rather than
                # leaving it stuck on "processing" for ever. The type name is
                # included because the message alone is often empty.
                await _mark_failed(
                    job_id,
                    str(exc) or type(exc).__name__,
                    variants,
                )
                log.exception("variant_failed_unexpectedly", variant=index)
                return job_id

        # --- 7. record the outcome ---------------------------------------
        all_failed = sorted({name for variant in variants for name in variant.failed_constraints})
        status = STATUS_COMPLETE_WITH_WARNINGS if all_failed else STATUS_COMPLETE
        await _update_job(
            job_id,
            status=status,
            result_urls=[variant.url for variant in variants],
            constraint_report={
                "variants": [
                    {
                        "index": variant.index,
                        "seed": variant.seed,
                        "failed_constraints": list(variant.failed_constraints),
                        "measurements": {
                            name: dict(measurement) for name, measurement in variant.report.items()
                        },
                    }
                    for variant in variants
                ],
                "constraints_met": {
                    name: name not in all_failed for name in _constraint_names(variants)
                },
                "failed_constraints": all_failed,
            },
            error=None,
        )
        log.info(
            "job_done",
            status=status,
            variants=len(variants),
            failed_constraints=all_failed,
        )
        return job_id
    finally:
        clear_context()


def _constraint_names(variants: list[RenderedVariant]) -> set[str]:
    """Every constraint name reported across a batch."""
    return {name for variant in variants for name in variant.report}
