"""Tests for GET /v1/files/{job_id}/{variant}.

The route exists so a browser can play samples the local storage backend wrote
to disk: ``file://`` URIs are server-side paths, and this turns them into
fetchable HTTP. Remote (S3) URLs are redirected to rather than proxied.

Job rows are created directly because the file route reads ``result_urls``
verbatim — the worker is not involved.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from app.core.config import settings
from app.db.session import get_session_factory
from app.models.db import GenerationJob
from app.models.schemas import GenerationSpec
from httpx import AsyncClient

from conftest import spec_payload

pytestmark = pytest.mark.asyncio


async def _make_job(result_urls: list[str], *, status: str = "complete") -> str:
    """Insert a finished job carrying the given result URLs.

    Args:
        result_urls: Exactly the URLs the route will be asked to serve.
        status: Row status; the route reads ``result_urls`` regardless.

    Returns:
        The job id.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = GenerationJob(
            id=uuid.uuid4().hex,
            status=status,
            spec=GenerationSpec.model_validate(spec_payload()).model_dump(mode="json"),
            batch_size=len(result_urls),
            base_seed=0,
            result_urls=result_urls,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


async def test_unknown_job_returns_404(client: AsyncClient) -> None:
    response = await client.get("/v1/files/does-not-exist/0")

    assert response.status_code == 404


async def test_variant_out_of_range_returns_404(client: AsyncClient) -> None:
    job_id = await _make_job(["https://cdn.test/a_0.wav"])

    assert (await client.get(f"/v1/files/{job_id}/1")).status_code == 404
    assert (await client.get(f"/v1/files/{job_id}/0")).status_code == 307


async def test_negative_variant_is_rejected(client: AsyncClient) -> None:
    job_id = await _make_job(["https://cdn.test/a_0.wav"])

    assert (await client.get(f"/v1/files/{job_id}/-1")).status_code == 422


async def test_remote_url_redirects(client: AsyncClient) -> None:
    job_id = await _make_job(["https://cdn.test/samples/a.wav"])

    response = await client.get(f"/v1/files/{job_id}/0")

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.test/samples/a.wav"


async def test_local_file_is_served_inline_with_an_audio_type(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    async with client_factory() as client:
        storage_root = Path(settings.local_storage_dir).resolve()
        wav = storage_root / "samples" / "abc" / "abc_0.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(b"RIFFfake-wav-bytes")

        job_id = await _make_job([wav.as_uri()])

        response = await client.get(f"/v1/files/{job_id}/0")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        assert "inline" in response.headers["content-disposition"]
        assert response.content == b"RIFFfake-wav-bytes"


async def test_missing_local_file_returns_404(client_factory: Any) -> None:
    async with client_factory() as client:
        storage_root = Path(settings.local_storage_dir).resolve()
        absent = storage_root / "samples" / "gone" / "gone_0.wav"
        job_id = await _make_job([absent.as_uri()])

        assert (await client.get(f"/v1/files/{job_id}/0")).status_code == 404


async def test_path_outside_the_storage_root_returns_404(
    client_factory: Any, tmp_path: Path
) -> None:
    """A stored URL that escapes the storage directory is never served."""
    async with client_factory() as client:
        outside = tmp_path / "not-a-sample.wav"
        outside.write_bytes(b"secret")
        job_id = await _make_job([outside.resolve().as_uri()])

        assert (await client.get(f"/v1/files/{job_id}/0")).status_code == 404


async def test_route_needs_no_api_key(client_factory: Any) -> None:
    """A `<audio>` element cannot send X-API-Key, so the route stays open."""
    async with client_factory() as client:
        client.headers.pop("X-API-Key", None)
        job_id = await _make_job(["https://cdn.test/a.wav"])

        assert (await client.get(f"/v1/files/{job_id}/0")).status_code == 307


async def test_poll_exposes_the_fetchable_url(client: AsyncClient) -> None:
    """The rewrite and the route agree: a local file polls as its route URL."""
    job_id = await _make_job(["file:///var/samples/x/x_0.wav"])

    polled = (await client.get(f"/v1/jobs/{job_id}")).json()

    assert polled["files"][0]["url"] == f"/v1/files/{job_id}/0"


async def test_poll_leaves_remote_urls_alone(client: AsyncClient) -> None:
    job_id = await _make_job(["https://cdn.test/a_0.wav"])

    polled = (await client.get(f"/v1/jobs/{job_id}")).json()

    assert polled["files"][0]["url"] == "https://cdn.test/a_0.wav"
