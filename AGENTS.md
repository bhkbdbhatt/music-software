# SampleForge — Project Rules

## Stack
- Python 3.11+, FastAPI, Pydantic v2
- PyTorch for model inference (GPU: CUDA 12.x)
- SQLAlchemy 2.0 + PostgreSQL (via asyncpg)
- Redis for job queue (Celery or arq)
- Docker for all services
- pytest for tests, ruff for linting

## Conventions
- Type hints everywhere, no `Any`
- Pydantic models for all API input/output
- Async where possible (FastAPI async endpoints, async DB)
- No global mutable state
- Every endpoint must have a corresponding test
- Use `structlog` for logging, not `print`

## Architecture
- `app/api/` — FastAPI routes (thin, no business logic)
- `app/services/` — business logic
- `app/models/` — Pydantic schemas + SQLAlchemy models
- `app/generation/` — ML model loading, inference, constraint solver
- `app/workers/` — Celery/arq task definitions
- `app/core/` — config, auth, middleware

## Don't
- Don't put model loading in route handlers
- Don't block the event loop (use run_in_threadpool for CPU-bound work)
- Don't commit secrets — use .env + pydantic-settings
- Don't skip input validation on any endpoint