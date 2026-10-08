"""Tests for the /v1/recipes CRUD surface."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_create_recipe_returns_201_with_location(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    response = await client.post("/v1/recipes", json=recipe_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == recipe_payload["name"]
    assert body["spec"]["category"] == "kick"
    assert response.headers["Location"] == f"/v1/recipes/{body['id']}"


async def test_duplicate_name_returns_409(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    (await client.post("/v1/recipes", json=recipe_payload))

    response = await client.post("/v1/recipes", json=recipe_payload)

    assert response.status_code == 409


async def test_create_recipe_requires_authentication(
    client_factory: Any, recipe_payload: dict[str, Any]
) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        response = await anonymous.post("/v1/recipes", json=recipe_payload)

    assert response.status_code == 401


async def test_create_rejects_an_invalid_spec(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    """A recipe must never be saved in a state the generator would reject."""
    recipe_payload["spec"]["attack_ms"] = 5000.0

    assert (await client.post("/v1/recipes", json=recipe_payload)).status_code == 422


async def test_get_recipe_round_trips_the_spec(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()

    fetched = await client.get(f"/v1/recipes/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["spec"] == created["spec"]
    assert fetched.json()["description"] == recipe_payload["description"]


async def test_get_unknown_recipe_returns_404(client: AsyncClient) -> None:
    assert (await client.get("/v1/recipes/nope")).status_code == 404


async def test_list_recipes_is_paginated(client: AsyncClient, spec: dict[str, Any]) -> None:
    for index in range(5):
        (
            await client.post(
                "/v1/recipes",
                json={
                    "name": f"kick-{index}",
                    "description": None,
                    "spec": spec,
                },
            )
        )

    page = await client.get("/v1/recipes?limit=2&offset=1")

    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2


async def test_list_rejects_an_oversized_page(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    (await client.post("/v1/recipes", json=recipe_payload))

    assert (await client.get("/v1/recipes?limit=101")).status_code == 422
    assert (await client.get("/v1/recipes?limit=0")).status_code == 422
    assert (await client.get("/v1/recipes?offset=-1")).status_code == 422


async def test_list_is_empty_on_a_fresh_database(client: AsyncClient) -> None:
    body = (await client.get("/v1/recipes")).json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_recipe_reads_are_open(client_factory: Any, recipe_payload: dict[str, Any]) -> None:
    """A recipe is a spec, not anyone's audio, so listing needs no key."""
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        assert (await anonymous.get("/v1/recipes")).status_code == 200


async def test_update_renames_a_recipe(client: AsyncClient, recipe_payload: dict[str, Any]) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()

    response = await client.put(f"/v1/recipes/{created['id']}", json={"name": "renamed-kick"})

    assert response.status_code == 200
    assert response.json()["name"] == "renamed-kick"
    assert response.json()["spec"] == created["spec"], "spec must be untouched"


async def test_update_replaces_the_spec(
    client: AsyncClient, recipe_payload: dict[str, Any], spec: dict[str, Any]
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()
    updated_spec = {**spec, "peak_db": -6.0}

    response = await client.put(f"/v1/recipes/{created['id']}", json={"spec": updated_spec})

    assert response.status_code == 200
    assert response.json()["spec"]["peak_db"] == -6.0
    assert response.json()["name"] == recipe_payload["name"]


async def test_update_to_a_taken_name_returns_409(
    client: AsyncClient, recipe_payload: dict[str, Any], spec: dict[str, Any]
) -> None:
    (await client.post("/v1/recipes", json=recipe_payload))
    other = (
        await client.post(
            "/v1/recipes",
            json={"name": "other", "description": None, "spec": spec},
        )
    ).json()

    response = await client.put(f"/v1/recipes/{other['id']}", json={"name": recipe_payload["name"]})

    assert response.status_code == 409


async def test_update_validates_the_new_spec(
    client: AsyncClient, recipe_payload: dict[str, Any], spec: dict[str, Any]
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()

    response = await client.put(
        f"/v1/recipes/{created['id']}",
        json={"spec": {**spec, "fundamental_hz": [500.0, 100.0]}},
    )

    assert response.status_code == 422


async def test_update_unknown_recipe_returns_404(client: AsyncClient) -> None:
    assert (await client.put("/v1/recipes/nope", json={"name": "x"})).status_code == 404


async def test_update_requires_authentication(
    client_factory: Any, recipe_payload: dict[str, Any]
) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        response = await anonymous.put("/v1/recipes/nope", json={"name": "x"})

    assert response.status_code == 401


async def test_delete_recipe_returns_204(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()

    response = await client.delete(f"/v1/recipes/{created['id']}")

    assert response.status_code == 204
    assert (await client.get(f"/v1/recipes/{created['id']}")).status_code == 404


async def test_delete_twice_returns_404(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()
    (await client.delete(f"/v1/recipes/{created['id']}"))

    assert (await client.delete(f"/v1/recipes/{created['id']}")).status_code == 404


async def test_delete_requires_authentication(
    client_factory: Any, recipe_payload: dict[str, Any]
) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        response = await anonymous.delete("/v1/recipes/nope")

    assert response.status_code == 401


async def test_run_recipe_queues_a_job(
    client: AsyncClient, recipe_payload: dict[str, Any], queue: Any
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()

    response = await client.post(f"/v1/recipes/{created['id']}/run")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["poll_url"] == f"/v1/jobs/{body['job_id']}"
    assert queue.enqueued == [body["job_id"]]


async def test_run_recipe_records_the_recipe_id(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:

    from app.db.session import get_session_factory
    from app.models.db import GenerationJob

    created = (await client.post("/v1/recipes", json=recipe_payload)).json()
    job_id = (await client.post(f"/v1/recipes/{created['id']}/run")).json()["job_id"]

    async def _recipe_id() -> str | None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(GenerationJob, job_id)
            assert job is not None
            return job.recipe_id

    assert await _recipe_id() == created["id"]


async def test_run_recipe_uses_the_stored_spec(
    client: AsyncClient, recipe_payload: dict[str, Any]
) -> None:
    """Editing the recipe changes what a later run generates."""

    from app.db.session import get_session_factory
    from app.models.db import GenerationJob

    created = (await client.post("/v1/recipes", json=recipe_payload)).json()
    (
        await client.put(
            f"/v1/recipes/{created['id']}",
            json={"spec": {**recipe_payload["spec"], "peak_db": -3.0}},
        )
    )
    job_id = (await client.post(f"/v1/recipes/{created['id']}/run")).json()["job_id"]

    async def _peak() -> float:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(GenerationJob, job_id)
            assert job is not None
            return float(job.spec["peak_db"])

    assert await _peak() == -3.0


async def test_run_unknown_recipe_returns_404(client: AsyncClient) -> None:
    assert (await client.post("/v1/recipes/nope/run")).status_code == 404


async def test_run_requires_authentication(
    client_factory: Any, recipe_payload: dict[str, Any]
) -> None:
    async with client_factory() as anonymous:
        anonymous.headers.pop("X-API-Key", None)
        response = await anonymous.post("/v1/recipes/nope/run")

    assert response.status_code == 401


async def test_run_with_unreachable_queue_returns_503(
    client: AsyncClient, recipe_payload: dict[str, Any], queue: Any
) -> None:
    created = (await client.post("/v1/recipes", json=recipe_payload)).json()
    queue.fail = True

    response = await client.post(f"/v1/recipes/{created['id']}/run")

    assert response.status_code == 503
