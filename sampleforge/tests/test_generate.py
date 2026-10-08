"""Tests for POST /v1/generate, GET /v1/jobs/{job_id}, and GET /v1/health.

The queue and the model are both faked (see ``conftest.py``); the database is
real. ``test_job_polling_returns_complete`` runs the *whole* path — HTTP submit,
the arq task, constraint enforcement, encode, upload, then HTTP poll — so the
pieces are verified to fit together rather than only in isolation.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import settings
from app.db.session import get_session_factory
from app.models.db import GenerationJob
from app.workers.tasks import generate_sample
from httpx import AsyncClient

from conftest import FakeStorage

# Every test here is async and talks to the app over a real httpx client.
pytestmark = pytest.mark.asyncio


async def _stored_job(job_id: str) -> GenerationJob:
    """Read a job row straight from the database, bypassing the API.

    Args:
        job_id: The job to fetch.

    Returns:
        The attached job row.
    """
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(GenerationJob, job_id)
        assert job is not None
        return job


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
async def test_health_endpoint(client: AsyncClient) -> None:
    """Liveness is public, cheap, and never touches the model."""
    response = await client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert isinstance(body["model_loaded"], bool)
    assert isinstance(body["gpu_available"], bool)
    assert body["version"] == settings.version


async def test_health_needs_no_api_key(client_factory: Any) -> None:
    """A load balancer probing health must not need a credential."""
    async with client_factory() as client:
        response = await client.get("/v1/health", headers={"X-API-Key": ""})

    assert response.status_code == 200


async def test_health_reports_the_model_as_loaded_once_it_is(
    client: AsyncClient, spec: dict[str, Any], generator: Any
) -> None:
    """model_loaded is observable state, not a constant."""
    before = (await client.get("/v1/health")).json()
    job_id = (await _submit(client, spec))["job_id"]
    await generate_sample({}, job_id)
    after = (await client.get("/v1/health")).json()

    assert before["model_loaded"] is False
    assert after["model_loaded"] is True


# ----------------------------------------------------------------------
# Submission
# ----------------------------------------------------------------------
async def test_generate_returns_202(client: AsyncClient, spec: dict[str, Any]) -> None:
    """Accepted, not done: generation is asynchronous by design."""
    response = await client.post("/v1/generate", json=spec)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert body["poll_url"] == f"/v1/jobs/{body['job_id']}"


async def test_generate_enqueues_exactly_one_job(
    client: AsyncClient, spec: dict[str, Any], queue: Any
) -> None:
    response = await client.post("/v1/generate", json=spec)

    assert queue.enqueued == [response.json()["job_id"]]


async def test_generate_persists_the_spec_for_replay(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """The spec is denormalised onto the job, so history stays reproducible."""
    job_id = (await client.post("/v1/generate", json=spec)).json()["job_id"]

    stored = await _stored_job(job_id)

    assert stored.spec["category"] == "kick"
    assert stored.spec["fundamental_hz"] == [40.0, 90.0]
    assert stored.spec["peak_db"] == -12.0


async def test_generate_invalid_spec_returns_422(
    client: AsyncClient, spec: dict[str, Any], queue: Any
) -> None:
    """fundamental min > max: the detector could never satisfy it."""
    spec["fundamental_hz"] = [900.0, 100.0]

    response = await client.post("/v1/generate", json=spec)

    assert response.status_code == 422
    assert queue.enqueued == [], "an invalid spec must never reach the queue"


async def test_generate_rejects_a_missing_required_field(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    del spec["peak_db"]

    assert (await client.post("/v1/generate", json=spec)).status_code == 422


async def test_generate_rejects_an_unknown_field(client: AsyncClient, spec: dict[str, Any]) -> None:
    """extra='forbid' catches typos that would otherwise be silently ignored."""
    spec["reverb_amt"] = 0.4

    assert (await client.post("/v1/generate", json=spec)).status_code == 422


async def test_generate_requires_auth(
    client_factory: Any, spec: dict[str, Any], queue: Any
) -> None:
    """No API key means 401, and nothing is queued."""
    async with client_factory() as client:
        response = await client.post("/v1/generate", json=spec, headers={"X-API-Key": ""})

    assert response.status_code == 401
    assert settings.api_key_header in response.headers.get("WWW-Authenticate", "")
    assert queue.enqueued == []


async def test_generate_rejects_an_unknown_api_key(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    response = await client.post("/v1/generate", json=spec, headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


async def test_unconfigured_api_refuses_rather_than_serving_open(
    client_factory: Any, spec: dict[str, Any]
) -> None:
    """No keys configured is a 503, not an invitation."""
    async with client_factory(api_keys=[]) as client:
        response = await client.post("/v1/generate", json=spec)

    assert response.status_code == 503
    assert "API_KEYS" in response.json()["detail"]


# ----------------------------------------------------------------------
# Polling
# ----------------------------------------------------------------------
async def _submit(client: AsyncClient, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Submit one job and return the parsed response body."""
    response = await client.post("/v1/generate", json=spec or {})
    assert response.status_code == 202, response.text
    return response.json()


async def test_job_polling_returns_complete(
    client: AsyncClient, spec: dict[str, Any], generator: Any, storage: FakeStorage
) -> None:
    """End to end: submit, run the task, poll, and get real files back.

    Nothing here is stubbed except the queue and the model. The status, the
    uploaded URL, and the constraint report all come from the worker's own
    bookkeeping against a real database row.
    """
    job_id = (await _submit(client, spec))["job_id"]

    assert await generate_sample({}, job_id) == job_id

    response = await client.get(f"/v1/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"complete", "complete_with_warnings"}
    assert len(body["files"]) == 1
    assert body["files"][0]["url"].startswith("https://cdn.test/")
    assert storage.keys(), "the worker must have uploaded something"
    assert generator.seeds, "the fake model must have been called"


async def test_job_polling_reports_processing_before_completion(
    client: AsyncClient, spec: dict[str, Any]
) -> None:
    """A queued job is visible immediately; polling is how you watch it move."""
    job_id = (await _submit(client, spec))["job_id"]

    body = (await client.get(f"/v1/jobs/{job_id}")).json()

    assert body["status"] == "queued"
    assert body["files"] == []


async def test_job_polling_is_idempotent(
    client: AsyncClient, spec: dict[str, Any], generator: Any
) -> None:
    """Polling a finished job twice must not re-run anything."""
    job_id = (await _submit(client, spec))["job_id"]
    await generate_sample({}, job_id)
    calls = len(generator.seeds)

    first = (await client.get(f"/v1/jobs/{job_id}")).json()
    second = (await client.get(f"/v1/jobs/{job_id}")).json()

    assert first == second
    assert len(generator.seeds) == calls, "a poll must not trigger generation"


async def test_failed_job_is_still_a_200(
    client: AsyncClient, spec: dict[str, Any], install_generator: Any
) -> None:
    """ "The job failed" is an answer, not a failed request."""
    from app.generation.base import ModelLoadError

    install_generator(_unloadable(ModelLoadError("no checkpoint")))
    job_id = (await _submit(client, spec))["job_id"]

    await generate_sample({}, job_id)

    body = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert (await client.get(f"/v1/jobs/{job_id}")).status_code == 200
    assert body["status"] == "failed"
    assert body["files"] == []


async def test_unknown_job_returns_404(client: AsyncClient) -> None:
    response = await client.get("/v1/jobs/does-not-exist")

    assert response.status_code == 404


async def test_job_poll_requires_authentication(client_factory: Any, spec: dict[str, Any]) -> None:
    job_id = (await _submit_via(client_factory, spec))["job_id"]

    async with client_factory() as client:
        response = await client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": ""})

    assert response.status_code == 401


async def _submit_via(client_factory: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Submit a job in one client scope and return the body."""
    async with client_factory() as client:
        return await _submit(client, spec)


def _unloadable(error: Exception) -> Any:
    """A generator that raises at load time."""
    from app.generation.base import Generator

    class _Unloadable:
        async def load(self) -> None:
            raise error

        async def generate(self, spec: Any, *, seed: int) -> Any:  # pragma: no cover
            raise AssertionError("must not generate if load failed")

        async def close(self) -> None:
            return None

    assert isinstance(_Unloadable(), Generator)
    return _Unloadable()
