"""Tests for GET /v1/batches — the batch list.

The interesting assertion is that the derived counts match what a poll of the
same batch reports: a list that disagrees with the detail view is worse than no
list at all. Rows are created directly so the statuses are exact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db.session import get_session_factory
from app.models.db import GenerationBatch, GenerationJob
from app.models.schemas import GenerationSpec
from httpx import AsyncClient

from conftest import spec_payload

pytestmark = pytest.mark.asyncio


async def _make_batch(
    *,
    job_statuses: list[str] | None = None,
    created_at: datetime | None = None,
    stored_total: int | None = None,
) -> str:
    """Insert a batch row and (optionally) its jobs.

    Args:
        job_statuses: Statuses for the member jobs; ``None`` creates a batch
            row with no jobs at all.
        created_at: Creation time for the batch; defaults to "now".
        stored_total: Overrides the batch's own ``total_jobs`` column, for the
            "jobs never committed" edge case.

    Returns:
        The batch id.
    """
    statuses = job_statuses or []
    batch_id = uuid.uuid4().hex
    stamp = created_at or datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            GenerationBatch(
                id=batch_id,
                total_jobs=stored_total if stored_total is not None else len(statuses),
                created_at=stamp,
            )
        )
        for status in statuses:
            session.add(
                GenerationJob(
                    id=uuid.uuid4().hex,
                    status=status,
                    spec=GenerationSpec.model_validate(spec_payload()).model_dump(mode="json"),
                    batch_size=1,
                    base_seed=0,
                    batch_id=batch_id,
                    result_urls=[],
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
        await session.commit()
    return batch_id


async def test_list_requires_an_api_key(client_factory: Any) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        assert (await anonymous.get("/v1/batches")).status_code == 401


async def test_list_is_empty_on_a_fresh_database(client: AsyncClient) -> None:
    body = (await client.get("/v1/batches")).json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_reports_derived_counts(client: AsyncClient) -> None:
    batch_id = await _make_batch(
        job_statuses=["complete", "complete_with_warnings", "failed", "processing"]
    )

    body = (await client.get("/v1/batches")).json()
    item = body["items"][0]

    assert item["batch_id"] == batch_id
    assert (item["completed"], item["failed"], item["total"]) == (2, 1, 4)


async def test_counts_agree_with_a_poll(client: AsyncClient) -> None:
    """The list and the detail view must never describe the same batch apart."""
    batch_id = await _make_batch(job_statuses=["complete", "failed", "queued"])

    listed = (await client.get("/v1/batches")).json()["items"][0]
    polled = (await client.get(f"/v1/batches/{batch_id}")).json()

    assert (listed["completed"], listed["failed"], listed["total"]) == (
        polled["completed"],
        polled["failed"],
        polled["total"],
    )


async def test_list_returns_batches_newest_first(client: AsyncClient) -> None:
    await _make_batch(job_statuses=["queued"], created_at=datetime(2026, 1, 1, tzinfo=UTC))
    newest = await _make_batch(job_statuses=["queued"], created_at=datetime(2026, 6, 1, tzinfo=UTC))

    body = (await client.get("/v1/batches")).json()

    assert next(item["batch_id"] for item in body["items"]) == newest


async def test_list_paginates(client: AsyncClient) -> None:
    for day in (1, 2, 3):
        await _make_batch(job_statuses=["queued"], created_at=datetime(2026, 1, day, tzinfo=UTC))

    first = (await client.get("/v1/batches?limit=2")).json()
    second = (await client.get("/v1/batches?limit=2&offset=2")).json()

    assert len(first["items"]) == 2 and first["total"] == 3
    assert len(second["items"]) == 1


async def test_list_rejects_an_oversized_page(client: AsyncClient) -> None:
    assert (await client.get("/v1/batches?limit=101")).status_code == 422


async def test_batch_without_jobs_falls_back_to_the_stored_total(
    client: AsyncClient,
) -> None:
    """A batch row whose jobs were never committed reports its own total."""
    batch_id = await _make_batch(job_statuses=None, stored_total=4)

    item = (await client.get("/v1/batches")).json()["items"][0]

    assert item["batch_id"] == batch_id
    assert (item["completed"], item["failed"], item["total"]) == (0, 0, 4)


async def test_list_does_not_ship_per_job_results(client: AsyncClient) -> None:
    """A list of batches must not carry N full result sets."""
    await _make_batch(job_statuses=["complete"])

    item = (await client.get("/v1/batches")).json()["items"][0]

    assert set(item) == {"batch_id", "completed", "failed", "total", "created_at"}
