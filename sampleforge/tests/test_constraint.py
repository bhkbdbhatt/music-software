"""Tests for the constraint enforcement pipeline."""

from __future__ import annotations

import numpy as np
import pytest
from app.models.schemas import GenerationSpec
from app.services.constraint import (
    enforce_constraints,
    measure_attack_ms,
    measure_release_ms,
    measure_stereo_width,
    violations,
)
from numpy.typing import NDArray

SR = 44100


# ----------------------------------------------------------------------
# Signal and spec builders
# ----------------------------------------------------------------------
def _sine(freq_hz: float, duration_ms: float = 500.0, sr: int = SR) -> NDArray[np.float64]:
    """A mono sine at full scale."""
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    return np.sin(2.0 * np.pi * freq_hz * t)


def _ramped_sine(
    freq_hz: float,
    duration_ms: float,
    measured_attack_ms: float,
    sr: int = SR,
) -> NDArray[np.float64]:
    """A sine with a linear amplitude ramp at the start.

    ``measured_attack_ms`` is what :func:`measure_attack_ms` should report: a
    linear ramp only reaches 10% of peak at one tenth of its length, so the
    ramp itself is drawn ten times longer than the requested attack.
    """
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    ramp_ms = measured_attack_ms * 10.0
    ramp = np.clip(t / (ramp_ms / 1000.0), 0.0, 1.0)
    return np.sin(2.0 * np.pi * freq_hz * t) * ramp


def _spec(**overrides: object) -> GenerationSpec:
    """A valid one-shot spec, ready to override."""
    payload: dict[str, object] = {
        "type": "one_shot",
        "category": "kick",
        "duration_ms": 500,
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
    payload.update(overrides)
    return GenerationSpec.model_validate(payload)


def _harmonic_tone(freq_hz: float, duration_ms: float = 500.0, sr: int = SR) -> NDArray[np.float64]:
    """A harmonically rich tone — closer to real model output than a bare sine.

    pYIN needs at least a second harmonic to anchor on: given a pure sine it
    will happily report a sub-octave, which would make these tests exercise the
    detector's failure mode rather than the pipeline.
    """
    n = round(duration_ms * sr / 1000.0)
    t = np.arange(n) / sr
    return (
        np.sin(2.0 * np.pi * freq_hz * t)
        + 0.5 * np.sin(4.0 * np.pi * freq_hz * t)
        + 0.25 * np.sin(6.0 * np.pi * freq_hz * t)
    )


def _band_db(audio: NDArray[np.float64], sr: int, low: float, high: float) -> float:
    """Absolute in-band energy in dB, so two signals can be compared directly."""
    mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    band = spectrum[(freqs >= low) & (freqs < high)]
    energy = float(np.sum(band**2))
    return 10.0 * float(np.log10(energy)) if energy > 0 else -200.0


# ----------------------------------------------------------------------
# Contract of the entry point
# ----------------------------------------------------------------------
def test_returns_same_shape_and_does_not_mutate_input() -> None:
    original = _sine(55.0)
    snapshot = original.copy()

    processed, _report = enforce_constraints(original, SR, _spec())

    assert processed.shape == original.shape
    assert original.shape == snapshot.shape
    np.testing.assert_array_equal(original, snapshot)
    assert processed is not original


def test_stereo_input_keeps_channel_count() -> None:
    stereo = np.stack([_sine(55.0), _sine(55.0) * 0.5], axis=1)
    processed, _ = enforce_constraints(stereo, SR, _spec(stereo_width=0.5))
    assert processed.shape == (stereo.shape[0], 2)


def test_report_entries_have_target_measured_met() -> None:
    _, report = enforce_constraints(_sine(55.0), SR, _spec())
    assert report, "expected a non-empty report"
    for name, measurement in report.items():
        assert set(measurement) == {"target", "measured", "met"}
        assert isinstance(measurement["met"], bool)
        assert isinstance(name, str)


def test_sample_rate_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not match"):
        enforce_constraints(_sine(55.0, duration_ms=20), 48000, _spec())


@pytest.mark.parametrize(
    "audio",
    [
        np.zeros(0),
        np.zeros((100, 3)),
        np.zeros((10, 10, 2)),
    ],
)
def test_invalid_audio_shapes_rejected(audio: NDArray[np.float64]) -> None:
    with pytest.raises(ValueError):
        enforce_constraints(audio, SR, _spec())


def test_is_deterministic() -> None:
    audio = _sine(55.0)
    first, first_report = enforce_constraints(audio, SR, _spec())
    second, second_report = enforce_constraints(audio, SR, _spec())
    np.testing.assert_allclose(first, second)
    assert first_report == second_report


# ----------------------------------------------------------------------
# 1 & 2. Spectral ceiling and floor
# ----------------------------------------------------------------------
def test_ceiling_removes_energy_above_cutoff() -> None:
    spec = _spec(spectral_ceiling_hz=2000.0, fundamental_hz=(1000.0, 1800.0))
    audio = _sine(15000.0)

    processed, report = enforce_constraints(audio, SR, spec)

    assert report["spectral_ceiling_hz"]["met"] is True
    assert report["spectral_ceiling_hz"]["measured"] < -30.0
    before = _band_db(audio, SR, 2000.0, SR / 2)
    after = _band_db(processed, SR, 2000.0, SR / 2)
    assert after < before - 40.0
    # The in-band content must survive.
    assert np.max(np.abs(processed)) > 0.0


def test_floor_removes_energy_below_cutoff() -> None:
    spec = _spec(spectral_floor_hz=500.0, fundamental_hz=(600.0, 900.0))
    audio = _harmonic_tone(40.0)

    processed, report = enforce_constraints(audio, SR, spec)

    assert report["spectral_floor_hz"]["met"] is True
    assert report["spectral_floor_hz"]["measured"] < -40.0
    before = _band_db(audio, SR, 0.0, 500.0)
    after = _band_db(processed, SR, 0.0, 500.0)
    assert after < before - 40.0


def test_zero_phase_filtering_keeps_transient_position() -> None:
    """Zero-phase filtering must not smear the onset."""
    spec = _spec(spectral_ceiling_hz=5000.0, spectral_floor_hz=20.0, attack_ms=5.0)
    audio = _ramped_sine(55.0, 400.0, 5.0)
    before = measure_attack_ms(audio[:, np.newaxis], SR, reference_ms=5.0)

    processed, _ = enforce_constraints(audio, SR, spec)
    after = measure_attack_ms(processed[:, np.newaxis], SR, reference_ms=5.0)

    assert before == pytest.approx(5.0, abs=0.5)
    assert after == pytest.approx(before, abs=0.5)


# ----------------------------------------------------------------------
# 3. Fundamental enforcement
# ----------------------------------------------------------------------
def test_out_of_range_fundamental_is_pitched_into_range() -> None:
    spec = _spec(fundamental_hz=(40.0, 90.0))
    audio = _harmonic_tone(150.0)

    _, report = enforce_constraints(audio, SR, spec)

    measured = report["fundamental_hz"]["measured"]
    assert report["fundamental_hz"]["met"] is True
    assert measured is not None
    assert 35.0 <= measured <= 95.0


def test_in_range_fundamental_is_left_alone() -> None:
    spec = _spec(fundamental_hz=(40.0, 90.0))
    audio = _harmonic_tone(55.0)

    _, report = enforce_constraints(audio, SR, spec)

    assert report["fundamental_hz"]["met"] is True
    assert report["fundamental_hz"]["measured"] == pytest.approx(55.0, abs=3.0)


def test_fundamental_far_outside_search_band_is_flagged() -> None:
    """A pitch the detector cannot even see is a miss, not a silent pass."""
    spec = _spec(fundamental_hz=(40.0, 90.0))
    audio = _harmonic_tone(1500.0)

    _, report = enforce_constraints(audio, SR, spec)

    assert report["fundamental_hz"]["met"] is False
    assert "fundamental_hz" in violations(report)


def test_undetectable_fundamental_is_flagged_as_violation() -> None:
    """Unvoiced noise has no fundamental: measured None, met False."""
    spec = _spec(fundamental_hz=(40.0, 90.0))
    rng = np.random.default_rng(20240517)
    noise = rng.normal(0.0, 0.5, size=SR // 2)

    _, report = enforce_constraints(noise, SR, spec)

    result = report["fundamental_hz"]
    assert result["measured"] is None
    assert result["met"] is False
    assert "fundamental_hz" in violations(report)


def test_silence_is_flagged_rather_than_normalised() -> None:
    _, report = enforce_constraints(np.zeros(SR // 4), SR, _spec())
    assert report["peak_db"]["measured"] is None
    assert report["peak_db"]["met"] is False


# ----------------------------------------------------------------------
# 4. Peak normalisation
# ----------------------------------------------------------------------
@pytest.mark.parametrize("target_db", [-1.0, -6.0, -12.0, -24.0])
def test_peak_normalised_to_target(target_db: float) -> None:
    spec = _spec(peak_db=target_db)
    audio = _sine(55.0) * 0.05

    processed, report = enforce_constraints(audio, SR, spec)

    expected_linear = 10.0 ** (target_db / 20.0)
    assert float(np.max(np.abs(processed))) == pytest.approx(expected_linear, rel=1e-6)
    assert report["peak_db"]["met"] is True
    assert report["peak_db"]["measured"] == pytest.approx(target_db, abs=1e-6)


def test_peak_normalisation_is_the_final_stage() -> None:
    """Filtering after normalisation would break the peak target."""
    spec = _spec(peak_db=-9.0, spectral_ceiling_hz=8000.0)
    processed, report = enforce_constraints(_ramped_sine(55.0, 500.0, 2.0), SR, spec)
    assert float(np.max(np.abs(processed))) == pytest.approx(10.0 ** (-9.0 / 20.0), rel=1e-6)
    assert report["peak_db"]["measured"] == pytest.approx(-9.0, abs=1e-6)


# ----------------------------------------------------------------------
# 5. Temporal envelope
# ----------------------------------------------------------------------
def test_slow_attack_is_shortened() -> None:
    spec = _spec(attack_ms=1.0)
    audio = _ramped_sine(55.0, 500.0, measured_attack_ms=20.0)
    before = measure_attack_ms(audio[:, np.newaxis], SR, reference_ms=20.0)
    # A median-filtered envelope of a rising *tone* reads a shade late; the
    # tolerance covers that quantisation, not real drift.
    assert before == pytest.approx(20.0, abs=2.0)

    processed, report = enforce_constraints(audio, SR, spec)

    measured = report["attack_ms"]["measured"]
    assert measured is not None
    assert measured < before / 2.0
    assert report["attack_ms"]["met"] is True
    # Length is preserved by the time warp.
    assert processed.shape == audio.shape


def test_fast_attack_is_lengthened_when_within_stretch_cap() -> None:
    spec = _spec(attack_ms=10.0)
    audio = _ramped_sine(55.0, 500.0, measured_attack_ms=4.0)

    _, report = enforce_constraints(audio, SR, spec)

    measured = report["attack_ms"]["measured"]
    assert measured is not None
    assert measured > 4.0
    assert report["attack_ms"]["met"] is True


def test_extreme_attack_stretch_falls_back_to_fade_and_reports_miss() -> None:
    """A click cannot become a 200 ms attack; we de-click and admit it."""
    spec = _spec(attack_ms=200.0)
    audio = _sine(55.0, duration_ms=500)

    processed, report = enforce_constraints(audio, SR, spec)

    assert abs(float(processed[0])) < 1e-9, "expected a de-click fade at sample 0"
    assert report["attack_ms"]["met"] is False
    assert report["attack_ms"]["measured"] is not None


def test_in_tolerance_attack_is_not_modified() -> None:
    spec = _spec(attack_ms=5.0)
    audio = _ramped_sine(55.0, 500.0, measured_attack_ms=6.0)
    snapshot = audio.copy()
    enforce_constraints(audio, SR, spec)
    np.testing.assert_array_equal(audio, snapshot)


@pytest.mark.parametrize(
    ("sample_type", "curve_is_smooth"),
    [("one_shot", True), ("loop", True), ("texture", True)],
)
def test_release_fade_lands_on_target(sample_type: str, curve_is_smooth: bool) -> None:
    if sample_type == "loop":
        spec = _spec(
            type="loop",
            category="hihat",
            duration_ms=None,
            duration_beats=2.0,
            bpm=140.0,
            release_ms=80.0,
            attack_ms=1.0,
            fundamental_hz=(600.0, 900.0),
            spectral_floor_hz=200.0,
        )
        # Inside the requested band, so no pitch correction is needed.
        audio = _ramped_sine(700.0, spec.effective_duration_ms, measured_attack_ms=1.0)
    else:
        spec = _spec(type=sample_type, release_ms=80.0, attack_ms=1.0)
        audio = _ramped_sine(55.0, spec.effective_duration_ms, measured_attack_ms=1.0)
    assert measure_release_ms(
        audio[:, np.newaxis], SR, reference_ms=spec.release_ms
    ) == pytest.approx(0.0, abs=2.0)

    processed, report = enforce_constraints(audio, SR, spec)

    measured = report["release_ms"]["measured"]
    assert measured is not None
    assert measured == pytest.approx(80.0, abs=8.0)
    assert report["release_ms"]["met"] is True
    assert curve_is_smooth
    # The fade must reach true silence, not merely a low level.
    assert abs(float(np.max(np.abs(processed[-1])))) < 1e-9


def test_release_fade_decays_across_its_window() -> None:
    """The faded span must fall, not just end in zero."""
    spec = _spec(release_ms=100.0, attack_ms=1.0)
    audio = _ramped_sine(55.0, 500.0, measured_attack_ms=1.0)
    processed, _ = enforce_constraints(audio, SR, spec)

    fade = round(0.1 * SR)
    tail = np.abs(processed[-fade:])
    head_level = float(np.max(tail[: fade // 4]))
    tail_level = float(np.max(tail[-fade // 4 :]))
    # A linear fade spans unity down to zero across the window, so the last
    # quarter can hold at most a quarter of the head level.
    assert head_level > 3.0 * tail_level


# ----------------------------------------------------------------------
# 6. Stereo width
# ----------------------------------------------------------------------
def _stereo(side_ratio: float, duration_ms: float = 300.0) -> NDArray[np.float64]:
    """Stereo pair with a known side/mid RMS ratio."""
    n = round(duration_ms * SR / 1000.0)
    t = np.arange(n) / SR
    mid = np.sin(2.0 * np.pi * 55.0 * t)
    side = side_ratio * np.sin(2.0 * np.pi * 110.0 * t)
    return np.stack([mid + side, mid - side], axis=1)


@pytest.mark.parametrize("target", [0.0, 0.25, 0.75, 1.5])
def test_stereo_width_hit_by_ms_processing(target: float) -> None:
    spec = _spec(stereo_width=target, channels=2)
    audio = _stereo(0.5)

    processed, report = enforce_constraints(audio, SR, spec)

    measured = report["stereo_width"]["measured"]
    assert measured is not None
    assert measured == pytest.approx(target, abs=0.05)
    assert report["stereo_width"]["met"] is True
    # Rescaling must not disturb the signal's level or length.
    assert processed.shape == audio.shape
    assert np.max(np.abs(processed)) > 0.0


def test_zero_width_collapses_to_mono() -> None:
    spec = _spec(stereo_width=0.0, channels=2)
    processed, _ = enforce_constraints(_stereo(0.5), SR, spec)
    mono = np.mean(processed, axis=1)
    assert np.allclose(processed[:, 0], mono)
    assert np.allclose(processed[:, 1], mono)


def test_mid_channel_is_preserved_by_width_adjustment() -> None:
    """M/S scaling must not alter the mono sum."""
    spec = _spec(stereo_width=0.3, channels=2)
    audio = _stereo(0.9)
    processed, _ = enforce_constraints(audio, SR, spec)
    # Compare mid before the width stage against the first channel of a
    # width-neutral spec, which leaves the image alone.
    neutral, _ = enforce_constraints(audio, SR, _spec(channels=2))
    assert measure_stereo_width(neutral) == pytest.approx(0.9, abs=0.2)
    assert measure_stereo_width(processed) == pytest.approx(0.3, abs=0.05)


def test_stereo_width_absent_when_not_requested() -> None:
    _, report = enforce_constraints(_stereo(0.5), SR, _spec(channels=2))
    assert "stereo_width" not in report


def test_stereo_width_ignored_for_mono_render() -> None:
    """A constraint that cannot apply is absent, not reported as unmet.

    enforce_constraints documents that inapplicable constraints are left out of
    the report so callers can tell "not evaluated" from "failed". Emitting the
    key with met=False made every mono job that set stereo_width look like a
    constraint miss, which the worker then surfaces as
    complete_with_warnings.
    """
    _, report = enforce_constraints(_sine(55.0), SR, _spec(stereo_width=0.5))
    assert "stereo_width" not in report
    assert violations(report) == []
