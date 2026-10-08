"""Tests for the generation worker task."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import pytest_asyncio
from app.core.config import override_settings, settings
from app.core.logging import configure_logging
from app.db import session as session_module
from app.generation.base import GenerationError, ModelLoadError
from app.models.db import Base, GenerationJob
from app.models.schemas import GenerationSpec
from app.services.encoding import decode_audio
from app.services.generation import reset_generator, set_generator_factory
from app.services.storage import TransientStorageError
from app.workers import tasks
from app.workers.tasks import (
    MODEL_LOAD_FAILED,
    STATUS_COMPLETE,
    STATUS_COMPLETE_WITH_WARNINGS,
    STATUS_FAILED,
    STATUS_PROCESSING,
    derive_seed,
    generate_sample,
    retry_delay,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

SR = 44100
DURATION_MS = 300

VALID_SPEC: dict[str, Any] = {
    "type": "one_shot",
    "category": "kick",
    "duration_ms": DURATION_MS,
    "fundamental_hz": (40.0, 90.0),
    "spectral_ceiling_hz": 12000.0,
    "spectral_floor_hz": 20.0,
    "peak_db": -12.0,
    "attack_ms": 1.0,
    "decay_ms": 100.0,
    "sustain_level": 0.0,
    "release_ms": 50.0,
    "bpm": 120.0,
    "key": "F#m",
    "genre": "techno",
}


def _tone(freq_hz: float, noise_seed: int = 0) -> np.ndarray:
    """A harmonically rich tone whose pitch depends on ``noise_seed``."""
    n = round(DURATION_MS * SR / 1000)
    t = np.arange(n) / SR
    rng = np.random.default_rng(noise_seed)
    detune = 1.0 + rng.uniform(-0.01, 0.01)
    return (
        np.sin(2 * np.pi * freq_hz * detune * t) + 0.5 * np.sin(4 * np.pi * freq_hz * detune * t)
    ).astype(np.float64)


class FakeGenerator:
    """Records the seeds it was asked for; emits a tone per seed."""

    def __init__(self) -> None:
        self.seeds: list[int] = []
        self.loads = 0

    async def load(self) -> None:
        self.loads += 1

    async def generate(self, spec: GenerationSpec, *, seed: int) -> np.ndarray:
        self.seeds.append(seed)
        return _tone(55.0, noise_seed=seed % 1000)

    async def close(self) -> None:
        return None


class ExplodingGenerator(FakeGenerator):
    """Fails on the first ``failures`` generate calls, then succeeds."""

    def __init__(self, error: Exception, failures: int = 99) -> None:
        super().__init__()
        self.error = error
        self.failures = failures

    async def generate(self, spec: GenerationSpec, *, seed: int) -> np.ndarray:
        if len(self.seeds) < self.failures:
            self.seeds.append(seed)
            raise self.error
        return await super().generate(spec, seed=seed)


class UnloadableGenerator(FakeGenerator):
    """Fails at load time."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def load(self) -> None:
        raise self.error


class FailsAfterGenerator(FakeGenerator):
    """Renders ``succeeds`` variants, then raises."""

    def __init__(self, error: Exception, succeeds: int) -> None:
        super().__init__()
        self.error = error
        self.succeeds = succeeds

    async def generate(self, spec: GenerationSpec, *, seed: int) -> np.ndarray:
        if len(self.seeds) >= self.succeeds:
            self.seeds.append(seed)
            raise self.error
        return await super().generate(spec, seed=seed)


@pytest.fixture(autouse=True)
def _quiet_logging() -> Iterator[None]:
    configure_logging(json_output=False)
    yield


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh SQLite database for one test, wired into the session module."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}", echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    previous_engine = session_module._engine
    previous_factory = session_module._session_factory
    session_module._engine = engine
    session_module._session_factory = factory
    try:
        yield factory
    finally:
        session_module._engine = previous_engine
        session_module._session_factory = previous_factory
        await engine.dispose()
        reset_generator()


@pytest_asyncio.fixture
async def storage_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the local storage backend at a temp directory, retries near-instant."""
    root = tmp_path / "artifacts"
    with override_settings(
        storage_backend="local",
        local_storage_dir=str(root),
        retry_base_delay_seconds=0.001,
        retry_max_delay_seconds=0.005,
        job_max_attempts=3,
    ):
        yield root


async def _create_job(
    db: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = 1,
    base_seed: int = 0,
    spec_overrides: dict[str, Any] | None = None,
    status: str = "queued",
) -> str:
    job_id = uuid.uuid4().hex
    payload = {**VALID_SPEC, **(spec_overrides or {})}
    spec = GenerationSpec.model_validate(payload)
    async with db() as session:
        session.add(
            GenerationJob(
                id=job_id,
                status=status,
                spec=spec.model_dump(mode="json"),
                batch_size=batch_size,
                base_seed=base_seed,
                result_urls=[],
            )
        )
        await session.commit()
    return job_id


async def _fetch(db: async_sessionmaker[AsyncSession], job_id: str) -> GenerationJob:
    async with db() as session:
        return await session.get(GenerationJob, job_id)


@pytest.fixture
def fake_storage() -> Any:
    """A storage backend that fails ``failures`` times, then records uploads."""

    class RecordingStorage:
        def __init__(self) -> None:
            self.uploads: list[tuple[str, bytes, str]] = []
            self.failures = 0
            self.error = TransientStorageError("connection reset")

        async def upload(self, key: str, data: bytes, *, content_type: str) -> Any:
            if self.failures > 0:
                self.failures -= 1
                raise self.error
            self.uploads.append((key, data, content_type))
            from app.services.storage import StoredObject

            return StoredObject(key=key, url=f"https://cdn.test/{key}", size_bytes=len(data))

    return RecordingStorage()


def _use_fake_storage(monkeypatch: pytest.MonkeyPatch, storage: Any) -> None:
    monkeypatch.setattr("app.workers.tasks.get_storage", lambda: storage)


def monkeypatch_storage(storage: Any) -> Any:
    """Patch the task's storage lookup for the duration of a ``with`` block."""
    import contextlib

    @contextlib.contextmanager
    def _patch() -> Iterator[None]:
        original = tasks.get_storage
        tasks.get_storage = lambda: storage  # type: ignore[assignment]
        try:
            yield
        finally:
            tasks.get_storage = original  # type: ignore[assignment]

    return _patch()


# ----------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_variant_job_completes(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    generator = FakeGenerator()
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db)

    assert await generate_sample({}, job_id) == job_id

    job = await _fetch(db, job_id)
    assert job.status == STATUS_COMPLETE
    assert job.error is None
    assert len(job.result_urls) == 1
    assert job.result_url is not None
    assert job.constraint_report is not None
    assert job.constraint_report["failed_constraints"] == []
    assert len(job.constraint_report["variants"]) == 1

    stored = list(storage_dir.rglob("*.wav"))
    assert len(stored) == 1
    audio, sr = decode_audio(stored[0].read_bytes())
    assert sr == SR
    assert abs(float(np.max(np.abs(audio))) - 10 ** (-12.0 / 20.0)) < 1e-4


@pytest.mark.asyncio
async def test_generated_audio_is_written_to_the_requested_format(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    set_generator_factory(FakeGenerator)

    for fmt, suffix in (("flac", ".flac"), ("mp3", ".mp3")):
        job_id = await _create_job(db, spec_overrides={"format": fmt})
        await generate_sample({}, job_id)
        job = await _fetch(db, job_id)
        assert job.status in (STATUS_COMPLETE, STATUS_COMPLETE_WITH_WARNINGS)
        assert len(list(storage_dir.rglob(f"*{suffix}"))) == 1


@pytest.mark.asyncio
async def test_batch_produces_one_file_per_variant_with_distinct_seeds(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    generator = FakeGenerator()
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db, batch_size=3, base_seed=42)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_COMPLETE
    assert len(job.result_urls) == 3
    assert len(set(job.result_urls)) == 3
    assert len(set(generator.seeds)) == 3
    assert len(list(storage_dir.rglob("*.wav"))) == 3


@pytest.mark.asyncio
async def test_zero_diversity_renders_identical_variants(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    generator = FakeGenerator()
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db, batch_size=3, base_seed=7, spec_overrides={"diversity": 0.0})

    await generate_sample({}, job_id)

    assert len(set(generator.seeds)) == 1, "diversity 0 must reuse one seed"
    files = sorted(storage_dir.rglob("*.wav"))
    payloads = [path.read_bytes() for path in files]
    assert len(set(payloads)) == 1, "identical seeds must give identical files"


@pytest.mark.asyncio
async def test_job_is_processing_while_the_work_runs(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    """The row must show "processing" during the run, not only at the end."""
    set_generator_factory(FakeGenerator)
    job_id = await _create_job(db)
    observed: list[str] = []

    class ObservingStorage:
        async def upload(self, key: str, data: bytes, *, content_type: str) -> Any:
            from app.services.storage import StoredObject

            job = await _fetch(db, job_id)
            observed.append(job.status if job else "gone")
            return StoredObject(key=key, url=f"https://cdn.test/{key}", size_bytes=len(data))

    with monkeypatch_storage(ObservingStorage()):
        await generate_sample({}, job_id)

    assert observed == [STATUS_PROCESSING]
    assert (await _fetch(db, job_id)).status == STATUS_COMPLETE


# ----------------------------------------------------------------------
# Constraints
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unmet_constraints_yield_complete_with_warnings(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    """Unvoiced noise has no fundamental: the file ships, flagged."""
    set_generator_factory(_NoiseGenerator)
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_COMPLETE_WITH_WARNINGS
    assert job.error is None
    assert len(job.result_urls) == 1
    assert job.constraint_report is not None
    failed = job.constraint_report["failed_constraints"]
    assert "fundamental_hz" in failed
    assert job.constraint_report["constraints_met"]["fundamental_hz"] is False
    assert job.constraint_report["constraints_met"]["peak_db"] is True


class _NoiseGenerator(FakeGenerator):
    """Emits noise, which has no detectable fundamental."""

    async def generate(self, spec: GenerationSpec, *, seed: int) -> np.ndarray:
        self.seeds.append(seed)
        rng = np.random.default_rng(seed)
        n = round(DURATION_MS * SR / 1000)
        return rng.normal(0.0, 0.3, size=n)


# ----------------------------------------------------------------------
# Failure modes
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_load_failure_is_recorded(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    set_generator_factory(lambda: UnloadableGenerator(ModelLoadError("no weights")))
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_FAILED
    assert job.error == MODEL_LOAD_FAILED
    assert job.result_urls == []


@pytest.mark.asyncio
async def test_generation_failure_records_the_message(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    set_generator_factory(lambda: ExplodingGenerator(GenerationError("CUDA OOM")))
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_FAILED
    assert job.error == "CUDA OOM"


@pytest.mark.asyncio
async def test_value_error_from_generator_is_not_retried(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    generator = ExplodingGenerator(ValueError("bad conditioning"))
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db, batch_size=2)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_FAILED
    assert "bad conditioning" in (job.error or "")
    assert len(generator.seeds) == 1, "a permanent error must not be retried"


@pytest.mark.asyncio
async def test_unknown_job_raises(db: async_sessionmaker[AsyncSession], storage_dir: Path) -> None:
    with pytest.raises(ValueError, match="unknown job"):
        await generate_sample({}, "does-not-exist")


@pytest.mark.asyncio
async def test_partial_batch_failure_fails_the_job(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    set_generator_factory(lambda: FailsAfterGenerator(GenerationError("boom"), succeeds=2))
    job_id = await _create_job(db, batch_size=3)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_FAILED
    assert job.error == "boom"
    # The two variants that did render are still on the row for debugging.
    assert len(job.result_urls) == 2


# ----------------------------------------------------------------------
# Retries
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transient_generation_error_is_retried(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    generator = ExplodingGenerator(ConnectionError("socket hang up"), failures=2)
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_COMPLETE
    assert len(generator.seeds) == 3, "two failures then a success"


@pytest.mark.asyncio
async def test_transient_upload_error_is_retried(
    db: async_sessionmaker[AsyncSession],
    storage_dir: Path,
    fake_storage: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_storage.failures = 2
    _use_fake_storage(monkeypatch, fake_storage)
    set_generator_factory(FakeGenerator)
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_COMPLETE
    assert len(fake_storage.uploads) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded(db: async_sessionmaker[AsyncSession], storage_dir: Path) -> None:
    generator = ExplodingGenerator(ConnectionError("still down"))
    set_generator_factory(lambda: generator)
    job_id = await _create_job(db)

    await generate_sample({}, job_id)

    job = await _fetch(db, job_id)
    assert job.status == STATUS_FAILED
    assert settings.job_max_attempts == 3
    assert len(generator.seeds) == 3


# ----------------------------------------------------------------------
# Units
# ----------------------------------------------------------------------
def test_derive_seed_is_zero_diversity_stable() -> None:
    assert derive_seed(7, 0, 0.0) == derive_seed(7, 1, 0.0) == 7


def test_derive_seed_is_deterministic() -> None:
    assert derive_seed(11, 2, 0.7) == derive_seed(11, 2, 0.7)


def test_derive_seed_differs_per_variant() -> None:
    assert derive_seed(11, 0, 0.5) != derive_seed(11, 1, 0.5)


def test_retry_delay_grows_and_respects_the_cap() -> None:
    with override_settings(retry_base_delay_seconds=1.0, retry_max_delay_seconds=2.0):
        first = retry_delay(1)
        second = retry_delay(2)
        capped = retry_delay(9)
    assert 0.9 <= first <= 1.1
    assert 1.8 <= second <= 2.2
    assert capped <= 2.2


@pytest.mark.asyncio
async def test_event_loop_is_not_blocked_by_generation(
    db: async_sessionmaker[AsyncSession], storage_dir: Path
) -> None:
    """Inference must run off the loop: the loop keeps ticking meanwhile."""

    class SlowGenerator(FakeGenerator):
        async def generate(self, spec: GenerationSpec, *, seed: int) -> np.ndarray:
            await asyncio.sleep(0.05)
            return await super().generate(spec, seed=seed)

    set_generator_factory(SlowGenerator)
    job_id = await _create_job(db)

    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    ticker = asyncio.create_task(_ticker())
    try:
        await generate_sample({}, job_id)
    finally:
        ticker.cancel()

    assert (await _fetch(db, job_id)).status == STATUS_COMPLETE
    assert ticks > 3, "the loop was blocked during generation"
