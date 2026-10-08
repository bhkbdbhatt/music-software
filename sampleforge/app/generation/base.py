"""Generator interface and the errors the worker reacts to.

The concrete model lives in :mod:`app.generation.vae_model`. Everything here is
about the contract: what a generator must be able to do, and which failures are
worth retrying.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from app.models.schemas import GenerationSpec

#: A rendered sample: mono ``(n_samples,)`` or stereo ``(n_samples, channels)``.
Audio = NDArray[np.float64]


class ModelLoadError(RuntimeError):
    """The generator's weights could not be loaded.

    Never transient — retrying a missing or corrupt checkpoint just burns GPU
    time — so the worker maps it straight to ``model_load_failed``.
    """


class GenerationError(RuntimeError):
    """Inference failed for a reason unrelated to the model's inputs.

    Split from ordinary exceptions so a caller can distinguish "the model
    failed" from "the spec was rejected", which is a client error and must not
    be retried.
    """


@runtime_checkable
class Generator(Protocol):
    """What the worker needs from a sample generator."""

    async def load(self) -> None:
        """Load weights onto the configured device.

        Raises:
            ModelLoadError: If the weights are missing, unreadable, or
                incompatible with the installed torch build.
        """
        ...

    async def generate(self, spec: GenerationSpec, *, seed: int) -> Audio:
        """Render one sample matching ``spec``.

        Args:
            spec: The constraints and conditioning to satisfy.
            seed: Seeds the sampling noise. The same seed and spec must produce
                the same audio, or batch diversity is not reproducible.

        Returns:
            The raw rendered audio, before constraint enforcement and encoding.

        Raises:
            GenerationError: If inference fails.
        """
        ...

    async def close(self) -> None:
        """Release device memory. Safe to call more than once."""
        ...
