"""v1 router assembly.

One place that knows every v1 path, so the API surface can be read in a single
screen and mounted (or excluded) as a unit.

Route order matters in one place: ``/recipes`` is declared before any
``/recipes/{recipe_id}`` route so the literal path wins over the parameterised
one. FastAPI matches in declaration order, and a parameterised sibling declared
first would swallow ``/recipes?limit=10``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import batch, files, generate, health, jobs, recipes

api_router = APIRouter(prefix="/v1")

# Health first: it is the endpoint a load balancer hits, and it should not
# depend on anything below it resolving.
api_router.include_router(health.router)
api_router.include_router(generate.router)
api_router.include_router(jobs.router)
api_router.include_router(files.router)
api_router.include_router(batch.router)
api_router.include_router(recipes.router)

__all__ = ["api_router"]
