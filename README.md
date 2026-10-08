# SampleForge

Constraint-enforced audio sample generation. A FastAPI + PyTorch backend that generates audio samples (kicks, one-shots, etc.) from a structured spec and verifies the rendered output against hard audio constraints, plus a SvelteKit web UI to drive it.

The repo contains two independent apps:

| Folder | What it is |
| --- | --- |
| `sampleforge/` | Backend: FastAPI REST API + arq worker + PostgreSQL + Redis + MinIO |
| `frontend/` | Web UI: SvelteKit 5 + TypeScript + Tailwind 4 |

## Prerequisites

- Docker + Docker Compose (recommended path)
- Or, for a native run: Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), Node.js 20+, npm, PostgreSQL 16, Redis 7
- POSIX shell for the backend `Makefile` (WSL, Git Bash, or Linux/macOS — native Windows cmd/PowerShell is not supported by the Makefile)

## Quick start (backend, Docker — recommended)

```bash
cd sampleforge
cp .env.example .env    # then edit SAMPLEFORGE_API_KEYS, e.g. ["dev-key-change-me"]
make dev                # = docker compose up --build
```

If you don't have `make`, run `docker compose up --build` directly from `sampleforge/`.

Startup order is handled by compose: postgres/redis → minio bucket init → `alembic upgrade head` → api + worker.

Verify:

```bash
make curl-health        # GET http://localhost:8000/v1/health
make generate           # submit a sample job and poll it to completion
make recipe             # save the sample spec as a reusable recipe
```

- Swagger UI: http://localhost:8000/docs (put your key in the `X-API-Key` field)
- ReDoc: http://localhost:8000/redoc

Stop:

```bash
make down               # stop, keep volumes
make clean-stack        # stop and delete volumes
```

### Ports

| Service | Port |
| --- | --- |
| API | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| MinIO S3 / console | 9000 / 9001 |

### GPU

Inference runs on CPU by default. To use CUDA, edit `sampleforge/docker-compose.yml`: uncomment the `deploy.resources.reservations.devices` block under `worker`, set `SAMPLEFORGE_DEVICE: cuda`, then `docker compose up -d worker`.

## Backend without Docker

```bash
cd sampleforge
cp .env.example .env
uv sync --group dev
make migrate            # alembic upgrade head (Postgres required; SQLite URLs skip this automatically)

# terminal 1
uvicorn app.main:app --reload --port 8000
# terminal 2
arq app.workers.queue.WorkerSettings
```

Point `SAMPLEFORGE_DATABASE_URL` and `SAMPLEFORGE_REDIS_URL` in `.env` at your own Postgres/Redis.

## Frontend

```bash
cd frontend
cp .env.example .env    # BACKEND_URL=http://127.0.0.1:8000, VITE_MOCK_API=false
npm install
npm run dev             # dev server
```

To work without a running backend, set `VITE_MOCK_API=true` in `frontend/.env`.

Production build:

```bash
npm run build
npm run preview         # or: node build (adapter-node)
```

Regenerate API types after backend schema changes:

```bash
npm run gen:types
```

## Tests and lint

Backend (from `sampleforge/`):

```bash
make test               # pytest with coverage
make test-fast          # pytest -q
make lint               # ruff check + format check
make check              # lint + test (what CI runs)
```

Tests run against SQLite with a fake queue and fake generator — no Postgres/Redis/GPU needed.

Frontend (from `frontend/`):

```bash
npm run lint            # prettier --check + eslint
npm run check           # svelte-check type checking
npm run test            # unit (vitest) + e2e (playwright)
```

## API overview

All routes are under `/v1` and, except `/v1/health`, require the `X-API-Key` header:

| Route | Purpose |
| --- | --- |
| `POST /v1/generate` | Queue a generation job, returns `job_id` |
| `POST /v1/batch` | Queue a batch of specs |
| `GET /v1/jobs/{id}` | Poll job status and per-constraint pass/fail results |
| `GET /v1/batches/{id}` | Poll batch status |
| `POST/GET /v1/recipes` | Save and list reusable specs |
| `GET /v1/files` | Download generated audio |
| `GET /v1/health` | Liveness: `model_loaded`, `gpu_available`, `queue_depth` |

Rate limits, API keys, DB/Redis URLs, storage backend (`local` or `s3`), and device (`cpu`/`cuda`) are all configured via `SAMPLEFORGE_*` variables in `sampleforge/.env` — see `sampleforge/.env.example`.

## Project layout

```
sampleforge/
  app/
    api/v1/        # FastAPI routes
    core/          # config, auth, logging
    generation/    # model loading, inference, post-processing
    models/        # Pydantic schemas + SQLAlchemy models
    services/      # business logic, constraint solver, storage
    workers/       # arq queue + tasks
  alembic/         # migrations
  tests/           # pytest suite
frontend/
  src/routes/      # generate, jobs, batches, recipes, library, settings
  src/lib/         # api client, audio, components
  openapi/         # backend OpenAPI snapshot
```
