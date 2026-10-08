"""Named constraint tests, written against the acceptance criteria.

Each test here states one constraint the way a user would state it: "put a
15 kHz tone under an 8 kHz ceiling", "normalise -3 dB input to -12 dB output",
"give me a 5 ms attack, +/-2 ms". The assertions are on *measured output*, not
on the report the pipeline produces about itself — a report that says "met" while
the audio disagrees would pass every other test in the suite and still ship a
broken library.

These complement ``test_constraint.py``, which covers the pipeline stage by
stage (ordering, idempotence, retry limits, boundary guards). This file is the
end-to-end view: one constraint, one signal, one verifiable claim.
"""

from __future__ import annotations

import numpy as np
import pytest
from app.models.schemas import GenerationSpec
from app.services.constraint import (
    detect_fundamental_hz,
    enforce_constraints,
    measure_attack_ms,
    measure_release_ms,
    measure_stereo_width,
    violations,
)

from conftest import (
    SR,
    band_db,
    band_fraction_db,
    harmonic_tone,
    peak_db,
    ramped_sine,
    sine,
    spec_payload,
)


def as_2d(audio: np.ndarray) -> np.ndarray:
    """Present mono audio as ``(n, 1)``, which the measurement helpers require.

    Args:
        audio: A 1-D or 2-D array.

    Returns:
        A 2-D array. Stereo input is returned unchanged.
    """
    return audio[:, np.newaxis] if audio.ndim == 1 else audio


def _spec(**overrides: object) -> GenerationSpec:
    """A valid spec, ready to override."""
    return GenerationSpec.model_validate(spec_payload(duration_ms=500, **overrides))


# ----------------------------------------------------------------------
# Spectral ceiling
# ----------------------------------------------------------------------
def test_spectral_ceiling_enforced() -> None:
    """15 kHz content under an 8 kHz ceiling must come out below -60 dB.

    The fixture signal carries an *in-range* fundamental alongside the out-of-band
    tone. That isolation matters: with a 15 kHz tone alone, the pipeline also
    tries to satisfy the fundamental constraint by pitch-shifting it, and the
    resulting shift dumps energy back above the ceiling. One constraint per test.
    """
    spec = _spec(spectral_ceiling_hz=8000.0, fundamental_hz=(1000.0, 3000.0))
    audio = sine(2000.0, duration_ms=500.0) + sine(15000.0, duration_ms=500.0, amplitude=0.5)

    # Precondition: the input really does have energy where the ceiling will cut.
    assert band_fraction_db(audio, SR, 8000.0, SR / 2) > -20.0, (
        "signal must start above the ceiling"
    )

    processed, report = enforce_constraints(audio, SR, spec)

    above = band_fraction_db(processed, SR, 8000.0, SR / 2)
    assert above < -60.0, f"expected < -60 dB above 8 kHz, measured {above:.1f} dB"
    assert report["spectral_ceiling_hz"]["met"] is True


def test_spectral_ceiling_preserves_in_band_content() -> None:
    """Filtering must not take the useful part of the signal with it."""
    spec = _spec(spectral_ceiling_hz=8000.0, fundamental_hz=(1000.0, 3000.0))
    audio = sine(2000.0, duration_ms=500.0) + sine(15000.0, duration_ms=500.0, amplitude=0.5)

    before = band_db(audio, SR, 1000.0, 3000.0)
    processed, _ = enforce_constraints(audio, SR, spec)
    # The pipeline also peak-normalises, so in-band level drops by the
    # normalisation amount. Comparing against the target peak isolates "the
    # filter threw away in-band content" from "everything got quieter".
    after = band_db(processed, SR, 1000.0, 3000.0)
    normalised_for = band_db(processed, SR, 1000.0, 3000.0) - peak_db(processed)

    assert after - (-12.0) > before - 3.0, "in-band energy must survive a ceiling"
    assert normalised_for == pytest.approx(before, abs=1.5)


def test_spectral_floor_enforced() -> None:
    """Sub-audio rumble must be removed by the floor.

    Threshold is the pipeline's own ``SPECTRAL_LEAK_TOLERANCE_DB`` (-30 dB), not
    the -60 dB the ceiling achieves. A 30 Hz high-pass over a 10 Hz tone only
    gets ~-42 dB here: reflection padding of a signal whose period is 4.4 k
    samples is not phase-continuous, and the resulting boundary transient puts
    broadband residue in the sub-floor band. -30 dB of total energy below 30 Hz
    is inaudible and harmless; -60 dB is not reachable without longer padding, so
    asserting it here would be asserting a change to the DSP, not a property of
    it.
    """
    # The floor has to sit below the fundamental band: GenerationSpec rejects a
    # floor at or above the fundamental minimum, since no signal could satisfy both.
    spec = _spec(spectral_floor_hz=30.0, fundamental_hz=(800.0, 1600.0))
    audio = sine(10.0, duration_ms=500.0) + sine(1000.0, duration_ms=500.0)

    processed, report = enforce_constraints(audio, SR, spec)

    below = band_fraction_db(processed, SR, 0.0, 30.0)
    assert below < -30.0, f"expected < -30 dB below 30 Hz, measured {below:.1f} dB"
    assert report["spectral_floor_hz"]["met"] is True


# ----------------------------------------------------------------------
# Peak normalisation
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("input_db", "target_db"),
    [(-3.0, -12.0), (0.0, -6.0), (-20.0, -12.0)],
)
def test_peak_normalization(input_db: float, target_db: float) -> None:
    """The output peak lands on the target, whatever came in."""
    spec = _spec(peak_db=target_db, fundamental_hz=(1000.0, 3000.0))
    amplitude = 10.0 ** (input_db / 20.0)
    audio = sine(2000.0, duration_ms=500.0, amplitude=amplitude)

    assert peak_db(audio) == pytest.approx(input_db, abs=0.1), "input level must be as intended"

    processed, report = enforce_constraints(audio, SR, spec)

    assert peak_db(processed) == pytest.approx(target_db, abs=0.3)
    assert report["peak_db"]["met"] is True


def test_peak_normalization_never_clips() -> None:
    """A target above 0 dBFS would produce a clipped, unusable file."""
    spec = _spec(peak_db=-0.1, fundamental_hz=(1000.0, 3000.0))
    audio = sine(2000.0, duration_ms=500.0, amplitude=0.9)

    processed, _ = enforce_constraints(audio, SR, spec)

    assert float(np.max(np.abs(processed))) <= 1.0


def test_peak_normalization_is_applied_after_filtering() -> None:
    """Order matters: normalising first, then filtering, would lose level.

    Filtering removes energy, so if peak normalisation ran before the ceiling the
    final peak would sit below the target. Asserting the *final* peak is the only
    way to catch a pipeline that normalised at the wrong point.
    """
    spec = _spec(peak_db=-6.0, spectral_ceiling_hz=8000.0, fundamental_hz=(2000.0, 4000.0))
    # Loud in-band plus loud out-of-band: filtering the out-of-band part costs
    # real level, which the final peak normalisation has to put back.
    audio = sine(4000.0, duration_ms=500.0, amplitude=0.7) + sine(16000.0, duration_ms=500.0)

    processed, _ = enforce_constraints(audio, SR, spec)

    assert peak_db(processed) == pytest.approx(-6.0, abs=0.3)


# ----------------------------------------------------------------------
# Attack envelope
# ----------------------------------------------------------------------
def test_attack_envelope() -> None:
    """A requested 5 ms attack is measured at 5 ms, within 2 ms."""
    spec = _spec(attack_ms=5.0, fundamental_hz=(100.0, 200.0))
    # Start with a 40 ms attack and require it to be shortened to 5 ms.
    audio = ramped_sine(150.0, duration_ms=500.0, measured_attack_ms=40.0)

    processed, report = enforce_constraints(audio, SR, spec)

    measured = measure_attack_ms(as_2d(processed), SR, reference_ms=5.0)
    assert measured == pytest.approx(5.0, abs=2.0), f"measured attack {measured:.2f} ms"
    assert report["attack_ms"]["met"] is True


def test_attack_envelope_reports_a_miss_it_cannot_fix() -> None:
    """A 200 ms attack on a 500 ms sample cannot be stretched into existence.

    The stretch is capped; past that the pipeline de-clicks the transient and
    admits the miss rather than quietly delivering something else.
    """
    spec = _spec(attack_ms=200.0, fundamental_hz=(100.0, 200.0))
    audio = sine(150.0, duration_ms=500.0)

    processed, report = enforce_constraints(audio, SR, spec)

    assert report["attack_ms"]["met"] is False, "an impossible target must be flagged"
    assert report["attack_ms"]["measured"] is not None
    assert float(np.max(np.abs(processed))) > 0.0, "audio is still delivered"


def test_release_envelope_fades_to_silence() -> None:
    """The tail must actually decay, not merely be labelled as decayed."""
    spec = _spec(release_ms=50.0, fundamental_hz=(100.0, 200.0))
    audio = ramped_sine(150.0, duration_ms=500.0, measured_attack_ms=1.0)

    processed, report = enforce_constraints(audio, SR, spec)

    assert measure_release_ms(as_2d(processed), SR) > 0.0
    assert report["release_ms"]["met"] is True
    # The fade lands on near-silence rather than merely trending downward: the
    # contract is FADE_DEPTH_RATIO (0.25) between the first and last tenth, and
    # an exponential fade clears the last sample entirely.
    final = float(np.max(np.abs(processed[-1:])))
    assert final < 0.02 * float(np.max(np.abs(processed))), f"tail ends at {final:.4f}"
    tail = processed[-int(0.01 * SR) :]
    body = processed[int(0.2 * SR) : int(0.3 * SR)]
    assert float(np.sqrt(np.mean(tail**2))) < float(np.sqrt(np.mean(body**2)))


# ----------------------------------------------------------------------
# Fundamental shift
# ----------------------------------------------------------------------
def test_fundamental_shift() -> None:
    """An 80 Hz input with a [40, 60] target comes out inside the band.

    Detection uses pYIN, which wants a second harmonic, hence the rich tone. The
    band edges are checked with the spec's declared tolerance rather than
    exactly: pitch-shifting cannot land on a boundary sample-exactly, and the
    API advertises a tolerance precisely because of that.
    """
    spec = _spec(fundamental_hz=(40.0, 60.0))
    audio = harmonic_tone(80.0, duration_ms=500.0)

    assert measure_fundamental(audio) > 60.0, "input must start above the target band"

    processed, report = enforce_constraints(audio, SR, spec)

    measured = measure_fundamental(processed, spec)
    tolerance = spec.tolerances.fundamental_hz
    assert 40.0 - tolerance <= measured <= 60.0 + tolerance, (
        f"expected 40-60 Hz (+/-{tolerance}), measured {measured:.1f} Hz"
    )
    assert report["fundamental_hz"]["met"] is True


def test_fundamental_shift_down_by_a_ratio() -> None:
    """Halving a 100 Hz tone should land near 50 Hz, not merely "somewhere in range"."""
    spec = _spec(fundamental_hz=(45.0, 55.0))
    audio = harmonic_tone(100.0, duration_ms=500.0)

    processed, _ = enforce_constraints(audio, SR, spec)

    measured = measure_fundamental(processed, spec)
    assert measured == pytest.approx(50.0, rel=0.25), f"expected near 50 Hz, got {measured:.1f} Hz"


def test_fundamental_untouched_when_already_in_range() -> None:
    """A 500 Hz tone inside [400, 600] must not be moved to satisfy a constraint it meets."""
    spec = _spec(fundamental_hz=(400.0, 600.0))
    audio = harmonic_tone(500.0, duration_ms=500.0)

    processed, report = enforce_constraints(audio, SR, spec)

    assert measure_fundamental(processed, spec) == pytest.approx(500.0, rel=0.1)
    assert report["fundamental_hz"]["met"] is True


def measure_fundamental(audio: np.ndarray, spec: GenerationSpec | None = None) -> float:
    """Detect the fundamental with the pipeline's own detector.

    Args:
        audio: Mono or stereo audio.
        spec: The spec whose search band to use. Defaults to a wide band, which is
            what you want for establishing where a signal *starts* — searching the
            target band against an out-of-range input invites pYIN to report a
            neighbouring partial instead.

    Returns:
        The detected fundamental in Hz.

    Raises:
        AssertionError: If the detector finds nothing, which would make any
            "is it in range" assertion vacuously false.
    """
    low, high = (spec or _spec(fundamental_hz=(30.0, 400.0))).fundamental_hz
    detected = detect_fundamental_hz(as_2d(audio), SR, low, high)
    assert detected is not None, "pYIN found no fundamental; the test signal is wrong"
    return float(detected)


# ----------------------------------------------------------------------
# Stereo width
# ----------------------------------------------------------------------
def _mid_side_stereo(mid_gain: float = 1.0, side_gain: float = 0.2) -> np.ndarray:
    """Stereo audio built in M/S, with a non-zero mid channel.

    An inverted pair (``[mono, -mono]``) is the obvious way to make a "wide"
    signal, but its mid channel is identically zero, and a side/mid ratio is
    undefined against a zero mid. The M/S stage correctly refuses to touch such
    a signal, which makes it useless as a test fixture.
    """
    mid = sine(150.0, duration_ms=500.0) * mid_gain
    side = sine(150.0, duration_ms=500.0) * side_gain
    return np.stack([mid + side, mid - side], axis=1)


def test_stereo_width_constraint() -> None:
    """A wide target widens a narrow image; the measurement follows."""
    spec = _spec(stereo_width=1.0, fundamental_hz=(100.0, 200.0))
    audio = _mid_side_stereo(mid_gain=1.0, side_gain=0.2)

    before = measure_stereo_width(audio)
    assert before is not None and before < 0.5, "fixture must start narrower than the target"

    processed, report = enforce_constraints(audio, SR, spec)

    assert processed.ndim == 2 and processed.shape[1] == 2, "stereo in, stereo out"
    measured = measure_stereo_width(processed)
    assert measured == pytest.approx(1.0, abs=0.1), f"measured width {measured}"
    assert report["stereo_width"]["met"] is True


def test_stereo_width_zero_collapses_to_mono_image() -> None:
    """stereo_width=0 means the side signal goes to zero, not "unchanged".

    The mid channel survives; what is removed is the difference between the two
    channels. Asserting on ``L - R`` rather than on the raw channels keeps this
    from passing just because both channels happen to be quiet.
    """
    spec = _spec(stereo_width=0.0, fundamental_hz=(100.0, 200.0))
    audio = _mid_side_stereo(mid_gain=1.0, side_gain=0.2)

    processed, _ = enforce_constraints(audio, SR, spec)

    assert float(np.max(np.abs(processed[:, 0] - processed[:, 1]))) < 1e-6
    assert float(np.max(np.abs(processed))) > 0.1, "the mid channel must survive"


def test_stereo_width_is_skipped_for_a_mono_render() -> None:
    """Asking for width on a mono signal is a no-op, not a miss.

    An inapplicable constraint is absent from the report rather than reported as
    unmet, so a mono job that sets stereo_width is not flagged
    complete_with_warnings for a constraint nobody could measure.
    """
    spec = _spec(stereo_width=0.5, fundamental_hz=(100.0, 200.0))

    processed, report = enforce_constraints(sine(150.0, duration_ms=500.0), SR, spec)

    assert processed.ndim == 1, "mono in, mono out"
    assert "stereo_width" not in report, "an inapplicable constraint must not appear as a miss"


# ----------------------------------------------------------------------
# Whole pipeline
# ----------------------------------------------------------------------
def test_full_pipeline() -> None:
    """Every constraint at once, each verified in the output and in the report.

    The fixture carries a slow-ish 5 ms attack, out-of-band 15 kHz content, and a
    peak 12 dB hot, and the spec asks for an 8 kHz ceiling, a 30 Hz floor, a
    40-60 Hz fundamental, a 5 ms attack, a 50 ms release, and -12 dBFS.

    The out-of-band tone is *also* ramped and kept at 0.3 of the body. That is not
    cosmetic: the attack is measured on the mono sum's envelope, so a
    full-amplitude 15 kHz sine — which reaches its peak in 16 microseconds —
    would report a 0 ms attack, make the constraint genuinely unsatisfiable, and
    quietly turn this into a test of the wrong thing.
    """
    spec = _spec(
        spectral_ceiling_hz=8000.0,
        spectral_floor_hz=30.0,
        fundamental_hz=(40.0, 60.0),
        attack_ms=5.0,
        release_ms=50.0,
        peak_db=-12.0,
    )
    audio = ramped_sine(50.0, duration_ms=500.0, measured_attack_ms=5.0) + (
        ramped_sine(15000.0, duration_ms=500.0, measured_attack_ms=5.0) * 0.3
    )
    audio = audio / float(np.max(np.abs(audio))) * 0.9

    processed, report = enforce_constraints(audio, SR, spec)

    # --- each constraint, measured rather than trusted ---------------------
    assert band_fraction_db(processed, SR, 8000.0, SR / 2) < -60.0, "ceiling not enforced"
    assert band_fraction_db(processed, SR, 0.0, 30.0) < -30.0, "floor not enforced"
    tolerance = spec.tolerances.fundamental_hz
    measured_fundamental = measure_fundamental(processed, spec)
    assert 40.0 - tolerance <= measured_fundamental <= 60.0 + tolerance, "fundamental not shifted"
    assert measure_attack_ms(as_2d(processed), SR, reference_ms=5.0) == pytest.approx(
        5.0, abs=2.0
    ), "attack not shaped"
    assert peak_db(processed) == pytest.approx(-12.0, abs=0.3), "peak not normalised"

    # --- and the report agrees with the measurements -----------------------
    for name in (
        "spectral_ceiling_hz",
        "spectral_floor_hz",
        "fundamental_hz",
        "attack_ms",
        "release_ms",
        "peak_db",
    ):
        assert report[name]["met"] is True, (
            f"{name} reported as unmet but measures clean: {report[name]}"
        )
        assert "target" in report[name]
        assert "measured" in report[name]

    assert processed.shape == audio.shape
    assert float(np.max(np.abs(processed))) > 0.0, "audio must survive the pipeline"


def test_full_pipeline_reports_what_it_could_not_fix() -> None:
    """A constraint the pipeline cannot satisfy is named, not quietly dropped.

    Here the attack is genuinely unsatisfiable: a phase-vocoder pitch shift puts
    a click at the onset, and the subsequent filters ring. The contract is not
    "everything always passes" — it is that delivered audio is never silently
    claimed to satisfy something it does not.
    """
    spec = _spec(
        spectral_ceiling_hz=8000.0,
        spectral_floor_hz=30.0,
        fundamental_hz=(40.0, 60.0),
        attack_ms=5.0,
        peak_db=-12.0,
    )
    audio = harmonic_tone(80.0, duration_ms=500.0) + sine(15000.0, duration_ms=500.0, amplitude=0.5)
    audio = audio / float(np.max(np.abs(audio))) * 0.9

    processed, report = enforce_constraints(audio, SR, spec)

    failed = violations(report)
    assert failed, "a pitch-shifted signal should miss at least the attack"
    assert set(failed) == {name for name, m in report.items() if m["met"] is False}
    for name in failed:
        assert report[name]["measured"] is not None, f"{name} failed but was not measured"
    # The constraints that were satisfiable still are: a miss on one does not
    # abandon the rest.
    assert report["peak_db"]["met"] is True
    assert peak_db(processed) == pytest.approx(-12.0, abs=0.3)
    assert float(np.max(np.abs(processed))) > 0.0, "audio is still delivered"


def test_full_pipeline_is_deterministic() -> None:
    """Same input, same output: a sample library has to be reproducible."""
    spec = _spec(spectral_ceiling_hz=8000.0, fundamental_hz=(40.0, 60.0), attack_ms=5.0)
    audio = harmonic_tone(80.0, duration_ms=500.0)

    first, _ = enforce_constraints(audio.copy(), SR, spec)
    second, _ = enforce_constraints(audio.copy(), SR, spec)

    np.testing.assert_array_equal(first, second)
