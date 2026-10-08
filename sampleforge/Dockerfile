# syntax=docker/dockerfile:experimental 
# RUN --mount=type=cache with sharing=locked

# SampleForge — multi-stage build.
#
#   builder  resolves and installs the locked dependency set, then byte-compiles
#            the source. Never shipped.
#   runtime  carries only the virtualenv, the source, and the two system
#            libraries the audio stack links against. Runs as a non-root user.
#
# Build:  docker build -t sampleforge .
# Run:    docker run --rm -p 8000:8000 -e SAMPLEFORGE_API_KEYS='["k"]' sampleforge
#
# Note on size: torch resolves to the CUDA 12.6 build (see [tool.uv.sources] in
# pyproject.toml), which drags in ~15 nvidia-* wheels. The image is therefore
# several GB. That is the price of a GPU-capable worker in one image; a CPU-only
# deployment can drop torch from pyproject.toml and rebuild for a fraction of the
# size.

# ---------------------------------------------------------------------------
# Stage 1 — builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# UV_COMPILE_BYTECODE pre-compiles .pyc at install time so the first request does
# not pay for it. UV_PYTHON_DOWNLOADS=never makes uv fail loudly rather than
# silently fetching a different interpreter than the base image ships.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# build-essential + pkg-config only matter if a wheel is missing for the target
# platform; libsndfile1/ffmpeg are runtime deps that the builder needs too,
# because librosa imports them at module scope.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# uv is a single static binary; copying it beats a curl-pipe-shell install and
# keeps the download hashed and layer-cached by BuildKit. The version matches the
# one that produced uv.lock: `revision = 5` is not readable by older uv, and a
# mismatch here fails `uv sync --frozen` at build time.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first, in their own layer: editing app/ then rebuilds in seconds
# instead of re-resolving torch. --frozen fails the build if uv.lock disagrees
# with pyproject.toml rather than silently re-resolving.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Source, then a real compile step so a syntax error fails the build instead of
# the first request. --no-install-project is safe because [tool.uv] sets
# package = false: the app is imported from /app, never installed.
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
    && python -m compileall -q app

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"

# libgomp1 is the OpenMP runtime that numpy/scipy/numba/torch link against —
# without it they import fine and then die on first use. libsndfile1 backs
# soundfile (wav/flac/mp3 encode), ffmpeg backs audio decoding fallbacks.
# build-essential is deliberately absent: there is nothing left to compile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Fixed uid/gid so a bind-mounted volume has predictable ownership across
# machines. --system keeps it out of /etc/passwd's login range while still
# giving us a real home for caches.
RUN groupadd --system --gid 10001 sampleforge \
    && useradd --system --uid 10001 --gid 10001 --create-home \
    --home-dir /home/sampleforge --shell /usr/sbin/nologin sampleforge

WORKDIR /app

# Same absolute path as the builder: venvs are not relocatable, the shebangs in
# /app/.venv/bin would break if it moved.
COPY --from=builder --chown=sampleforge:sampleforge /app/.venv /app/.venv
COPY --from=builder --chown=sampleforge:sampleforge /app/app /app/app
COPY --from=builder --chown=sampleforge:sampleforge /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=sampleforge:sampleforge /app/alembic /app/alembic

# The local storage backend writes here; the directory has to exist and be owned
# by the runtime user before any job renders a sample, or the first upload dies
# on a permission error that looks like a bug.
RUN mkdir -p /app/var/samples \
    && chown -R sampleforge:sampleforge /app/var

USER sampleforge:sampleforge

EXPOSE 8000

# Health check without curl (not installed): a 200 from /v1/health is enough.
# Note it reports "degraded" in the body when the queue is unreachable and still
# answers 200, which is intentional — see app/api/v1/health.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3).status == 200 else 1)"]

# Two workers: uvicorn's default is one, and a single process blocks on the
# async DB pool during generation submission. Scale with replicas rather than
# more workers once CPU is the constraint — the model lives in the worker, not
# here, so the API stays light.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
