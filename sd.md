Scaffold a Python project called "sampleforge" with this exact structure:

sampleforge/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entrypoint
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py        # pydantic-settings, reads .env
│   │   ├── security.py      # JWT auth, API key middleware
│   │   └── logging.py       # structlog setup
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── router.py    # aggregates all v1 routes
│   │   │   ├── generate.py  # POST /v1/generate
│   │   │   ├── batch.py     # POST /v1/batch
│   │   │   ├── recipes.py   # CRUD /v1/recipes
│   │   │   └── health.py    # GET /v1/health
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py       # Pydantic request/response models
│   │   └── db.py            # SQLAlchemy models (User, Recipe, Job, Generation)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── generation.py    # orchestrates: validate → queue → poll → return
│   │   ├── constraint.py    # spectral/temporal constraint solver
│   │   └── storage.py       # S3/local file storage for generated WAVs
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── base.py          # abstract base: load_model(), generate(spec)
│   │   ├── vae_model.py     # SampleVAE-based implementation
│   │   └── postprocess.py   # spectral ceiling enforcement, normalization, fade
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── tasks.py         # arq task: run_generation(job_id)
│   │   └── queue.py         # arq Redis connection
│   └── db/
│       ├── __init__.py
│       ├── session.py       # async engine + session factory
│       └── migrations/      # alembic
├── tests/
│   ├── conftest.py
│   ├── test_generate.py
│   ├── test_constraint.py
│   └── test_batch.py
├── models/                  # .gitkeep — model weights go here
├── alembic.ini
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml       # postgres + redis + app + worker
├── .env.example
└── README.md

Tech stack:
- FastAPI + Uvicorn
- Pydantic v2 (use model_config = ConfigDict(...))
- SQLAlchemy 2.0 async with asyncpg
- arq (not Celery) for the job queue — lighter, asyncio-native
- Redis for queue + caching
- S3-compatible storage (use boto3, configurable endpoint for MinIO in dev)
- structlog for logging
- pydantic-settings for config

Generate all files with working code. The FastAPI app should start and serve /v1/health. 
Use alembic for migrations. Include a docker-compose.yml with postgres:16, redis:7, 
and the app. The .env.example should have: DATABASE_URL, REDIS_URL, S3_ENDPOINT, 
S3_BUCKET, API_KEY_SECRET, MODEL_PATH, GPU_DEVICE.

For the generation module, create a clean abstract interface:
- BaseGenerator: load() -> None, generate(spec: GenerationSpec) -> np.ndarray
- VAEGenerator(BaseGenerator): wraps a TensorFlow/PyTorch VAE model
- The actual model loading should be lazy (on first call, not import time)

Make sure pyproject.toml uses uv-compatible format with all dependencies pinned.   