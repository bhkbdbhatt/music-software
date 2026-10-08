"""Generator lifecycle management.

Holds one loaded generator per process behind an :class:`asyncio.Lock`. Loading
is serialised because two jobs arriving together would otherwise each allocate
a copy of the weights and can OOM a GPU that could hold one. Keeping the
instance here — rather than in a route handler or the task — means the API and
the workers share the same load path.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.generation.base import Generator, ModelLoadError

log = get_logger(__name__)

#: Invoked the first time a generator is needed. Tests and local development
#: replace this to supply a fake; production points it at the real model.
_generator_factory: object | None = None

_lock = asyncio.Lock()
_generator: Generator | None = None


def set_generator_factory(factory: object) -> None:
    """Install the callable that builds the generator.

    Args:
        factory: A zero-argument callable returning a :class:`Generator`.
    """
    global _generator_factory, _generator
    _generator_factory = factory
    _generator = None


def reset_generator() -> None:
    """Drop the cached generator so the next call reloads it.

    Used by tests and by a worker restart after an OOM.
    """
    global _generator
    _generator = None


def is_generator_loaded() -> bool:
    """Whether this process already holds a loaded generator.

    Read by ``/v1/health``. Separate from :func:`get_generator` on purpose:
    health must never trigger a model load, which would put a multi-gigabyte
    GPU allocation behind a health check.
    """
    return _generator is not None


async def get_generator() -> Generator:
    """Return the process-wide generator, loading it on first use.

    Returns:
        A loaded generator.

    Raises:
        ModelLoadError: If no factory is installed, or loading fails.
    """
    global _generator
    if _generator is not None:
        return _generator

    async with _lock:
        # Another coroutine may have loaded it while we waited on the lock.
        if _generator is not None:
            return _generator

        if _generator_factory is None:
            raise ModelLoadError(
                "no generator factory registered; call set_generator_factory() "
                "or implement app.generation.vae_model"
            )
        log.info("generator_loading")
        generator = _generator_factory()  # type: ignore[operator]
        await generator.load()
        _generator = generator
        log.info("generator_loaded", type=type(generator).__name__)
        return _generator
