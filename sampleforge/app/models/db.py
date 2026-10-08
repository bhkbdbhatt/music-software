"""SQLAlchemy models for job persistence.

Kept apart from :mod:`app.models.schemas` on purpose: those are the API
contract, these describe rows. The spec is stored as JSON so a job keeps
reproducing from the request that created it even after the schema evolves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class GenerationJob(Base):
    """A single generation job and everything needed to audit its outcome.

    The spec is denormalised onto the row rather than referenced, so a job can
    be replayed from its own record with no join and no risk of the original
    recipe changing underneath a queued job.
    """

    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    base_seed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    batch_id: Mapped[str | None] = mapped_column(
        String(64), default=None, index=True, nullable=True
    )
    recipe_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    result_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    constraint_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(String(1024), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def result_url(self) -> str | None:
        """The first rendered variant's URL, for the single-file case.

        Batch jobs return every variant in :attr:`result_urls`; this is the
        convenience view for callers that asked for one file.
        """
        return self.result_urls[0] if self.result_urls else None


class GenerationBatch(Base):
    """A group of jobs submitted together, plus how they should be executed.

    Progress is deliberately *not* stored here. Counts are derived from the
    member jobs on every poll, so a crashed worker cannot leave a batch
    permanently reporting "3 of 4 done" — the numbers are always a snapshot of
    what the database actually holds.
    """

    __tablename__ = "generation_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    total_jobs: Mapped[int] = mapped_column(Integer, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Recipe(Base):
    """A named, reusable :class:`~app.models.schemas.GenerationSpec`.

    Recipes are the unit of sharing: a spec saved once and referenced by name,
    so a team tunes one kick and everybody regenerates from the same numbers
    instead of copy-pasting JSON between projects.
    """

    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), default=None)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
