"""Encoding rendered audio to a deliverable file.

All three output formats go through libsndfile via :mod:`soundfile` rather than
pydub. libsndfile writes MP3 natively (since 1.1), so this keeps the worker
free of an ffmpeg binary in the image — one fewer thing to go wrong in a
container — and avoids pydub's silent degradation to WAV when ffmpeg is
missing.
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from app.models.schemas import GenerationSpec

#: libsndfile subtype per output format. 16-bit would be a downgrade from the
#: spec's 24-bit default, so 24-bit is used wherever the container supports it.
_SUBTYPES: dict[str, str] = {
    "wav": "PCM_24",
    "flac": "PCM_24",
    # MP3 is a lossy format with no bit-depth choice; the encoder is 128 kbit/s.
    "mp3": "MPEG_LAYER_III",
}


def normalise_for_write(audio: NDArray[np.float64]) -> NDArray[np.float32]:
    """Coerce audio into the layout and dtype :mod:`soundfile` expects.

    Args:
        audio: ``(n_samples,)`` mono or ``(n_samples, channels)``.

    Returns:
        A contiguous float32 array — ``(n_samples, 1)`` for mono input, so the
        file is written as a single channel rather than as an interleaved pair
        of identical ones.

    Raises:
        ValueError: If the array is empty or has more than two dimensions.
    """
    if audio.size == 0:
        raise ValueError("audio is empty")
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        array = array[:, np.newaxis]
    elif array.ndim != 2:
        raise ValueError(f"audio must be 1-D or 2-D, got {array.ndim}-D")
    return np.ascontiguousarray(array)


def encode_audio(
    audio: NDArray[np.float64],
    sr: int,
    spec: GenerationSpec,
) -> bytes:
    """Encode a sample into the format the spec asked for.

    Args:
        audio: Processed audio, mono or stereo.
        sr: Sample rate in Hz. Must match ``spec.sample_rate`` — encoding at a
            different rate would resample and invalidate the spectral
            constraints already enforced.
        spec: Supplies ``format``, ``bit_depth``, and ``channels``.

    Returns:
        The encoded file's bytes, ready to upload.

    Raises:
        ValueError: If the sample rate disagrees with the spec, or the audio
            shape is unusable.
    """
    if sr != spec.sample_rate:
        raise ValueError(
            f"audio sample rate {sr} does not match spec sample_rate {spec.sample_rate}"
        )

    data = normalise_for_write(audio)
    if data.shape[1] > spec.channels:
        # Downmix rather than truncate: dropping a channel would silently
        # discard half the file's content.
        data = data.mean(axis=1, keepdims=True)
    elif data.shape[1] < spec.channels:
        data = np.repeat(data, spec.channels, axis=1)

    buffer = io.BytesIO()
    sf.write(
        buffer,
        data,
        sr,
        format=spec.format.upper(),
        subtype=_SUBTYPES[spec.format],
    )
    return buffer.getvalue()


def decode_audio(data: bytes) -> tuple[NDArray[np.float64], int]:
    """Decode encoded bytes back to audio. The inverse of :func:`encode_audio`.

    Args:
        data: Encoded file bytes.

    Returns:
        The audio and its sample rate.

    Raises:
        ValueError: If the bytes are not a file libsndfile recognises.
    """
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float64", always_2d=True)
    except Exception as exc:  # libsndfile raises RuntimeError subclasses
        raise ValueError(f"could not decode audio: {exc}") from exc
    return audio, sr
