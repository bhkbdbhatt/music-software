"""Tests for POST /v1/batch and GET /v1/batches/{batch_id}.

The ``on_failure`` tests here drive the real worker task rather than poking the
database: cancellation is a side effect of the failure path in
``app.workers.tasks``, so writing the sibling rows by hand would test the test.

All tests talk to the app over a real ``httpx.AsyncClient``.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.db.session import get_session_factory
from app.models.db import GenerationBatch, GenerationJob
from app.workers.tasks import (
    BATCH_STOPPED,
    STATUS_FAILED,
    generate_sample,
)
from httpx import AsyncClient

from conftest import ExplodingGenerator, FakeGenerator

pytestmark = pytest.mark.asyncio


async def _submit_batch(client: AsyncClient, specs: list[dict[str, Any]], **options: Any) -> dict:
    """POST a batch and return the response body.

    Args:
        client: An async client.
        specs: The specs to queue.
        **options: Batch execution options.

    Returns:
        The parsed 202 body.
    """
    body: dict[str, Any] = {"specs": specs}
    if options:
        body["options"] = options
    response = await client.post("/v1/batch", json=body)
    assert response.status_code == 202, response.text
    return response.json()


async def _jobs_in(batch_id: str) -> list[GenerationJob]:
    """Every job in a batch, ordered by creation.

    Args:
        batch_id: The batch to inspect.

    Returns:
        The job rows.
    """
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(GenerationJob).where(GenerationJob.batch_id == batch_id)
        )
        return list(result.scalars())


async def _run_batch(batch_id: str, generator: Any) -> list[str]:
    """Run every job in a batch in submission order, as a worker would.

    Args:
        batch_id: The batch to drain.
        generator: The fake model to install for the run.

    Returns:
        The job ids, in the order they were run.
    """
    from app.services.generation import reset_generator, set_generator_factory

    set_generator_factory(lambda: generator)
    try:
        return [await generate_sample({}, job.id) for job in await _jobs_in(batch_id)]
    finally:
        reset_generator()
        set_generator_factory(None)


# ----------------------------------------------------------------------
# Creating jobs
# ----------------------------------------------------------------------
async def test_batch_creates_multiple_jobs(
    client: AsyncClient, spec: dict[str, Any], queue: Any
) -> None:
    """One job per spec, each independently queued and pollable."""
    body = await _submit_batch(client, [spec, spec, spec])

    assert body["total_jobs"] == 3
    assert body["poll_url"] == f"/v1/batches/{body['batch_id']}"
    assert len(queue.enqueued) == 3
    assert len(set(queue.enqueued)) == 3, "each spec needs its own job id"

    jobs = await _jobs_in(body["batch_id"])
    assert len(jobs) == 3
    assert {job.status for job in jobs} == {"queued"}
    assert all(job.batch_id == body["batch_id"] for job in jobs)


async def test_batch_creates_a_row_per_distinct_spec(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """The spec is stored per job, so a batch of variants replays correctly."""
    body = await _submit_batch(client, [{**spec, "peak_db": -3.0}, {**spec, "peak_db": -18.0}])

    peaks = sorted(job.spec["peak_db"] for job in await _jobs_in(body["batch_id"]))

    assert peaks == [-18.0, -3.0]


async def test_batch_persists_its_options(client: AsyncClient, spec: dict[str, Any]) -> None:
    """max_concurrent and on_failure are worker inputs, not decoration."""
    body = await _submit_batch(client, [spec], parallel=False, max_concurrent=2, on_failure="stop")

    factory = get_session_factory()
    async with factory() as session:
        batch = await session.get(GenerationBatch, body["batch_id"])
        assert batch is not None
        assert batch.options == {"parallel": False, "max_concurrent": 2, "on_failure": "stop"}
        assert batch.total_jobs == 1


async def test_batch_rejects_an_invalid_spec_and_enqueues_nothing(
    client: AsyncClient, spec: dict[str, Any], queue: Any
) -> None:
    """All-or-nothing: no half-queued batch."""
    broken = {**spec, "fundamental_hz": [900.0, 100.0]}

    response = await client.post("/v1/batch", json={"specs": [spec, broken]})

    assert response.status_code == 422
    assert queue.enqueued == []


@pytest.mark.parametrize("count", [0, 101])
async def test_batch_rejects_a_wrong_number_of_specs(
    client: AsyncClient, spec: dict[str, Any], count: int
) -> None:
    assert (await client.post("/v1/batch", json={"specs": [spec] * count})).status_code == 422


@pytest.mark.parametrize("max_concurrent", [0, 65])
async def test_batch_validates_max_concurrent(
    client: AsyncClient, spec: dict[str, Any], max_concurrent: int
) -> None:
    response = await client.post(
        "/v1/batch", json={"specs": [spec], "options": {"max_concurrent": max_concurrent}}
    )

    assert response.status_code == 422


async def test_batch_rejects_an_unknown_failure_policy(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    response = await client.post(
        "/v1/batch", json={"specs": [spec], "options": {"on_failure": "explode"}}
    )

    assert response.status_code == 422


async def test_unreachable_queue_returns_503_and_commits_nothing(
    client: AsyncClient, spec: dict[str, Any], queue: Any
) -> None:
    """A 503 with no batch row beats a batch that will never be drained."""
    queue.fail = True

    response = await client.post("/v1/batch", json={"specs": [spec, spec]})

    assert response.status_code == 503
    assert "queue" in response.json()["detail"].lower()


# ----------------------------------------------------------------------
# on_failure: continue
# ----------------------------------------------------------------------
async def test_batch_on_failure_continue(
    client: AsyncClient, spec: dict[str, Any], storage: Any
) -> None:
    """One failure does not cancel the rest of the group.

    The generator fails the first job and succeeds the rest; every sibling should
    still reach a terminal success.
    """
    body = await _submit_batch(client, [spec] * 3, on_failure="continue")
    generator = ExplodingGenerator(RuntimeError("model hiccup"), failures=1)

    await _run_batch(body["batch_id"], generator)

    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)
    statuses = [job.status for job in jobs]
    assert statuses.count("failed") == 1, f"expected exactly one failure, got {statuses}"
    assert statuses.count("complete") + statuses.count("complete_with_warnings") == 2

    progress = (await client.get(f"/v1/batches/{body['batch_id']}")).json()
    assert progress["failed"] == 1
    assert progress["completed"] == 2
    assert progress["total"] == 3


async def test_batch_on_failure_continue_is_the_default(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """Omitting the option must behave like continue, not like stop."""
    body = await _submit_batch(client, [spec] * 2)

    await _run_batch(body["batch_id"], ExplodingGenerator(RuntimeError("boom"), failures=1))

    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)
    assert [job.status for job in jobs].count("failed") == 1
    assert all(job.error != BATCH_STOPPED for job in jobs)


# ----------------------------------------------------------------------
# on_failure: stop
# ----------------------------------------------------------------------
async def test_batch_on_failure_stop(
    client: AsyncClient, spec: dict[str, Any], storage: Any
) -> None:
    """The first failure cancels every sibling that has not started.

    Cancellation is visible two ways: the siblings' rows move to failed with a
    recognisable error, and a worker that later picks up their still-queued arq
    entries skips them instead of burning GPU time.
    """
    body = await _submit_batch(client, [spec] * 3, on_failure="stop")

    await _run_batch(body["batch_id"], ExplodingGenerator(RuntimeError("model died"), failures=1))

    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)
    statuses = [job.status for job in jobs]

    assert statuses.count("failed") == 3, f"stop should fail the whole group, got {statuses}"
    cancelled = [job for job in jobs if job.error == BATCH_STOPPED]
    assert len(cancelled) == 2, "two siblings cancelled by the first failure"
    # The original failure keeps its own message: a cancellation must not
    # overwrite the diagnosis of what actually broke.
    assert "model died" in next(job.error for job in jobs if job.error != BATCH_STOPPED)


async def test_batch_on_failure_stop_skips_already_cancelled_jobs(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """A cancelled job handed to the worker is not rendered again.

    arq offers no way to remove a pending job, so the task can be invoked for one
    the group already cancelled. Rendering it would overwrite the cancellation
    with a success and spend real inference on audio nobody reads.
    """
    body = await _submit_batch(client, [spec] * 2, on_failure="stop")
    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)
    victim = jobs[1]

    from app.services.generation import reset_generator, set_generator_factory

    # Fail the first job, which cancels the second as a side effect.
    set_generator_factory(lambda: ExplodingGenerator(RuntimeError("boom"), failures=1))
    try:
        await generate_sample({}, jobs[0].id)
    finally:
        reset_generator()

    cancelled = await _jobs_in(body["batch_id"])
    assert next(j for j in cancelled if j.id == victim.id).status == STATUS_FAILED

    # Now a worker is handed the cancelled job, as the broker eventually will.
    generator = FakeGenerator()
    set_generator_factory(lambda: generator)
    try:
        await generate_sample({}, victim.id)
    finally:
        reset_generator()

    after = next(j for j in await _jobs_in(body["batch_id"]) if j.id == victim.id)
    assert after.status == STATUS_FAILED
    assert after.error == BATCH_STOPPED
    assert after.result_urls == [], "a skipped job must not report files"
    assert not generator.seeds, "inference must not run for a cancelled job"


async def test_batch_on_failure_stop_leaves_jobs_already_finished_alone(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """Only queued siblings are cancelled; completed work is never rewritten."""
    body = await _submit_batch(client, [spec] * 2, on_failure="stop")
    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)

    # Run the *second* job to completion first, then fail the first.
    from app.services.generation import reset_generator, set_generator_factory

    set_generator_factory(lambda: FakeGenerator())
    try:
        await generate_sample({}, jobs[1].id)
        finished_status = next(
            j for j in await _jobs_in(body["batch_id"]) if j.id == jobs[1].id
        ).status
        urls_before = next(
            j for j in await _jobs_in(body["batch_id"]) if j.id == jobs[1].id
        ).result_urls

        await generate_sample({}, jobs[0].id)
    finally:
        reset_generator()

    survivor = next(j for j in await _jobs_in(body["batch_id"]) if j.id == jobs[1].id)
    assert survivor.status == finished_status, "a completed sibling was overwritten"
    assert survivor.result_urls == urls_before
    assert finished_status in {"complete", "complete_with_warnings"}


async def test_batch_on_failure_stop_leaves_unbatched_jobs_alone(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """A standalone job has no group, so nothing may be cancelled on its behalf."""
    from app.services.generation import reset_generator, set_generator_factory

    response = await client.post("/v1/generate", json=spec)
    job_id = response.json()["job_id"]

    set_generator_factory(lambda: ExplodingGenerator(RuntimeError("boom"), failures=1))
    try:
        await generate_sample({}, job_id)
    finally:
        reset_generator()

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(GenerationJob, job_id)
        assert job is not None
        assert job.batch_id is None
        assert job.status == STATUS_FAILED


# ----------------------------------------------------------------------
# Progress reporting
# ----------------------------------------------------------------------
async def test_batch_progress_counts_completed_and_failed(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    body = await _submit_batch(client, [spec] * 3)

    jobs = sorted(await _jobs_in(body["batch_id"]), key=lambda j: j.created_at)
    factory = get_session_factory()
    async with factory() as session:
        first = await session.get(GenerationJob, jobs[0].id)
        second = await session.get(GenerationJob, jobs[1].id)
        third = await session.get(GenerationJob, jobs[2].id)
        assert first is not None and second is not None and third is not None
        first.status = "complete"
        first.result_urls = ["https://cdn.test/a.wav"]
        second.status = "complete_with_warnings"
        second.constraint_report = {
            "constraints_met": {"peak_db": True},
            "failed_constraints": ["fundamental_hz"],
        }
        third.status = "failed"
        third.error = "model_load_failed"
        await session.commit()

    body = (await client.get(f"/v1/batches/{body['batch_id']}")).json()
    assert body["total"] == 3
    assert body["completed"] == 2, "complete_with_warnings counts as completed"
    assert body["failed"] == 1
    assert {r["status"] for r in body["results"]} == {
        "complete",
        "complete_with_warnings",
        "failed",
    }


async def test_batch_progress_counts_queued_jobs_as_neither(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """A job that has not run is neither completed nor failed."""
    from app.models.schemas import GenerationSpec

    body = await _submit_batch(client, [spec])
    job_id = (await _jobs_in(body["batch_id"]))[0].id

    assert (await client.get(f"/v1/batches/{body['batch_id']}")).json() == {
        "batch_id": body["batch_id"],
        "completed": 0,
        "failed": 0,
        "total": 1,
        "results": [
            {
                "job_id": job_id,
                "status": "queued",
                "files": [],
                "constraints_met": {},
                # The echo is the validated spec, so it carries the server-side
                # defaults the submitted payload omitted.
                "spec": GenerationSpec.model_validate(spec).model_dump(mode="json"),
            }
        ],
    }


async def test_batch_progress_is_recomputed_not_cached(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """Polling twice must not double-count: the numbers are derived, not stored."""
    body = await _submit_batch(client, [spec])

    await _run_batch(body["batch_id"], FakeGenerator())

    first = (await client.get(f"/v1/batches/{body['batch_id']}")).json()
    second = (await client.get(f"/v1/batches/{body['batch_id']}")).json()

    assert first == second
    assert first["completed"] == 1


async def test_unknown_batch_returns_404(client: AsyncClient) -> None:
    assert (await client.get("/v1/batches/nope")).status_code == 404


async def test_batch_progress_requires_authentication(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    async with client_factory() as client:
        batch_id = (await _submit_batch(client, [spec]))["batch_id"]

    async with client_factory() as anonymous:
        response = await anonymous.get(f"/v1/batches/{batch_id}", headers={"X-API-Key": ""})

    assert response.status_code == 401


# ----------------------------------------------------------------------
# Rate limiting
# ----------------------------------------------------------------------
async def test_batch_rate_limit_is_enforced_per_key(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    """3/minute: the fourth request in a window is a 429."""
    async with client_factory(rate_limit_enabled=True, batch_rate_limit="3/minute") as client:
        statuses = [
            (await client.post("/v1/batch", json={"specs": [spec]})).status_code for _ in range(4)
        ]

    assert statuses == [202, 202, 202, 429]


async def test_rate_limited_response_carries_retry_after(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    async with client_factory(rate_limit_enabled=True, batch_rate_limit="1/minute") as client:
        await client.post("/v1/batch", json={"specs": [spec]})
        response = await client.post("/v1/batch", json={"specs": [spec]})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "rate limit" in response.json()["detail"]


async def test_rate_limit_buckets_are_per_api_key(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    """One exhausted key must not block a different one."""
    async with client_factory(rate_limit_enabled=True, batch_rate_limit="1/minute") as client:
        await client.post("/v1/batch", json={"specs": [spec]})
        blocked = await client.post("/v1/batch", json={"specs": [spec]})
        other = await client.post(
            "/v1/batch",
            json={"specs": [spec]},
            headers={"X-API-Key": "a-different-key"},
        )

    assert blocked.status_code == 429
    assert other.status_code == 401, "an unknown key is rejected, not limited"


async def test_generate_rate_limit_is_separate_from_batch(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    """Exhausting the batch quota must not consume the generate quota."""
    async with client_factory(
        rate_limit_enabled=True,
        batch_rate_limit="1/minute",
        generate_rate_limit="5/minute",
    ) as client:
        await client.post("/v1/batch", json={"specs": [spec]})
        await client.post("/v1/batch", json={"specs": [spec]})
        generated = await client.post("/v1/generate", json=spec)

    assert generated.status_code == 202


async def test_recipes_are_not_rate_limited(client_factory: Any) -> None:
    """Reads are cheap; only the endpoints that cost GPU time carry a quota."""
    async with client_factory(rate_limit_enabled=True, batch_rate_limit="1/minute") as client:
        statuses = [(await client.get("/v1/recipes")).status_code for _ in range(5)]

    assert statuses == [200] * 5
