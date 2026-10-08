"""Saved recipes: named, reusable specs.

A recipe is the unit of sharing. Once a kick is tuned, it is saved by name and
regenerated from the same numbers, instead of JSON being copied between
projects and drifting.

Reads are open — a recipe is a spec, not anyone's audio — while writes and
``/run`` require a key. If recipes hold anything sensitive, add the key
dependency to the three read routes as well.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.generate import create_job
from app.core.logging import get_logger
from app.core.security import ApiKey
from app.db.session import SessionDep
from app.models.db import Recipe
from app.models.schemas import (
    STATUS_QUEUED,
    RecipeCreate,
    RecipeList,
    RecipeRead,
    RecipeRunResponse,
    RecipeUpdate,
)
from app.workers.queue import enqueue_job

log = get_logger(__name__)

router = APIRouter(prefix="/recipes", tags=["recipes"])


async def _load_recipe(session: AsyncSession, recipe_id: str) -> Recipe:
    """Fetch a recipe or raise 404.

    Args:
        session: Async database session.
        recipe_id: The recipe to fetch.

    Returns:
        The recipe row.

    Raises:
        HTTPException: 404 if no such recipe exists.
    """
    recipe = await session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown recipe: {recipe_id}",
        )
    return recipe


@router.post(
    "",
    response_model=RecipeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save a recipe",
    description=(
        "Stores a `GenerationSpec` under a unique name. The spec is validated "
        "on the way in, so a recipe can never be saved in a state the "
        "generator would reject."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_409_CONFLICT: {"description": "A recipe with that name exists."},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The spec is invalid."},
    },
)
async def create_recipe(
    request: Request,
    payload: RecipeCreate,
    response: Response,
    api_key: ApiKey,
    session: SessionDep,
) -> RecipeRead:
    """Save a new recipe.

    Args:
        request: Incoming request.
        payload: Name, description, and spec.
        response: Used to publish the new recipe's location.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The stored recipe.

    Raises:
        HTTPException: 409 if the name is taken. 422 is handled by FastAPI
            before this runs, for an invalid spec.
    """
    existing = await session.execute(select(Recipe.id).where(Recipe.name == payload.name))
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a recipe named {payload.name!r} already exists",
        )

    recipe = Recipe(
        id=uuid.uuid4().hex,
        name=payload.name,
        description=payload.description,
        spec=payload.spec.model_dump(mode="json"),
    )
    session.add(recipe)
    await session.commit()
    await session.refresh(recipe)

    response.headers["Location"] = f"/v1/recipes/{recipe.id}"
    log.info("recipe_created", recipe_id=recipe.id, name=recipe.name)
    return RecipeRead.model_validate(recipe)


@router.get(
    "",
    response_model=RecipeList,
    summary="List recipes",
    description=(
        "Newest first, paginated. `limit` is capped at 100 so a single request "
        "cannot pull the whole table."
    ),
)
async def list_recipes(
    request: Request,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Recipes to skip."),
) -> RecipeList:
    """Return a page of saved recipes.

    Args:
        request: Incoming request.
        limit: Page size, 1 to 100.
        offset: Number of recipes to skip.
        session: Async database session.

    Returns:
        The page plus the total recipe count.
    """
    total_result = await session.execute(select(func.count()).select_from(Recipe))
    total = int(total_result.scalar_one())

    result = await session.execute(
        select(Recipe).order_by(Recipe.created_at.desc(), Recipe.id).limit(limit).offset(offset)
    )
    items = [RecipeRead.model_validate(recipe) for recipe in result.scalars()]
    return RecipeList(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{recipe_id}",
    response_model=RecipeRead,
    summary="Fetch a recipe",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such recipe."}},
)
async def get_recipe(
    request: Request,
    recipe_id: str,
    session: SessionDep,
) -> RecipeRead:
    """Return one saved recipe.

    Args:
        request: Incoming request.
        recipe_id: The recipe to fetch.
        session: Async database session.

    Returns:
        The recipe.

    Raises:
        HTTPException: 404 if it does not exist.
    """
    return RecipeRead.model_validate(await _load_recipe(session, recipe_id))


@router.put(
    "/{recipe_id}",
    response_model=RecipeRead,
    summary="Update a recipe",
    description=(
        "Partial update: send only the fields to change. Renaming to an existing "
        "name is a 409 rather than a silent overwrite."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_404_NOT_FOUND: {"description": "No such recipe."},
        status.HTTP_409_CONFLICT: {"description": "That name is already taken."},
    },
)
async def update_recipe(
    request: Request,
    recipe_id: str,
    payload: RecipeUpdate,
    api_key: ApiKey,
    session: SessionDep,
) -> RecipeRead:
    """Update a recipe's name, description, or spec.

    Args:
        request: Incoming request.
        recipe_id: The recipe to update.
        payload: Fields to change; omitted fields are left alone.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The updated recipe.

    Raises:
        HTTPException: 404 if it does not exist; 409 if the new name is taken.
    """
    recipe = await _load_recipe(session, recipe_id)

    if payload.name is not None and payload.name != recipe.name:
        clash = await session.execute(select(Recipe.id).where(Recipe.name == payload.name))
        if clash.first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"a recipe named {payload.name!r} already exists",
            )
        recipe.name = payload.name

    if payload.description is not None:
        recipe.description = payload.description
    if payload.spec is not None:
        recipe.spec = payload.spec.model_dump(mode="json")

    await session.commit()
    await session.refresh(recipe)
    log.info("recipe_updated", recipe_id=recipe.id)
    return RecipeRead.model_validate(recipe)


@router.delete(
    "/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recipe",
    description=(
        "Removes the recipe. Jobs already generated from it are untouched — the "
        "spec is denormalised onto each job row, so history stays reproducible."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_404_NOT_FOUND: {"description": "No such recipe."},
    },
)
async def delete_recipe(
    request: Request,
    recipe_id: str,
    api_key: ApiKey,
    session: SessionDep,
) -> Response:
    """Delete a saved recipe.

    Args:
        request: Incoming request.
        recipe_id: The recipe to delete.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        204 No Content.

    Raises:
        HTTPException: 404 if it does not exist.
    """
    recipe = await _load_recipe(session, recipe_id)
    await session.delete(recipe)
    await session.commit()
    log.info("recipe_deleted", recipe_id=recipe_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{recipe_id}/run",
    response_model=RecipeRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate from a saved recipe",
    description=(
        "Queues a job using the recipe's stored spec. The job records the "
        "recipe it came from, so generated files can be traced back to the "
        "exact spec that produced them."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key."},
        status.HTTP_404_NOT_FOUND: {"description": "No such recipe."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The queue is unreachable."},
    },
)
async def run_recipe(
    request: Request,
    recipe_id: str,
    api_key: ApiKey,
    session: SessionDep,
) -> RecipeRunResponse:
    """Queue a generation job from a saved recipe.

    Args:
        request: Incoming request.
        recipe_id: The recipe to run.
        api_key: The caller's validated API key.
        session: Async database session.

    Returns:
        The queued job's id, status, and poll URL.

    Raises:
        HTTPException: 404 if the recipe does not exist; 503 if the queue is
            unreachable.
    """
    recipe = await _load_recipe(session, recipe_id)

    from app.models.schemas import GenerationSpec

    spec = GenerationSpec.model_validate(recipe.spec)
    job = await create_job(session, spec, recipe_id=recipe.id)

    try:
        await enqueue_job(job.id)
    except ConnectionError as exc:
        await session.rollback()
        log.error("recipe_enqueue_failed", recipe_id=recipe_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the job queue is unavailable; try again shortly",
        ) from exc
    await session.commit()

    log.info("recipe_run", recipe_id=recipe_id, job_id=job.id)
    return RecipeRunResponse(
        job_id=job.id,
        status=STATUS_QUEUED,
        poll_url=f"/v1/jobs/{job.id}",
    )
