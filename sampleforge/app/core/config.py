"""Application settings.

Loaded once from the environment (and ``.env``) via pydantic-settings. Nothing
here reads the environment at import time beyond constructing :data:`settings`,
so tests can override fields per-test with :func:`override_settings`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the API, workers, and supporting services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SAMPLEFORGE_",
        extra="ignore",
    )

    # --- Service metadata -----------------------------------------------
    version: str = Field(default="0.1.0", description="Reported by /v1/health.")
    environment: str = Field(
        default="development", description="'development', 'test', or 'production'."
    )

    # --- Auth ------------------------------------------------------------
    api_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Valid X-API-Key values. Empty means the API is unconfigured, and "
            "authenticated endpoints then reject with 503 rather than serving "
            "unauthenticated."
        ),
    )
    api_key_header: str = Field(default="X-API-Key", description="Header carrying the API key.")

    # --- Rate limiting ---------------------------------------------------
    rate_limit_enabled: bool = Field(
        default=True,
        description="Master switch for slowapi; disabled in tests so they stay independent.",
    )
    generate_rate_limit: str = Field(
        default="100/minute", description="Quota for POST /v1/generate, per API key."
    )
    batch_rate_limit: str = Field(
        default="10/minute", description="Quota for POST /v1/batch, per API key."
    )

    # --- Queue -----------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", description="arq broker DSN.")

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://sampleforge:sampleforge@localhost:5432/sampleforge",
        description="Async SQLAlchemy DSN.",
    )
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)

    # --- Storage ---------------------------------------------------------
    storage_backend: str = Field(
        default="local",
        description="'local' writes to local_storage_dir; 's3' uploads to S3.",
    )
    local_storage_dir: str = Field(
        default="./var/samples", description="Directory for local artifact storage."
    )
    s3_bucket: str | None = Field(default=None)
    s3_prefix: str = Field(default="samples", description="Key prefix inside the bucket.")
    s3_endpoint_url: str | None = Field(
        default=None, description="Custom endpoint for S3-compatible stores."
    )
    s3_region: str | None = Field(default=None)

    # --- Generation ------------------------------------------------------
    model_path: str | None = Field(
        default=None, description="Directory or checkpoint for the generator."
    )
    device: str = Field(default="cuda", description="Torch device for inference.")
    max_batch_size: int = Field(default=64, ge=1)

    # --- Retry policy ----------------------------------------------------
    job_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Total attempts for transient failures, including the first.",
    )
    retry_base_delay_seconds: float = Field(default=0.5, gt=0.0)
    retry_max_delay_seconds: float = Field(default=30.0, gt=0.0)


settings = Settings()


@contextmanager
def override_settings(**overrides: object) -> Iterator[None]:
    """Temporarily override :data:`settings` fields.

    Used by tests and by local development scripts; anything not overridden is
    restored on exit.

    Args:
        **overrides: Field names and the values to apply.

    Yields:
        Nothing — the point is the scoped mutation of :data:`settings`.
    """
    previous = {key: getattr(settings, key) for key in overrides}
    try:
        for key, value in overrides.items():
            setattr(settings, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)
