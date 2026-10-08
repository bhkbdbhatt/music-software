"""Tests for GET /v1/health."""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import override_settings
from httpx import AsyncClient

from conftest import TEST_KEY

pytestmark = pytest.mark.asyncio


async def test_health_is_unauthenticated(client_factory: Any) -> None:
    async with client_factory() as client:
        response = await client.get("/v1/health", headers={"X-API-Key": ""})

    assert response.status_code == 200


async def test_health_reports_every_documented_field(client: AsyncClient) -> None:
    body = (await client.get("/v1/health")).json()

    assert set(body) >= {"status", "model_loaded", "gpu_available", "queue_depth", "version"}
    assert isinstance(body["model_loaded"], bool)
    assert isinstance(body["gpu_available"], bool)


async def test_health_reports_the_configured_version(client_factory: Any) -> None:
    async with client_factory(version="9.9.9") as client:
        assert (await client.get("/v1/health")).json()["version"] == "9.9.9"


async def test_health_reports_the_queue_depth(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _depth() -> int | None:
        return 7

    monkeypatch.setattr("app.api.v1.health.queue_depth", _depth)
    # Whether this box has a GPU is environment-dependent; the point here is the
    # queue depth, so the other two components are stubbed.
    monkeypatch.setattr("app.api.v1.health.gpu_available", lambda: True)

    body = (await client.get("/v1/health")).json()

    assert body["queue_depth"] == 7
    assert body["status"] == "ok"


async def test_health_is_degraded_when_the_queue_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_broker() -> int | None:
        return None

    monkeypatch.setattr("app.api.v1.health.queue_depth", _no_broker)

    body = (await client.get("/v1/health")).json()

    assert body["status"] == "degraded"
    assert body["queue_depth"] is None, "cannot tell is not the same as empty"
    assert "queue" in body["detail"]


async def test_health_stays_200_when_degraded(client: AsyncClient) -> None:
    """A 503 would take the instance out of a load balancer's rotation.

    That is the opposite of what you want when the GPU box has no GPU: the API
    can still accept jobs and queue them for a healthy worker elsewhere.
    """
    assert (await client.get("/v1/health")).status_code == 200


async def test_health_flags_cuda_configured_without_a_gpu(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """device=cuda with no visible GPU would fail every job at model load."""
    monkeypatch.setattr("app.api.v1.health.gpu_available", lambda: False)

    async def _zero() -> int | None:
        return 0

    monkeypatch.setattr("app.api.v1.health.queue_depth", _zero)

    with override_settings(device="cuda"):
        body = (await client.get("/v1/health")).json()

    assert body["gpu_available"] is False
    assert body["status"] == "degraded"
    assert "cuda" in body["detail"]


async def test_health_reports_model_loaded_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.health.is_generator_loaded", lambda: True)
    monkeypatch.setattr("app.api.v1.health.gpu_available", lambda: True)

    async def _zero() -> int | None:
        return 0

    monkeypatch.setattr("app.api.v1.health.queue_depth", _zero)

    body = (await client.get("/v1/health")).json()

    assert body["model_loaded"] is True
    assert body["gpu_available"] is True
    assert body["status"] == "ok"


async def test_health_does_not_trigger_a_model_load(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health must never put a multi-gigabyte allocation behind a probe."""
    from app.services import generation

    def _explode() -> bool:
        raise AssertionError("health must not load the model")

    monkeypatch.setattr(generation, "get_generator", _explode)

    assert (await client.get("/v1/health")).status_code == 200


async def test_health_is_documented_in_openapi(client: AsyncClient) -> None:
    operation = (await client.get("/openapi.json")).json()["paths"]["/v1/health"]["get"]

    assert operation["tags"] == ["health"]
    assert operation["summary"]
    assert operation["description"]
    assert "security" not in operation, "health must not advertise a credential"


async def test_health_does_not_leak_the_api_key(client: AsyncClient) -> None:
    """The response must not echo back the credential it was called with."""
    response = await client.get("/v1/health", headers={"X-API-Key": TEST_KEY})

    assert TEST_KEY not in response.text
