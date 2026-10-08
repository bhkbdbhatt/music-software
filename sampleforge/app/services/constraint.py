"""Constraint enforcement for generated samples.

This stage runs *after* the model has produced a raw waveform and *before* the
file is delivered. Its job is to turn a plausible-sounding sample into one that
provably satisfies the hard constraints in a :class:`~app.models.schemas.GenerationSpec`.

Design rules:

* **Pure function.** :func:`enforce_constraints` takes an array and returns a
  new array plus a report. The input is never mutated, nothing is cached
  between calls, and the module holds no global mutable state — so it is safe
  to call from a worker thread or to run concurrently across a batch.
* **No GPU.** Everything here is scipy/numpy DSP; the model already ran on the
  accelerator.
* **Deterministic.** Given the same audio and spec, the same report. No random
  seeds, no stateful filters.

Pipeline order, and why it deviates from the order the constraints are listed in:

1. Fundamental pitch enforcement (pYIN detect → :func:`librosa.effects.pitch_shift`)
2. Attack shaping, then release fade
3. Brick-wall low-pass at :attr:`~app.models.schemas.GenerationSpec.spectral_ceiling_hz`
4. High-pass at :attr:`~app.models.schemas.GenerationSpec.spectral_floor_hz`
5. M/S stereo-width control
6. **Peak normalisation last**

The filters come late for the same reason pitch correction comes early:
**every stage that is not band-limited dirties the spectrum.** A phase-vocoder
pitch shift resynthesises the whole signal; a time-warped attack resamples the
onset. Both splatter energy across the band. Run an 8th-order low-pass before
either and its work is undone in the part of the file that got stretched — so
the spectral filters are the last thing that touches the waveform, and the
ceiling is judged on the audio that actually ships.

The cost is that the attack measurement sees unfiltered audio, so a sample with
sub-floor rumble can read as having a marginally slower onset than it does. That
is a smaller error than shipping a file with out-of-band energy, and the
envelope stage is self-consistent: it measures the same signal it reshapes.

Peak normalisation runs at the end. Every earlier stage changes the waveform's
maximum sample — filters ring, pitch shifting resamples, fades remove
headroom — so normalising in the middle would leave the delivered file at the
wrong peak. Running it last makes ``peak_db`` exact, at the cost of the
attenuation being redistributed by the normaliser rather than by each stage,
which is what a mastering engineer would do anyway.

Constraints that are *not* enforced here: ``decay_ms`` and ``sustain_level``.
Shaping a decay curve onto an existing tail reliably produces an artefact that
worsens the sound in pursuit of a number, so those stay as model conditioning.
They are not reported either, so a caller can tell "not enforced" from
"enforced and failed" by key absence.

Example:
    >>> audio, report = enforce_constraints(raw, sr=44100, spec=spec)  # doctest: +SKIP
    >>> violations(report)  # doctest: +SKIP
    ['fundamental_hz']
"""

from __future__ import annotations

from typing import Final, Literal, TypedDict

import librosa
import numpy as np
import structlog
from numpy.typing import NDArray
from scipy.ndimage import median_filter
from scipy.signal import butter, sosfiltfilt

from app.models.schemas import GenerationSpec

log = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

#: 8th-order Butterworth: steep enough to read as a brick wall on a single
#: render, gentle enough that the zero-phase pass does not smear transients.
FILTER_ORDER: Final[int] = 8

#: Fraction of peak amplitude that defines "the attack has arrived". The
#: conventional 10% onset point: insensitive to a single noisy sample but
#: early enough to mean something perceptually.
ATTACK_THRESHOLD_RATIO: Final[float] = 0.1

#: Width bounds for the envelope smoother, in seconds. The window is derived
#: from the constraint being measured (see :func:`_envelope_width`) rather than
#: fixed, because a window wide enough to reject a carrier's ripple would also
#: smear a short attack.
ENVELOPE_MIN_SECONDS: Final[float] = 0.0002
ENVELOPE_MAX_SECONDS: Final[float] = 0.02

#: The envelope smoother uses this fraction of the constraint it is measuring,
#: so a 2 ms attack gets a sub-millisecond window and a 400 ms release gets a
#: 20 ms one.
ENVELOPE_WINDOW_FRACTION: Final[float] = 0.2

#: How far the last tenth of a release fade must sit below the first tenth,
#: as a linear ratio. 0.25 is a 12 dB drop, which both fade curves clear and a
#: hard cut cannot.
FADE_DEPTH_RATIO: Final[float] = 0.25

#: pYIN searches a range widened by this factor around the requested
#: fundamental band. The model can be wrong by more than a semitone, and the
#: pipeline has to know *how* wrong in order to compute the shift — but not by
#: much more, because every extra octave of search range is another octave in
#: which pYIN can report the wrong one.
DETECT_RANGE_FACTOR: Final[float] = 1.5

#: Tighter band for verifying a shift. The target window is known by then, so
#: the search only has to absorb correction error — and staying well below
#: ``2 * fundamental_hz[1]`` is what keeps an octave-up estimate (90 Hz
#: reported as 180) out of the results.
VERIFY_RANGE_FACTOR: Final[float] = 1.25

#: Bounds for pYIN, independent of the spec: below this nothing is audible as
#: a fundamental, and the top must stay under Nyquist.
DETECT_FMIN_HZ: Final[float] = 20.0
DETECT_FMAX_HEADROOM: Final[float] = 0.95

#: pYIN frame geometry. The hop is fixed for resolution; the frame length is
#: derived from the search band at call time (see
#: :func:`detect_fundamental_hz`). Explicit rather than default so detection
#: cost and accuracy do not shift if librosa changes its defaults.
PYIN_HOP_SECONDS: Final[float] = 0.0116

#: Minimum ratio of ``fmax`` to ``fmin`` for the pYIN search band. Narrower
#: bands leave pYIN's internal pitch range degenerate and it raises
#: ParameterError from pad_center, several frames deep, with a message about
#: array sizes that says nothing about the cause. A request like
#: ``fundamental_hz=[45, 55]`` is perfectly valid, so the band is widened instead
#: of refused; the estimate is then corrected into range by the caller.
PYIN_MIN_BAND_RATIO: Final[float] = 1.5

#: How far an onset may be time-stretched when a slow attack is
#: requested but the render already has a near-instant one. Past a few times
#: the stretch starts to smear transients instead of softening them, so the
#: pipeline reports the miss honestly instead of forcing it.
MAX_ATTACK_STRETCH: Final[float] = 4.0

#: Reflective padding applied before zero-phase filtering: a fraction of the
#: signal, or :data:`FILTER_PAD_SECONDS`, whichever is longer, capped at the
#: signal length.
FILTER_PAD_FRACTION: Final[float] = 0.25
FILTER_PAD_SECONDS: Final[float] = 0.05

#: Out-of-band energy tolerated after filtering, in dB relative to the input.
#: Deliberately looser than ``Tolerances.ceiling_violation_db`` (-40 dB):
#: that tolerance applies to the post-hoc analysis pass, which measures a
#: finished file, while this filter is still working on a finite buffer whose
#: edges it cannot fully control. -30 dB is a brick wall by any standard and is
#: what an 8th-order zero-phase pass reliably delivers here.
SPECTRAL_LEAK_TOLERANCE_DB: Final[float] = -30.0

#: Length of the fade applied at each end of the signal after filtering, to
#: remove the click that zero-phase filtering leaves on a buffer that starts and
#: ends in silence.
BOUNDARY_GUARD_SECONDS: Final[float] = 0.0005

#: How many times the attack is measured, corrected, and re-measured. One pass
#: is not always enough: measuring a 10 ms attack on a 55 Hz tone means
#: resolving a window far shorter than the carrier's period, so the reading
#: carries enough jitter to overshoot. Re-measuring and correcting again
#: converges, and the alternative — a wider smoothing window — would smear the
#: short attacks this stage exists to preserve.
MAX_ATTACK_PASSES: Final[int] = 3

ReleaseCurve = Literal["linear", "exponential"]

#: Types whose tails are sustained material, where an exponential fade keeps
#: constant power and avoids the audible "fade then silence" of a linear ramp.
SUSTAINED_TYPES: Final[frozenset[str]] = frozenset({"loop", "texture"})


class Measurement(TypedDict):
    """One constraint's target, measured result, and verdict.

    ``measured`` is ``None`` when a value could not be measured at all — an
    unvoiced signal has no fundamental to report. That is distinct from a
    measured value that happens to miss the target.
    """

    target: float | tuple[float, float] | None
    measured: float | tuple[float, float] | None
    met: bool


#: Constraint name -> measurement. JSON-serialisable by construction, so a
#: worker can drop it straight into a job record.
ConstraintReport = dict[str, Measurement]


def violations(report: ConstraintReport) -> list[str]:
    """Names of every constraint in ``report`` that was not met.

    Args:
        report: A report from :func:`enforce_constraints`.

    Returns:
        Constraint names whose ``met`` flag is ``False``, in report order.
    """
    return [name for name, result in report.items() if not result["met"]]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _as_2d(audio: FloatArray) -> FloatArray:
    """Return audio as a ``(n_samples, n_channels)`` float64 array.

    Raises:
        ValueError: If the array is empty, has more than two dimensions, or
            carries more than two channels.
    """
    if audio.size == 0:
        raise ValueError("audio is empty")
    if audio.ndim == 1:
        out = audio[:, np.newaxis].astype(np.float64, copy=False)
    elif audio.ndim == 2:
        out = audio.astype(np.float64, copy=False)
    else:
        raise ValueError(f"audio must be 1-D or 2-D, got {audio.ndim}-D")

    if out.shape[1] > 2:
        raise ValueError(f"only mono or stereo audio is supported, got {out.shape[1]} channels")
    return out


def _mono(audio_2d: FloatArray) -> FloatArray:
    """Downmix to a single channel. Analysis is done on the mono sum."""
    return audio_2d.mean(axis=1)


def _rms(signal: FloatArray) -> float:
    """Root-mean-square level of a 1-D signal."""
    if signal.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(signal))))


def _zero_phase_filter(audio_2d: FloatArray, sos: NDArray[np.float64], sr: int) -> FloatArray:
    """Apply an SOS filter along the time axis with zero phase distortion.

    Uses forward-backward filtering so the passband edge lands exactly on the
    requested frequency with no group-delay offset (which would otherwise smear
    the attack we are trying to measure).

    The signal is reflectively padded before filtering and trimmed afterwards.
    Two reasons, both of which bite on the short samples this pipeline deals in:
    ``filtfilt`` needs roughly three times its pad length to estimate edge
    transients, which a 100 ms hihat does not have; and those transients are not
    just a cosmetic artefact — an unpadded pass leaves 25 dB of sub-floor
    energy where a padded one leaves 44 dB, because the filter is being asked to
    treat a hard-cut buffer as if it were periodic.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sos: Second-order sections from :func:`scipy.signal.butter`.
        sr: Sample rate in Hz, used to size the padding in seconds.

    Returns:
        The filtered audio, same length and shape.
    """
    n_samples = audio_2d.shape[0]
    if n_samples < 2:
        return audio_2d

    pad = min(
        max(
            round(FILTER_PAD_FRACTION * n_samples),
            round(FILTER_PAD_SECONDS * sr),
        ),
        n_samples - 1,
    )
    if pad > 0:  # noqa: SIM108 - the branch keeps the no-pad case allocation-free
        padded = np.pad(audio_2d, ((pad, pad), (0, 0)), mode="reflect")
    else:
        padded = audio_2d

    # sosfiltfilt's own default, derived from the filter order.
    default_pad = 3 * (2 * len(sos) + 1 - min((sos[:, 2] == 0).sum(), (sos[:, 5] == 0).sum()))
    padlen = int(min(default_pad, max(0, padded.shape[0] - 1)))
    filtered = np.asarray(sosfiltfilt(sos, padded, axis=0, padlen=padlen), dtype=np.float64)

    if pad > 0:
        filtered = filtered[pad:-pad]
    return filtered


def _band_energy(audio_2d: FloatArray, sr: int, low_hz: float, high_hz: float) -> float:
    """Absolute energy in a frequency band, from an FFT of the mono downmix."""
    spectrum = np.abs(np.fft.rfft(_mono(audio_2d)))
    freqs = np.fft.rfftfreq(audio_2d.shape[0], d=1.0 / sr)
    band = spectrum[(freqs >= low_hz) & (freqs < high_hz)]
    return float(np.sum(band**2))


def _total_energy(audio_2d: FloatArray) -> float:
    """Absolute energy of the whole spectrum."""
    return float(np.sum(np.abs(np.fft.rfft(_mono(audio_2d))) ** 2))


def _db(energy: float, reference: float) -> float:
    """Energy in dB relative to a reference, floored at -200 dB.

    A ratio against an absolute reference rather than against the filtered
    signal's own total energy: once a filter has done its job the residual is
    pure edge ringing, and a self-referential ratio then reports that ringing
    as if it were meaningful signal.
    """
    if reference <= 0.0 or energy <= 0.0:
        return -200.0
    return max(-200.0, 10.0 * float(np.log10(energy / reference)))


def _envelope_width(sr: int, reference_ms: float | None) -> int:
    """Odd median-filter width for envelope extraction, in samples.

    Sized from the constraint being measured so the smoother never dominates
    it: a tenth of a 1 ms attack is a tenth of a millisecond, while a 200 ms
    release gets the 20 ms cap. Without ``reference_ms`` a mid-sized 10 ms
    window is assumed.

    Args:
        sr: Sample rate in Hz.
        reference_ms: The constraint's duration in ms, if known.

    Returns:
        An odd window length of at least 3 samples.
    """
    seconds = ENVELOPE_MAX_SECONDS
    if reference_ms is not None and reference_ms > 0.0:
        seconds = ENVELOPE_WINDOW_FRACTION * reference_ms / 1000.0
    seconds = min(max(seconds, ENVELOPE_MIN_SECONDS), ENVELOPE_MAX_SECONDS)
    width = max(3, round(seconds * sr))
    return width | 1  # force odd so the window stays centred


def _envelope(audio_2d: FloatArray, sr: int, reference_ms: float | None = None) -> FloatArray:
    """Amplitude envelope of a sample's mono downmix.

    Uses a median filter rather than a mean because the carrier's ripple is
    what makes naive onset detection fail: a 55 Hz sine under a rising envelope
    dips back under the 10% threshold on every cycle, which reports the attack
    as late as the carrier's half-period. A median rejects that entirely, since
    half of every window is always in a trough.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        reference_ms: Duration of the constraint being measured, used to size
            the smoothing window.

    Returns:
        A non-negative envelope, one value per sample.
    """
    return median_filter(np.abs(_mono(audio_2d)), size=_envelope_width(sr, reference_ms))


def _last_envelope_peak(env: FloatArray, floor_ratio: float) -> int | None:
    """Index of the last local maximum in the signal's audible region.

    The search is confined to the part of the envelope above ``floor_ratio``
    of peak, because the last sliver of any fade sits at effectively zero and
    trivially qualifies as a local maximum against flat padding.

    Args:
        env: Amplitude envelope from :func:`_envelope`.
        floor_ratio: Level, relative to the envelope's peak, bounding the
            searched region.

    Returns:
        The index, or ``None`` if the envelope never rises.
    """
    peak = float(np.max(env)) if env.size else 0.0
    if peak <= 0.0:
        return None
    audible = np.flatnonzero(env >= floor_ratio * peak)
    if audible.size == 0:
        return None

    region = env[: int(audible[-1]) + 1]
    if region.size < 3:
        return None
    is_max = (region[1:-1] >= region[:-2]) & (region[1:-1] >= region[2:])
    maxima = np.flatnonzero(is_max) + 1
    if maxima.size == 0:
        return None
    return int(maxima[-1])


def measure_attack_ms(
    audio_2d: FloatArray,
    sr: int,
    reference_ms: float | None = None,
) -> float:
    """Attack time of a rendered sample, in milliseconds.

    Defined as the time until the amplitude envelope first reaches 10% of peak.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        reference_ms: The requested attack, used to size the envelope smoother.

    Returns:
        Attack in milliseconds. A silent sample reports its full duration (it
        never starts), and a sample already above threshold at sample 0 reports
        0.0.
    """
    duration_ms = 1000.0 * audio_2d.shape[0] / sr
    env = _envelope(audio_2d, sr, reference_ms)
    peak = float(np.max(env)) if env.size else 0.0
    if peak <= 0.0:
        return duration_ms
    above = np.flatnonzero(env >= ATTACK_THRESHOLD_RATIO * peak)
    if above.size == 0:
        return duration_ms
    return 1000.0 * int(above[0]) / sr


def measure_release_ms(
    audio_2d: FloatArray,
    sr: int,
    reference_ms: float | None = None,
) -> float:
    """Inaudible tail of a rendered sample, in milliseconds.

    The time from the last sample above 10% of peak to the end of the file —
    how long the sample takes to become inaudible after its decay.

    This is a genuine measurement, but it is deliberately **not** what the
    release constraint is judged on. A fade of length L puts its final 10%
    (linear) or 33% (constant-dB) below the threshold, so this reading is a
    fixed fraction of the fade that was drawn and cannot be made to agree with
    an arbitrary ``release_ms``. Worse, the boundary between the model's own
    decay and the fade applied on top of it is not identifiable from the signal
    at all. :func:`_verify_release_fade` checks the fade itself instead.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        reference_ms: The expected release, used to size the envelope smoother.

    Returns:
        Tail length in milliseconds, or the full duration for a sample that
        never falls below the threshold.
    """
    env = _envelope(audio_2d, sr, reference_ms)
    peak = float(np.max(env)) if env.size else 0.0
    if peak <= 0.0:
        return 1000.0 * audio_2d.shape[0] / sr
    audible = np.flatnonzero(env >= ATTACK_THRESHOLD_RATIO * peak)
    if audible.size == 0:
        return 1000.0 * audio_2d.shape[0] / sr
    return 1000.0 * (env.size - 1 - int(audible[-1])) / sr


def _verify_release_fade(audio_2d: FloatArray, sr: int, release_ms: float) -> float:
    """Confirm a tail fade of ``release_ms`` exists, and return its length.

    Checks that the final ``release_ms`` of the sample descend — and descend
    far enough that the last tenth of the fade is well below the first tenth.
    That is the property a release constraint is really about, and unlike a
    threshold-crossing measurement it is not confounded by where the fade
    happens to begin.

    The comparison uses two narrow slices rather than the whole window: a
    linear fade's first third averages 5x its last third, so any threshold tight
    enough to be meaningful fails on the curve's shape instead of on a missing
    fade. Ten per cent in, ten per cent out is a 12 dB drop, which both the
    linear and constant-dB curves clear comfortably and a hard cut cannot.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        release_ms: Expected fade length.

    Returns:
        ``release_ms`` if such a fade is present, otherwise ``0.0``.
    """
    n_samples = audio_2d.shape[0]
    fade_samples = round(release_ms * sr / 1000.0)
    if fade_samples < 10 or fade_samples >= n_samples:
        return 0.0

    env = _envelope(audio_2d, sr, release_ms)
    if float(np.max(env)) <= 0.0:
        return 0.0

    window = max(4, fade_samples // 10)
    fade_start = n_samples - fade_samples
    head_level = float(np.max(env[fade_start : fade_start + window]))
    tail_level = float(np.max(env[n_samples - window :]))
    if head_level <= 0.0 or tail_level > FADE_DEPTH_RATIO * head_level:
        return 0.0  # flat, rising, or barely descending: not a fade
    return release_ms


def _widen_band(fmin_hz: float, fmax_hz: float, nyquist_hz: float) -> tuple[float, float]:
    """Widen a search band geometrically until pYIN can analyse it.

    Args:
        fmin_hz: Requested lower edge in Hz.
        fmax_hz: Requested upper edge in Hz.
        nyquist_hz: Highest analysable frequency in Hz.

    Returns:
        The widened ``(fmin, fmax)``, capped at ``nyquist_hz``.
    """
    while fmax_hz / fmin_hz < PYIN_MIN_BAND_RATIO and fmax_hz < nyquist_hz:
        spread = float(np.sqrt(PYIN_MIN_BAND_RATIO))
        fmin_hz = max(DETECT_FMIN_HZ, fmin_hz / spread)
        fmax_hz = min(nyquist_hz, fmax_hz * spread)
    return fmin_hz, fmax_hz


def detect_fundamental_hz(
    audio_2d: FloatArray,
    sr: int,
    fmin_hz: float,
    fmax_hz: float,
) -> float | None:
    """Estimate the fundamental frequency with pYIN.

    pYIN is used rather than a bare FFT peak because it resolves octave errors
    — the difference between reporting a 55 Hz kick fundamental and its 110 Hz
    harmonic is exactly the mistake this pipeline exists to correct.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        fmin_hz: Lowest frequency to consider.
        fmax_hz: Highest frequency to consider.

    Returns:
        The median voiced pitch estimate in Hz, or ``None`` if no frame was
        voiced (noise, a silent buffer, a pitch outside the search band).
    """
    fmin_hz = max(DETECT_FMIN_HZ, float(fmin_hz))
    fmax_hz = float(fmax_hz)
    nyquist = 0.5 * sr
    fmax_hz = min(DETECT_FMAX_HEADROOM * nyquist, fmax_hz)
    if fmax_hz <= fmin_hz:
        return None

    # Widen a band too narrow for pYIN to analyse, geometrically and
    # symmetrically so the requested range stays centred. Capped at Nyquist, so a
    # narrow band high in the spectrum widens only as far as it can.
    if fmax_hz / fmin_hz < PYIN_MIN_BAND_RATIO:
        fmin_hz, fmax_hz = _widen_band(fmin_hz, fmax_hz, nyquist)

    n_samples = audio_2d.shape[0]
    # pYIN needs at least one full period of fmin inside the analysis window,
    # and warns that accuracy suffers below two. A 20 Hz search floor therefore
    # asks for 50-100 ms of audio, so the frame grows to fit whatever the
    # search band demands. When the sample is too short even for one period
    # there is no honest pitch to report.
    one_period = int(np.ceil(sr / fmin_hz)) + 2
    two_periods = int(np.ceil(2.0 * sr / fmin_hz)) + 2
    if n_samples < one_period:
        return None
    frame_length = two_periods if n_samples >= two_periods else one_period
    frame_length = min(frame_length, n_samples)

    hop_length = min(round(PYIN_HOP_SECONDS * sr), max(1, frame_length // 2))

    mono = _mono(audio_2d).astype(np.float32)
    if not np.any(np.abs(mono) > 1e-6):
        return None

    try:
        f0, _, _ = librosa.pyin(
            y=mono,
            fmin=fmin_hz,
            fmax=fmax_hz,
            sr=sr,
            frame_length=frame_length,
            hop_length=hop_length,
        )
    except librosa.util.exceptions.ParameterError:
        # Belt and braces. The band is widened above precisely to keep this
        # unreachable, but pYIN's internal contracts are not documented and could
        # tighten; a failed measurement must degrade to "cannot measure", never to
        # an exception that fails the whole job with an array-size message.
        log.warning(
            "fundamental_detection_failed",
            fmin_hz=fmin_hz,
            fmax_hz=fmax_hz,
            frame_length=frame_length,
        )
        return None
    voiced = f0[~np.isnan(f0)]
    if voiced.size == 0:
        return None
    return float(np.median(voiced))


def _pitch_shift(audio_2d: FloatArray, sr: int, semitones: float) -> FloatArray:
    """Shift every channel by ``semitones``, preserving length.

    Channels are shifted independently. That preserves the inter-channel level
    balance exactly; the cost is a small change in inter-channel phase, which
    can narrow the perceived image. Pitch-shifting the mid channel alone would
    avoid that but cannot be done without a phase-vocoder implementation that
    understands M/S, which librosa does not provide.

    A large shift makes the phase vocoder numerically fragile — extreme
    semitone counts can emit NaN or inf. Those are scrubbed to silence here:
    a NaN sample would propagate through every later stage and poison the peak
    normalisation, turning one bad variant into a failed job.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        semitones: Signed shift in semitones.

    Returns:
        The shifted audio, same length and shape.
    """
    if semitones == 0.0:
        return audio_2d.copy()
    shifted = np.empty_like(audio_2d)
    for channel in range(audio_2d.shape[1]):
        shifted[:, channel] = librosa.effects.pitch_shift(
            y=audio_2d[:, channel].astype(np.float32),
            sr=sr,
            n_steps=semitones,
        )
    shifted = shifted.astype(np.float64, copy=False)

    finite = np.isfinite(shifted)
    if not finite.all():
        bad = int(np.count_nonzero(~finite))
        log.warning(
            "pitch_shift_emitted_non_finite_samples",
            semitones=semitones,
            samples=bad,
        )
        shifted = np.where(finite, shifted, 0.0)
    return shifted


def _warp_attack(
    audio_2d: FloatArray,
    sr: int,
    measured_ms: float,
    target_ms: float,
) -> FloatArray | None:
    """Move an onset to the requested attack time by warping time, not gain.

    Gain envelopes alone cannot fix attack time. You can only attenuate the
    early samples, and attenuating a rising edge pushes the onset *later* than
    it was rather than sooner. So the onset region is time-warped instead: input
    positions map onto output positions piecewise-linearly, compressing the
    region when the render is too slow and stretching it when it is too fast.

    * ``[0, measured]`` maps onto ``[0, target]`` — compressed by
      ``measured / target`` when shortening, stretched by the reciprocal when
      lengthening.
    * ``[measured, end]`` is scaled by the reciprocal deficit, so the file keeps
      its original length and keeps all of its content. The compensation is
      small: an 8 ms correction on an 800 ms sample moves the tail by well under
      1%.

    Both directions land the *measured* attack on the target, which a fade
    cannot promise: a linear fade-in of length T only reaches 10% of peak at
    T/10, so fading in for the requested attack would measure a tenth of it.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        measured_ms: Currently measured attack.
        target_ms: Requested attack.

    Returns:
        The warped audio, length unchanged, or ``None`` when the warp cannot be
        performed: a stretch beyond :data:`MAX_ATTACK_STRETCH`, a target that
        would fill the whole sample, or a measured attack of zero samples.
    """
    n_samples = audio_2d.shape[0]
    measured = round(measured_ms * sr / 1000.0)
    target = round(target_ms * sr / 1000.0)

    if target > measured:
        if measured < 1:
            return None
        stretch = target / measured
        if stretch > MAX_ATTACK_STRETCH:
            log.warning(
                "attack_stretch_exceeds_cap",
                measured_ms=measured_ms,
                target_ms=target_ms,
                stretch=stretch,
                cap=MAX_ATTACK_STRETCH,
            )
            return None
        target = min(round(measured * MAX_ATTACK_STRETCH), n_samples - 1)
    else:
        target = max(target, 1)
    if target >= n_samples or measured >= n_samples:
        return None

    out_index = np.arange(n_samples, dtype=np.float64)
    in_index = np.where(
        out_index < target,
        out_index * (measured / target),
        measured + (out_index - target) * ((n_samples - measured) / (n_samples - target)),
    )
    in_index = np.clip(in_index, 0.0, n_samples - 1.0)

    warped = np.empty_like(audio_2d)
    source = np.arange(n_samples, dtype=np.float64)
    for channel in range(audio_2d.shape[1]):
        warped[:, channel] = np.interp(in_index, source, audio_2d[:, channel])
    log.debug(
        "attack_warped",
        measured_ms=measured_ms,
        target_ms=target_ms,
        direction="shorten" if measured > target else "lengthen",
    )
    return warped


def _fade_gain(curve: ReleaseCurve, n: int) -> FloatArray:
    """A fade from unity to exact silence over ``n`` samples.

    ``linear`` falls off proportionally, which is what a percussive tail wants:
    it reaches silence at a predictable rate. ``exponential`` decays at a
    constant 60 dB across the fade and is rescaled to still reach true zero,
    which holds perceived power steady through the fade rather than dropping
    away — the reason sustained material uses it.
    """
    position = np.arange(n, dtype=np.float64) / max(1, n - 1)
    if curve == "exponential":
        span_db = 60.0
        gain = (np.power(10.0, -span_db * position / 20.0) - 10.0 ** (-span_db / 20.0)) / (
            1.0 - 10.0 ** (-span_db / 20.0)
        )
    else:
        gain = 1.0 - position
    return np.clip(gain, 0.0, 1.0)


def _apply_release_fade(
    audio_2d: FloatArray,
    sr: int,
    release_ms: float,
    curve: ReleaseCurve,
) -> FloatArray:
    """Fade the tail of the sample to silence over ``release_ms``.

    The fade is drawn over exactly ``release_ms`` samples, which is what
    :func:`measure_release_ms` then reports (it measures from the last envelope
    maximum, and the fade starts there).

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        release_ms: Length of the fade.
        curve: Fade shape, see :data:`SUSTAINED_TYPES` for the selection rule.

    Returns:
        The faded audio. The fade is skipped when it would cover the whole
        sample, which would just be a volume ramp.
    """
    n_samples = audio_2d.shape[0]
    fade_samples = round(release_ms * sr / 1000.0)
    if fade_samples < 1 or fade_samples >= n_samples:
        return audio_2d

    faded = audio_2d.copy()
    faded[-fade_samples:, :] *= _fade_gain(curve, fade_samples)[:, np.newaxis]
    return faded


def _apply_attack_fade(
    audio_2d: FloatArray,
    sr: int,
    target_ms: float,
) -> FloatArray:
    """Fallback de-click fade-in when an onset cannot be time-warped.

    Used when the render's onset is essentially instantaneous (no measurable
    attack to stretch) and the requested attack is longer than
    :data:`MAX_ATTACK_STRETCH` would allow. This trades a click for a late hit,
    so it is the last resort and the resulting measurement is reported as-is.

    Unlike :func:`_apply_release_fade` this ramps *up* from silence, so it uses
    its own gain curve rather than the release fade's — that one is unity at
    its first sample by design.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        target_ms: Requested attack.

    Returns:
        The faded audio, or the input unchanged if the ramp would cover the
        whole sample.
    """
    n_samples = audio_2d.shape[0]
    ramp = round(target_ms * sr / 1000.0)
    if ramp < 1 or ramp >= n_samples:
        return audio_2d

    # 0.0 at the first sample, exactly 1.0 at the last, so the ramp joins the
    # untreated audio without a step.
    gain = np.linspace(0.0, 1.0, ramp, dtype=np.float64)
    faded = audio_2d.copy()
    faded[:ramp, :] *= gain[:, np.newaxis]
    return faded


def _apply_stereo_width(audio_2d: FloatArray, target_ratio: float) -> FloatArray:
    """Scale the side channel to hit a target side/mid RMS ratio.

    Works in M/S: ``mid = (L + R) / 2`` carries everything common to both
    channels and ``side = (L - R) / 2`` carries the stereo difference. Only the
    side channel is scaled, so the mono compatibility sum is untouched and the
    target width holds regardless of how the material is mixed.

    Args:
        audio_2d: ``(n_samples, 2)`` stereo audio.
        target_ratio: Desired ``rms(side) / rms(mid)``. 0.0 collapses to mono.

    Returns:
        The widened or narrowed audio. Returns the input unchanged for mono
        input or when the mid level is zero and the ratio is therefore
        undefined.
    """
    if audio_2d.shape[1] != 2:
        return audio_2d

    mid = (audio_2d[:, 0] + audio_2d[:, 1]) / 2.0
    side = (audio_2d[:, 0] - audio_2d[:, 1]) / 2.0
    mid_rms = _rms(mid)
    if mid_rms <= 0.0:
        return audio_2d

    current_ratio = _rms(side) / mid_rms
    gain = target_ratio / current_ratio if current_ratio > 0.0 else target_ratio
    if np.isclose(gain, 1.0):
        return audio_2d

    side = side * gain
    return np.stack([mid + side, mid - side], axis=1)


def measure_stereo_width(audio_2d: FloatArray) -> float | None:
    """Side/mid RMS ratio of a stereo sample.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.

    Returns:
        The ratio, or ``None`` for mono input or when the mid level is zero.
    """
    if audio_2d.shape[1] != 2:
        return None
    mid = (audio_2d[:, 0] + audio_2d[:, 1]) / 2.0
    mid_rms = _rms(mid)
    if mid_rms <= 0.0:
        return None
    return _rms((audio_2d[:, 0] - audio_2d[:, 1]) / 2.0) / mid_rms


# ----------------------------------------------------------------------
# Stages
# ----------------------------------------------------------------------
def _boundary_guard(audio_2d: FloatArray, sr: int) -> FloatArray:
    """Fade the outermost :data:`BOUNDARY_GUARD_SECONDS` to silence.

    The spectral filters run after the envelope stages, and zero-phase
    filtering a buffer that begins and ends at exactly zero leaves ringing at
    both ends — around -33 dB relative to peak, which is an audible click on
    every render. Half a millisecond of fade at each edge removes it and is far
    below the threshold of notice, even for the shortest transient this pipeline
    handles.
    """
    n_samples = audio_2d.shape[0]
    guard = min(round(BOUNDARY_GUARD_SECONDS * sr), n_samples // 2)
    if guard < 1:
        return audio_2d

    rise = np.linspace(0.0, 1.0, guard, dtype=np.float64)
    gain = np.concatenate([rise, np.ones(n_samples - 2 * guard, dtype=np.float64), rise[::-1]])
    return audio_2d * gain[:, np.newaxis]


def _enforce_spectral_ceiling(
    audio_2d: FloatArray, sr: int, spec: GenerationSpec
) -> tuple[FloatArray, Measurement]:
    """Brick-wall low-pass at the requested ceiling."""
    ceiling = spec.spectral_ceiling_hz
    nyquist = 0.5 * sr
    if ceiling >= nyquist:
        # Already above the representable band; nothing to remove.
        return audio_2d, {"target": ceiling, "measured": ceiling, "met": True}

    sos = butter(FILTER_ORDER, ceiling, btype="lowpass", fs=sr, output="sos")
    filtered = _zero_phase_filter(audio_2d, sos, sr)
    # Out-of-band leakage, reported relative to the energy that came *in*.
    # Referencing the filtered signal instead would be self-defeating: once a
    # filter removes nearly everything, its own edge ringing becomes the
    # denominator, and a 170 dB-clean signal reads as a 50/50 split.
    #
    # The verdict is deliberately not "less energy above the ceiling than
    # before". An 8th-order filter rings, so on a signal with nothing near the
    # ceiling it can leave a hair more energy up there than it started with —
    # a false alarm about a filter that did its job.
    leak_db = _db(_band_energy(filtered, sr, ceiling, nyquist), _total_energy(audio_2d))
    return filtered, {
        "target": ceiling,
        "measured": leak_db,
        "met": bool(leak_db <= SPECTRAL_LEAK_TOLERANCE_DB),
    }


def _enforce_spectral_floor(
    audio_2d: FloatArray, sr: int, spec: GenerationSpec
) -> tuple[FloatArray, Measurement]:
    """High-pass at the requested floor."""
    floor = spec.spectral_floor_hz
    if floor <= 0.0:
        return audio_2d, {"target": floor, "measured": floor, "met": True}

    sos = butter(FILTER_ORDER, floor, btype="highpass", fs=sr, output="sos")
    filtered = _zero_phase_filter(audio_2d, sos, sr)
    # Sub-floor leakage, on the same basis as the ceiling. It shares the
    # ceiling's threshold: it is the same question asked of the other end of
    # the band.
    leak_db = _db(_band_energy(filtered, sr, 0.0, floor), _total_energy(audio_2d))
    return filtered, {
        "target": floor,
        "measured": leak_db,
        "met": bool(leak_db <= SPECTRAL_LEAK_TOLERANCE_DB),
    }


def _enforce_fundamental(
    audio_2d: FloatArray, sr: int, spec: GenerationSpec
) -> tuple[FloatArray, Measurement]:
    """Pitch-shift the sample into the requested fundamental band."""
    low, high = spec.fundamental_hz
    tol = spec.tolerances.fundamental_hz
    nyquist = 0.5 * sr
    nyquist_cap = DETECT_FMAX_HEADROOM * nyquist
    search_low = max(DETECT_FMIN_HZ, low / DETECT_RANGE_FACTOR)
    search_high = min(nyquist_cap, high * DETECT_RANGE_FACTOR)

    detected = detect_fundamental_hz(audio_2d, sr, search_low, search_high)
    if detected is None:
        log.warning(
            "fundamental_undetectable",
            category=spec.category,
            detect_band=[search_low, search_high],
        )
        return audio_2d, {
            "target": (low, high),
            "measured": None,
            "met": False,
        }

    in_range = low - tol <= detected <= high + tol
    if in_range:
        return audio_2d, {
            "target": (low, high),
            "measured": detected,
            "met": True,
        }

    # Out of range: shift by the semitone distance from where it is to the
    # nearest edge of the window, so the correction is the smallest one that
    # can succeed.
    target_hz = min(max(detected, low), high)
    semitones = 12.0 * float(np.log2(target_hz / detected))
    shifted = _pitch_shift(audio_2d, sr, semitones)

    verify_low = max(DETECT_FMIN_HZ, low / VERIFY_RANGE_FACTOR)
    verify_high = min(nyquist_cap, high * VERIFY_RANGE_FACTOR)
    remeasured = detect_fundamental_hz(shifted, sr, verify_low, verify_high)
    met = remeasured is not None and low - tol <= remeasured <= high + tol
    log.info(
        "fundamental_corrected",
        category=spec.category,
        detected_hz=detected,
        shift_semitones=semitones,
        remeasured_hz=remeasured,
        met=met,
    )
    if not met:
        log.warning(
            "fundamental_constraint_violation",
            category=spec.category,
            target=(low, high),
            measured=remeasured,
            shift_semitones=semitones,
        )
    return shifted, {
        "target": (low, high),
        "measured": remeasured,
        "met": bool(met),
    }


def _normalize_peak(audio_2d: FloatArray, peak_db: float) -> tuple[FloatArray, Measurement]:
    """Scale the sample so its absolute peak sits at ``peak_db`` dBFS."""
    peak = float(np.max(np.abs(audio_2d))) if audio_2d.size else 0.0
    if peak <= 0.0:
        # Silence in, silence out; normalising would only amplify dither.
        return audio_2d, {"target": peak_db, "measured": None, "met": False}

    target_linear = 10.0 ** (peak_db / 20.0)
    normalised = audio_2d * (target_linear / peak)
    measured_db = 20.0 * float(np.log10(float(np.max(np.abs(normalised)))))
    return normalised, {
        "target": peak_db,
        "measured": measured_db,
        "met": bool(abs(measured_db - peak_db) <= 1e-6),
    }


def _correct_attack(
    audio_2d: FloatArray, sr: int, spec: GenerationSpec
) -> tuple[FloatArray, float]:
    """Bring the measured attack onto the requested value, if it can be done.

    Measures, warps, and re-measures up to :data:`MAX_ATTACK_PASSES` times,
    stopping as soon as the reading is within tolerance.

    Args:
        audio_2d: ``(n_samples, n_channels)`` audio.
        sr: Sample rate in Hz.
        spec: Supplies ``attack_ms`` and its tolerance.

    Returns:
        The corrected audio and its measured attack. When the attack cannot be
        corrected — an instantaneous onset with no room to stretch, or a sample
        too short to reshape — the audio is de-clicked with
        :func:`_apply_attack_fade` and the honest measurement is returned.
    """
    target = spec.attack_ms
    tol = spec.tolerances.attack_ms
    measured = measure_attack_ms(audio_2d, sr, target)

    for _ in range(MAX_ATTACK_PASSES):
        if abs(measured - target) <= tol:
            return audio_2d, measured
        warped = _warp_attack(audio_2d, sr, measured, target)
        if warped is None:
            break
        audio_2d = warped
        remeasured = measure_attack_ms(audio_2d, sr, target)
        if abs(remeasured - measured) < 1e-6:
            break  # no longer moving: warping cannot reach the target
        measured = remeasured

    return _apply_attack_fade(audio_2d, sr, target), measure_attack_ms(audio_2d, sr, target)


def _shape_envelope(
    audio_2d: FloatArray, sr: int, spec: GenerationSpec
) -> tuple[FloatArray, Measurement, Measurement]:
    """Correct the attack, then fade the release."""
    audio_2d, final_attack = _correct_attack(audio_2d, sr, spec)
    attack_measurement: Measurement = {
        "target": spec.attack_ms,
        "measured": final_attack,
        "met": bool(abs(final_attack - spec.attack_ms) <= spec.tolerances.attack_ms),
    }

    curve: ReleaseCurve = "exponential" if spec.type in SUSTAINED_TYPES else "linear"
    audio_2d = _apply_release_fade(audio_2d, sr, spec.release_ms, curve)
    verified_release = _verify_release_fade(audio_2d, sr, spec.release_ms)
    release_measurement: Measurement = {
        "target": spec.release_ms,
        "measured": verified_release,
        "met": bool(verified_release > 0.0),
    }
    return audio_2d, attack_measurement, release_measurement


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def enforce_constraints(
    audio: FloatArray,
    sr: int,
    spec: GenerationSpec,
) -> tuple[FloatArray, ConstraintReport]:
    """Enforce every hard constraint in ``spec`` on a rendered sample.

    This is the single entry point for the post-generation stage. It is pure:
    ``audio`` is not modified, and the same arguments always produce the same
    output and report.

    The stages run in the order documented at the module level — pitch
    correction, envelope shaping, filters, stereo width, then peak normalisation
    last — because every stage before the filters dirties the spectrum.

    Args:
        audio: Raw rendered sample, ``(n_samples,)`` mono or
            ``(n_samples, n_channels)``. Sample values may use any scale; the
            result is normalised to the spec's peak.
        sr: Sample rate in Hz. Must match the spec's :attr:`sample_rate`, since
            the spectral constraints are absolute frequencies.
        spec: The spec whose hard constraints should be enforced.

    Returns:
        A tuple of ``(processed_audio, constraint_report)``. The audio has the
        same shape as the input. The report maps each enforced constraint to
        its :class:`Measurement`; keys whose constraint does not apply to this
        audio (for example ``stereo_width`` on a mono render) are absent, so
        callers can distinguish "not evaluated" from "failed".

    Raises:
        ValueError: If ``audio`` is empty, is not 1-D or 2-D, has more than
            two channels, or ``sr`` does not match the spec's sample rate.

    Example:
        >>> processed, report = enforce_constraints(raw, sr, spec)  # doctest: +SKIP
        >>> violations(report)  # doctest: +SKIP
        []
    """
    if sr != spec.sample_rate:
        raise ValueError(
            f"audio sample rate {sr} does not match spec sample_rate "
            f"{spec.sample_rate}; spectral constraints are absolute frequencies"
        )

    working = _as_2d(audio)
    was_mono_1d = audio.ndim == 1
    report: ConstraintReport = {}

    working, fundamental_result = _enforce_fundamental(working, sr, spec)
    report["fundamental_hz"] = fundamental_result

    working, attack_result, release_result = _shape_envelope(working, sr, spec)
    report["attack_ms"] = attack_result
    report["release_ms"] = release_result

    # Filters last: pitch shifting and time warping both splatter energy, so
    # anything band-limiting has to come after them to mean anything.
    working, ceiling_result = _enforce_spectral_ceiling(working, sr, spec)
    report["spectral_ceiling_hz"] = ceiling_result

    working, floor_result = _enforce_spectral_floor(working, sr, spec)
    report["spectral_floor_hz"] = floor_result

    # Last step to touch the time domain: the filters have left ringing at both
    # ends, and this removes it.
    working = _boundary_guard(working, sr)

    if spec.stereo_width is not None:
        working = _apply_stereo_width(working, spec.stereo_width)
        measured_width = measure_stereo_width(working)
        if measured_width is None:
            # Mono render (or a silent mid channel): there is no stereo image to
            # measure, so the constraint is not applicable rather than unmet.
            # Reporting it as a miss would flag every mono job that sets
            # stereo_width as complete_with_warnings, and would claim a
            # verification that never happened. The module contract is that
            # inapplicable constraints are absent from the report.
            log.debug(
                "stereo_width_not_applicable",
                reason="mono_render"
                if working.ndim == 1 or working.shape[1] != 2
                else "silent_mid",
            )
        else:
            report["stereo_width"] = {
                "target": spec.stereo_width,
                "measured": measured_width,
                "met": bool(
                    abs(measured_width - spec.stereo_width) <= spec.tolerances.stereo_width
                ),
            }

    working, peak_result = _normalize_peak(working, spec.peak_db)
    report["peak_db"] = peak_result

    failed = violations(report)
    if failed:
        log.warning(
            "constraints_violated",
            category=spec.category,
            job_constraints=failed,
        )

    # Hand back the shape we were given: a 1-D input stays 1-D so callers that
    # pass mono buffers do not suddenly have to handle a channel axis.
    return (working[:, 0] if was_mono_1d else working), report
