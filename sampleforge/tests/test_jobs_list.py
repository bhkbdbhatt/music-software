"""Tests for GET /v1/jobs — the recent-jobs list.

Covers authentication, pagination, ordering, the status filter, the spec echo,
and the local-file URL rewrite that the list and the poll share (both go
through ``_to_response``).

Rows are created directly where a test needs precise control over
``created_at`` or ``status``: SQLite's ``CURRENT_TIMESTAMP`` has second
granularity, so jobs submitted in the same second would tie and fall back to a
random id order — testing ordering against that would be testing luck.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db.session import get_session_factory
from app.models.db import GenerationJob
from app.models.schemas import GenerationSpec
from httpx import AsyncClient

from conftest import spec_payload

pytestmark = pytest.mark.asyncio


async def _make_job(
    *,
    status: str = "queued",
    spec: dict[str, Any] | None = None,
    result_urls: list[str] | None = None,
    batch_id: str | None = None,
    created_at: datetime | None = None,
) -> GenerationJob:
    """Insert a job row directly.

    Args:
        status: Job status to write.
        spec: Spec payload; validated then stored as a model dump, exactly as
            the submit endpoint stores it.
        result_urls: Stored result URLs.
        batch_id: Batch to link to.
        created_at: Creation time; defaults to "now".

    Returns:
        The persisted row.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = GenerationJob(
            id=uuid.uuid4().hex,
            status=status,
            spec=GenerationSpec.model_validate(spec or spec_payload()).model_dump(mode="json"),
            batch_size=1,
            base_seed=0,
            batch_id=batch_id,
            result_urls=result_urls or [],
            created_at=created_at or datetime.now(UTC),
            updated_at=created_at or datetime.now(UTC),
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


async def test_list_requires_an_api_key(client_factory: Any) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        assert (await anonymous.get("/v1/jobs")).status_code == 401


async def test_list_is_empty_on_a_fresh_database(client: AsyncClient) -> None:
    body = (await client.get("/v1/jobs")).json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_returns_submitted_jobs_newest_first(client: AsyncClient) -> None:
    oldest = await _make_job(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    newest = await _make_job(created_at=datetime(2026, 6, 1, tzinfo=UTC))
    middle = await _make_job(created_at=datetime(2026, 3, 1, tzinfo=UTC))

    body = (await client.get("/v1/jobs")).json()

    assert body["total"] == 3
    assert [item["job_id"] for item in body["items"]] == [newest.id, middle.id, oldest.id]


async def test_list_paginates(client: AsyncClient) -> None:
    for days in range(3):
        await _make_job(created_at=datetime(2026, 1, 1 + days, tzinfo=UTC))

    first = (await client.get("/v1/jobs?limit=2")).json()
    second = (await client.get("/v1/jobs?limit=2&offset=2")).json()

    assert len(first["items"]) == 2 and first["total"] == 3
    assert len(second["items"]) == 1 and second["total"] == 3
    assert first["items"][0]["job_id"] != second["items"][0]["job_id"]


async def test_list_rejects_an_oversized_page(client: AsyncClient) -> None:
    assert (await client.get("/v1/jobs?limit=101")).status_code == 422
    assert (await client.get("/v1/jobs?limit=0")).status_code == 422
    assert (await client.get("/v1/jobs?offset=-1")).status_code == 422


async def test_list_filters_by_status(client: AsyncClient) -> None:
    await _make_job(status="queued")
    await _make_job(status="failed")
    await _make_job(status="complete")

    body = (await client.get("/v1/jobs?status=failed")).json()

    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


async def test_list_rejects_an_unknown_status(client: AsyncClient) -> None:
    assert (await client.get("/v1/jobs?status=schrodinger")).status_code == 422


async def test_list_items_echo_the_validated_spec(client: AsyncClient) -> None:
    """The echo carries server-side defaults, not just the submitted payload."""
    response = await client.post("/v1/generate", json=spec_payload())
    job_id = response.json()["job_id"]

    body = (await client.get("/v1/jobs")).json()
    item = body["items"][0]

    assert item["job_id"] == job_id
    expected = GenerationSpec.model_validate(spec_payload()).model_dump(mode="json")
    assert item["spec"] == expected
    assert item["spec"]["sample_rate"] == 44100  # a default the payload omitted
    assert item["batch_id"] is None and item["recipe_id"] is None
    assert "created_at" in item and "updated_at" in item


async def test_list_rewrites_local_file_urls(client: AsyncClient) -> None:
    job = await _make_job(
        status="complete",
        result_urls=["file:///var/samples/abc/abc_0.wav", "https://cdn.test/abc_1.wav"],
    )

    body = (await client.get("/v1/jobs?status=complete")).json()
    urls = [f["url"] for f in body["items"][0]["files"]]

    assert urls == [f"/v1/files/{job.id}/0", "https://cdn.test/abc_1.wav"]


async def test_list_keeps_batch_and_recipe_links(client: AsyncClient) -> None:
    await _make_job(batch_id="batch-abc")

    body = (await client.get("/v1/jobs")).json()

    assert body["items"][0]["batch_id"] == "batch-abc"
