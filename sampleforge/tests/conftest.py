"""Shared fixtures for the API tests.

Every test runs against the real ASGI app over a real HTTP client, with a real
SQLite database. Two things are faked, both because the alternative needs a
network or a GPU:

* the **queue** — arq needs Redis, and the API's whole contract with Redis is
  "hand this id over", which a recorder asserts on directly;
* the **model** — inference is not something a test can run. Tests install a
  :class:`FakeGenerator` that renders deterministic tones, so the constraint
  pipeline is exercised against real audio without a GPU.

``client`` and the rate-limit tests share one factory rather than duplicating
the database and settings wiring.

Signal builders are fixtures returning callables (``sine(440.0)``) rather than
fixtures returning arrays, so a test can ask for exactly the signal it needs
instead of accepting whatever a fixed array happens to contain.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import pytest
import pytest_asyncio
from app.core.config import override_settings
from app.core.logging import configure_logging
from app.db import session as session_module
from app.generation.base import GenerationError, ModelLoadError
from app.main import app
from app.models.db import Base
from app.models.schemas import GenerationSpec
from app.services.storage import StoredObject
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from numpy.typing import NDArray
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_KEY = "test-key-1"

#: Sample rate for every generated test signal.
SR = 44100

Audio = NDArray[np.float64]


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class RecordingQueue:
    """Stands in for arq, recording the job ids it was handed."""

    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.fail = False

    async def __call__(self, job_id: str) -> str:
        if self.fail:
            raise ConnectionError("redis unreachable")
        self.enqueued.append(job_id)
        return job_id


class FakeGenerator:
    """Renders deterministic tones instead of running inference.

    The tone is harmonically rich rather than a bare sine, and its pitch depends
    on the seed. Both matter: pYIN needs a second harmonic to anchor on (given a
    pure sine it will happily report a sub-octave, so the tests would be
    exercising the detector's failure mode), and seed-dependent pitch is what
    makes "these two variants differ" a meaningful assertion.
    """

    def __init__(self, *, freq_hz: float = 55.0) -> None:
        self.freq_hz = freq_hz
        self.seeds: list[int] = []
        self.loads = 0

    async def load(self) -> None:
        self.loads += 1

    async def generate(self, spec: GenerationSpec, *, seed: int) -> Audio:
        self.seeds.append(seed)
        return harmonic_tone(
            self.freq_hz,
            duration_ms=spec.effective_duration_ms,
            sr=spec.sample_rate,
            detune_seed=seed % 1000,
        )

    async def close(self) -> None:
        return None


class ExplodingGenerator(FakeGenerator):
    """Raises ``error`` on the first ``failures`` calls, then succeeds."""

    def __init__(self, error: Exception, failures: int = 99, *, freq_hz: float = 55.0) -> None:
        super().__init__(freq_hz=freq_hz)
        self.error = error
        self.failures = failures

    async def generate(self, spec: GenerationSpec, *, seed: int) -> Audio:
        if len(self.seeds) < self.failures:
            self.seeds.append(seed)
            raise self.error
        return await super().generate(spec, seed=seed)


class UnloadableGenerator(FakeGenerator):
    """Fails at load time, the way a missing checkpoint does."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def load(self) -> None:
        raise self.error


class FakeStorage:
    """Records uploads in memory instead of calling S3."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []
        self.failures = 0
        self.error: Exception = RuntimeError("upload failed")

    async def upload(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        if self.failures > 0:
            self.failures -= 1
            raise self.error
        self.uploads.append((key, data, content_type))
        return StoredObject(
            key=key,
            url=f"https://cdn.test/{key}",
            size_bytes=len(data),
        )

    def keys(self) -> list[str]:
        return [key for key, _data, _ctype in self.uploads]


# ----------------------------------------------------------------------
# Signal builders
# ----------------------------------------------------------------------
def sine(
    freq_hz: float,
    duration_ms: float = 500.0,
    sr: int = SR,
    amplitude: float = 1.0,
) -> Audio:
    """A mono sine, full scale unless ``amplitude`` says otherwise."""
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    return amplitude * np.sin(2.0 * np.pi * freq_hz * t)


def harmonic_tone(
    freq_hz: float,
    duration_ms: float = 500.0,
    sr: int = SR,
    *,
    detune_seed: int = 0,
) -> Audio:
    """A harmonically rich tone — closer to real model output than a bare sine.

    Args:
        freq_hz: Nominal fundamental.
        duration_ms: Length.
        sr: Sample rate.
        detune_seed: Varies the pitch by up to +/-1%, so two variants built from
            different seeds are audibly and measurably different.

    Returns:
        A mono float64 array.
    """
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    detune = 1.0 + np.random.default_rng(detune_seed).uniform(-0.01, 0.01)
    return (
        np.sin(2.0 * np.pi * freq_hz * detune * t)
        + 0.5 * np.sin(4.0 * np.pi * freq_hz * detune * t)
        + 0.25 * np.sin(6.0 * np.pi * freq_hz * detune * t)
    )


def noise(
    duration_ms: float = 500.0,
    sr: int = SR,
    seed: int = 0,
    amplitude: float = 1.0,
) -> Audio:
    """White noise, for spectral-floor and ceiling tests."""
    n = round(duration_ms * sr / 1000.0)
    return amplitude * np.random.default_rng(seed).standard_normal(n)


def ramped_sine(
    freq_hz: float,
    duration_ms: float,
    measured_attack_ms: float,
    sr: int = SR,
) -> Audio:
    """A sine with a linear amplitude ramp at the start.

    ``measured_attack_ms`` is what ``measure_attack_ms`` should report: a linear
    ramp only reaches 10% of peak at one tenth of its length, so the ramp itself
    is drawn ten times longer than the requested attack.
    """
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    ramp = np.clip(t / ((measured_attack_ms * 10.0) / 1000.0), 0.0, 1.0)
    return np.sin(2.0 * np.pi * freq_hz * t) * ramp


def band_db(audio: Audio, sr: int, low: float, high: float) -> float:
    """Absolute in-band energy in dB, so two signals can be compared directly.

    Args:
        audio: Mono or stereo; stereo is downmixed first.
        sr: Sample rate.
        low: Band lower edge in Hz, inclusive.
        high: Band upper edge in Hz, exclusive.

    Returns:
        Energy in dB, or -200 for a digitally silent band.
    """
    mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    band = spectrum[(freqs >= low) & (freqs < high)]
    energy = float(np.sum(band**2))
    return 10.0 * float(np.log10(energy)) if energy > 0 else -200.0


def band_fraction_db(audio: Audio, sr: int, low: float, high: float) -> float:
    """How much of a signal's total energy falls in a band, in dB.

    Scale-invariant and length-invariant, which is what makes this the right way
    to state "there is less than -60 dB above 8 kHz". Peak normalisation runs
    last in the pipeline, so any absolute reading taken after it is a function of
    the normalisation gain rather than of the filter.

    Args:
        audio: Mono or stereo.
        sr: Sample rate.
        low: Band lower edge in Hz, inclusive.
        high: Band upper edge in Hz, exclusive.

    Returns:
        ``10 * log10(band / total)``, or -200 for a digitally silent band.
    """
    mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    total = float(np.sum(spectrum**2))
    if total <= 0:
        return -200.0
    band = spectrum[(freqs >= low) & (freqs < high)]
    energy = float(np.sum(band**2))
    return 10.0 * float(np.log10(energy / total)) if energy > 0 else -200.0


def peak_db(audio: Audio) -> float:
    """Peak level of a signal in dBFS.

    Args:
        audio: Mono or stereo.

    Returns:
        ``20 * log10(peak)``, or -200 for silence.
    """
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return 20.0 * float(np.log10(peak)) if peak > 0 else -200.0


def spec_payload(**overrides: Any) -> dict[str, Any]:
    """A valid one-shot spec as a request body, with optional overrides."""
    payload: dict[str, Any] = {
        "type": "one_shot",
        "category": "kick",
        "duration_ms": 300,
        "fundamental_hz": [40.0, 90.0],
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
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
def _install_generator(fake: Any) -> None:
    """Register ``fake`` as the process-wide generator factory."""
    from app.services.generation import set_generator_factory

    set_generator_factory(lambda: fake)


def _reset_generator() -> None:
    """Drop the cached generator and its factory between tests."""
    from app.services.generation import reset_generator, set_generator_factory

    reset_generator()
    set_generator_factory(None)


@pytest.fixture(autouse=True)
def _quiet_logging() -> Iterator[None]:
    """Human-readable logs, and no leaked structlog config between files."""
    configure_logging(json_output=False)
    yield


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> RecordingQueue:
    """Replace the enqueue helper with a recorder, everywhere it is imported."""
    recorder = RecordingQueue()
    for module in (
        "app.api.v1.generate",
        "app.api.v1.batch",
        "app.api.v1.recipes",
    ):
        monkeypatch.setattr(f"{module}.enqueue_job", recorder)
    return recorder


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    """Replace the worker's storage backend with an in-memory recorder.

    Patched on ``app.workers.tasks``, not on ``app.services.storage``: the task
    does ``from app.services.storage import get_storage``, so it holds its own
    reference and a patch on the defining module would silently do nothing.
    """
    fake = FakeStorage()
    monkeypatch.setattr("app.workers.tasks.get_storage", lambda: fake)
    return fake


@pytest.fixture
def generator() -> Iterator[FakeGenerator]:
    """A fake model, installed for the duration of one test.

    Installed through :func:`set_generator_factory` because that is the seam
    production uses too; resetting on teardown keeps the cached instance from
    leaking into the next test's ``/v1/health`` reading.
    """
    fake = FakeGenerator()
    _install_generator(fake)
    try:
        yield fake
    finally:
        _reset_generator()


@pytest.fixture
def install_generator() -> Iterator[Callable[[Any], Any]]:
    """Install a specific fake generator, for tests that need a failure mode.

    Yields:
        A callable that registers a generator and returns it.
    """

    def _install(fake: Any) -> Any:
        _install_generator(fake)
        return fake

    try:
        yield _install
    finally:
        _reset_generator()


@pytest.fixture
def client_factory(tmp_path: Any, queue: RecordingQueue) -> Callable[..., Any]:
    """Build async clients against throwaway databases with chosen settings."""
    clients: list[AsyncClient] = []

    @asynccontextmanager
    async def _make(**overrides: Any) -> AsyncIterator[AsyncClient]:
        database_url = f"sqlite+aiosqlite:///{tmp_path / uuid.uuid4().hex}.db"
        engine = create_async_engine(database_url, echo=False)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        previous_engine = session_module._engine
        previous_factory = session_module._session_factory
        session_module._engine = engine
        session_module._session_factory = factory

        settings_overrides: dict[str, Any] = {
            "database_url": database_url,
            "api_keys": [TEST_KEY],
            # Off by default: the limiter is stateful and in-process, so shared
            # buckets would make the suite order-dependent. The limiter has its
            # own tests with limits switched on.
            "rate_limit_enabled": False,
            "environment": "test",
            "local_storage_dir": str(tmp_path / "artifacts"),
            # A closed port, so a health check cannot spend time on a real broker.
            "redis_url": "redis://127.0.0.1:1/0",
        }
        settings_overrides.update(overrides)

        # LifespanManager rather than TestClient: httpx's ASGI transport does not
        # run startup/shutdown, and the app's lifespan is what disposes the
        # engine between tests.
        try:
            with override_settings(**settings_overrides):
                async with (
                    LifespanManager(app, startup_timeout=10, shutdown_timeout=10),
                    AsyncClient(
                        transport=ASGITransport(app=app),
                        base_url="http://testserver",
                        headers={"X-API-Key": TEST_KEY},
                    ) as test_client,
                ):
                    clients.append(test_client)
                    yield test_client
        finally:
            session_module._engine = previous_engine
            session_module._session_factory = previous_factory
            await engine.dispose()

    yield _make


@pytest_asyncio.fixture
async def client(client_factory: Callable[..., Any]) -> AsyncIterator[AsyncClient]:
    """An async client with rate limiting disabled.

    Enters the factory's context here so tests can ``await client.get(...)``
    directly. Tests needing different settings use ``client_factory`` themselves
    rather than growing a fixture per combination.
    """
    async with client_factory() as test_client:
        yield test_client


@pytest.fixture
def spec() -> dict[str, Any]:
    """A valid one-shot spec payload."""
    return spec_payload()


@pytest.fixture
def auth() -> dict[str, str]:
    """A valid API key header."""
    return {"X-API-Key": TEST_KEY}


@pytest.fixture
def recipe_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """A recipe creation body with a unique name."""
    return {
        "name": f"deep-kick-{uuid.uuid4().hex[:8]}",
        "description": "A tuned 808-style kick.",
        "spec": spec,
    }


__all__ = [
    "SR",
    "TEST_KEY",
    "Audio",
    "ExplodingGenerator",
    "FakeGenerator",
    "FakeStorage",
    "GenerationError",
    "ModelLoadError",
    "RecordingQueue",
    "UnloadableGenerator",
    "band_db",
    "band_fraction_db",
    "harmonic_tone",
    "noise",
    "peak_db",
    "ramped_sine",
    "sine",
    "spec_payload",
]
