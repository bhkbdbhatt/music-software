# SampleForge

Constraint-enforced audio sample generation API. Submit a `GenerationSpec`, get
back rendered audio files (WAV/FLAC/MP3) plus a per-constraint pass/fail map —
every spectral and temporal constraint is verified after rendering, not just
requested.

- **Backend:** FastAPI + Uvicorn, SQLAlchemy 2.0 (async, PostgreSQL), arq on Redis
- **Inference:** PyTorch VAE worker with a constraint solver and post-processing
- **Storage:** local disk or S3/MinIO
- **UI:** the interactive Swagger UI served by the API at `/docs`

---

## Requirements

| | |
|---|---|
| Docker + Compose v2 | recommended way to run everything |
| Python 3.11–3.13 + [uv](https://docs.astral.sh/uv/) | only for running outside Docker |
| GNU Make (or WSL/Git Bash on Windows) | only if you want the `make` shortcuts |
| NVIDIA driver + Container Toolkit | only for GPU inference |

The Compose stack needs a Linux host or WSL2. Native Windows `cmd.exe` is not
supported by the `Makefile`; plain `docker compose` commands work anywhere Docker
does.

---

## Quick start (development)

```bash
cd sampleforge
cp .env.example .env        # then edit SAMPLEFORGE_API_KEYS
make dev                    # = docker compose up --build
```

First build is slow (the image carries the CUDA build of torch). Subsequent
builds reuse the dependency layer.

When it is up:

```bash
make curl-health            # GET /v1/health
make generate               # submit a sample job and poll it to completion
make recipe                 # save that spec as a named recipe
```

Without Make:

```bash
docker compose up --build
curl -sS http://localhost:8000/v1/health
```

Services and ports:

| Service | Port | Purpose |
|---|---|---|
| api | `8000` | REST API + `/docs` UI |
| postgres | `5432` | jobs, batches, recipes |
| redis | `6379` | arq job queue |
| minio | `9000` / `9001` | S3-compatible storage (dev) |

Stop with `make down` (keeps volumes) or `make clean-stack` (deletes them).

---

## The UI (`/docs`)

The API ships its own browser UI — FastAPI's Swagger UI. Nothing to build or
deploy separately; it is served by the same process as the backend.

1. Start the stack (`make dev`) and open **http://localhost:8000/docs**
   (`/redoc` for the readable reference, `/openapi.json` for the raw schema).
2. `GET /v1/health` needs no key — hit **Execute** to confirm the API, queue, and
   model state.
3. For every other endpoint, click **Try it out**, fill in the body, and enter
   your key in the **`X-API-Key`** header parameter field (it appears as a
   regular parameter on each operation). Send the request.

Notes:

- The key must be one of the values in `.env` under `SAMPLEFORGE_API_KEYS`
  (a JSON list, e.g. `["dev-key-change-me"]`).
- An empty list leaves the API unconfigured: authenticated endpoints answer
  **503** rather than serving unauthenticated traffic.
- Rate limits apply per key: `SAMPLEFORGE_GENERATE_RATE_LIMIT` (default
  `100/minute`) and `SAMPLEFORGE_BATCH_RATE_LIMIT` (default `10/minute`); a
  breach is a **429** with `Retry-After`.

Typical flow in the UI:

1. `POST /v1/generate` → returns `job_id`.
2. `GET /v1/jobs/{job_id}` → poll until `status` is `complete`,
   `complete_with_warnings`, or `failed`.
3. The response carries rendered file references and the constraint pass/fail
   map.
4. `POST /v1/recipes` saves the spec; `GET /v1/recipes` lists them (reads are
   unauthenticated).

---

## Running in production

### 1. Configure

Create `.env` from the template and change it before deploying:

```bash
cp .env.example .env
```

Minimum production edits:

```dotenv
SAMPLEFORGE_ENVIRONMENT=production
SAMPLEFORGE_API_KEYS=["put-a-long-random-value-here"]   # never ship the dev key
SAMPLEFORGE_STORAGE_BACKEND=s3
SAMPLEFORGE_S3_BUCKET=your-bucket
SAMPLEFORGE_S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
SAMPLEFORGE_DEVICE=cuda                                 # cpu if no GPU
SAMPLEFORGE_MODEL_PATH=/models/sampleforge-vae
```

All settings are read with the `SAMPLEFORGE_` prefix (see `app/core/config.py`).
`SAMPLEFORGE_MODEL_PATH` must point **inside** the container: bind-mount your
weights into the worker (e.g. `./models:/models` in `docker-compose.yml`). With
it unset, every job fails at model load rather than the service failing to boot.

Beware: `docker-compose.yml` hardcodes container-side values for
`SAMPLEFORGE_ENVIRONMENT`, `SAMPLEFORGE_DEVICE`, database/Redis URLs, and the
storage backend. Override them with a production override file rather than
editing the base file:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

(`docker-compose.prod.yml` only needs an `environment:` block for `api` and
`worker` with your production values.)

### 2. Build the image

```bash
docker build -t sampleforge .
```

### 3. Start the stack

```bash
docker compose up -d --build
```

Compose starts, in order: Postgres and Redis (health-checked) → `minio-init` →
`migrate` (runs `alembic upgrade head` and must succeed) → `api` and `worker`.
Migrations never race each other because they run in a dedicated one-shot
service, so scaling `api` replicas is safe.

Equivalent manual ordering, if you are not using Compose:

1. Start PostgreSQL and Redis.
2. `alembic upgrade head` (Alembic reads `SAMPLEFORGE_DATABASE_URL`, never
   `alembic.ini`).
3. API: the image's default CMD —
   `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`
4. Worker: `arq app.workers.queue.WorkerSettings`

### 4. Verify

```bash
curl -sS http://localhost:8000/v1/health
```

`/v1/health` always answers **200** — degraded components are reported in the
body so monitoring alerts on `status`/`detail` instead of a 5xx that would pull
the instance out of rotation:

```json
{"status": "ok", "model_loaded": true, "gpu_available": true,
 "queue_depth": 0, "version": "0.1.0", "detail": null}
```

`status: "degraded"` with `detail` naming the unreachable queue, or a `cuda`
device with no visible GPU, means fix the configuration before sending traffic.

Then exercise it through the UI at `/docs` or with a real request:

```bash
curl -sS -X POST http://localhost:8000/v1/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $YOUR_KEY" \
  -d '{"type":"one_shot","category":"kick","duration_ms":300,
       "fundamental_hz":[40.0,90.0],"spectral_ceiling_hz":12000.0,
       "spectral_floor_hz":20.0,"peak_db":-12.0,"attack_ms":1.0,
       "decay_ms":100.0,"sustain_level":0.0,"release_ms":50.0,
       "bpm":120.0,"key":"F#m","genre":"techno","format":"wav","batch_size":1}'
```

### 5. GPU inference (optional)

Host prerequisites: NVIDIA driver, NVIDIA Container Toolkit (on Docker Desktop
for Windows/macOS: enable WSL integration GPU support). Then, in
`docker-compose.yml`:

1. Uncomment the `deploy.resources.reservations.devices` block under `worker`.
2. Set `SAMPLEFORGE_DEVICE: cuda` in `x-app-env`.
3. `docker compose up -d worker`

Verify:

```bash
docker compose exec worker python -c \
  "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
curl -sS http://localhost:8000/v1/health   # gpu_available: true
```

### 6. Operations

```bash
docker compose ps                 # service status
docker compose logs -f api        # tail a service
make migrate                      # apply new migrations
make check-migrations             # fail if models drifted from migrations
```

- Rendered samples live in the `sample_data` volume (shared by api and worker),
  or in S3 when `SAMPLEFORGE_STORAGE_BACKEND=s3`.
- The worker gets a 120s stop grace period so an in-flight render finishes
  instead of being killed mid-write.
- Rate-limit state is in-process; if the API is scaled horizontally, move it to
  Redis storage (noted in `app/core/security.py`).

---

## Running without Docker

```bash
cd sampleforge
cp .env.example .env             # point URLs at localhost services
uv sync --group dev              # create .venv with dev dependencies
make migrate                     # needs reachable Postgres
uvicorn app.main:app --reload --port 8000        # API (+ /docs)
arq app.workers.queue.WorkerSettings             # worker, separate terminal
```

The API needs Postgres and Redis running (`make dev-cpu` starts Postgres, Redis,
and MinIO without the API or worker). Against SQLite
(`SAMPLEFORGE_DATABASE_URL=sqlite+aiosqlite:///...`) the API creates tables on
startup and needs no migration step, but the worker still needs Redis.

---

## Tests and lint

```bash
make test        # pytest + coverage
make lint        # ruff check + format check
make check       # both, as CI would run
```

---

## Project layout

```
sampleforge/
├── app/
│   ├── main.py            # FastAPI app factory
│   ├── api/v1/            # routes: generate, batch, recipes, jobs, health
│   ├── core/              # config, auth, rate limiting, structlog
│   ├── models/            # Pydantic schemas + SQLAlchemy models
│   ├── services/          # generation, constraint solver, storage
│   ├── generation/        # model loading, inference, post-processing
│   ├── workers/           # arq task + worker settings
│   └── db/                # async engine/session
├── alembic/               # migrations
├── tests/
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── .env.example
```
