"""Tests for the generation spec schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.models.schemas import (
    GeneratedFile,
    GenerationResponse,
    GenerationSpec,
    SpectralAnalysis,
    Tolerances,
)
from pydantic import ValidationError

VALID_ONESHOT: dict[str, object] = {
    "type": "one_shot",
    "category": "kick",
    "duration_ms": 800,
    "fundamental_hz": (40.0, 90.0),
    "spectral_ceiling_hz": 12000.0,
    "spectral_floor_hz": 25.0,
    "peak_db": -12.0,
    "attack_ms": 1.0,
    "decay_ms": 400.0,
    "sustain_level": 0.0,
    "release_ms": 50.0,
    "bpm": 140.0,
    "key": "F#m",
    "genre": "techno",
}

VALID_LOOP: dict[str, object] = {
    "type": "loop",
    "category": "hihat",
    "duration_beats": 2.0,
    "fundamental_hz": (600.0, 900.0),
    "spectral_ceiling_hz": 16000.0,
    "spectral_floor_hz": 200.0,
    "peak_db": -6.0,
    "attack_ms": 0.5,
    "decay_ms": 20.0,
    "sustain_level": 0.3,
    "release_ms": 10.0,
    "bpm": 128.0,
    "key": "C major",
    "genre": "house",
}


def _spec(**overrides: object) -> GenerationSpec:
    """Build a spec from :data:`VALID_ONESHOT` with field overrides applied."""
    payload = {**VALID_ONESHOT, **overrides}
    return GenerationSpec.model_validate(payload)


# ----------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------
def test_valid_one_shot_defaults_applied() -> None:
    spec = _spec()
    assert spec.sample_rate == 44100
    assert spec.bit_depth == 24
    assert spec.channels == 2
    assert spec.batch_size == 1
    assert spec.diversity == 0.5
    assert spec.format == "wav"
    assert spec.metadata_embed is True
    assert spec.spectral_tilt_db_per_octave == 0.0
    assert spec.mood is None
    assert spec.reference_sample_url is None


def test_valid_loop_derives_duration_ms() -> None:
    spec = GenerationSpec.model_validate(VALID_LOOP)
    # 2 beats at 128 BPM = 937.5 ms
    assert spec.effective_duration_ms == 938
    assert spec.total_frames == round(938 * 44100 / 1000)


def test_full_spec_round_trips_through_model_dump() -> None:
    spec = _spec(
        mood="dark",
        reference_sample_url="https://cdn.example.com/ref.wav",
        batch_size=4,
        diversity=0.0,
        format="flac",
        metadata_embed=False,
        spectral_tilt_db_per_octave=-3.0,
    )
    again = GenerationSpec.model_validate(spec.model_dump(mode="json"))
    assert again == spec


# ----------------------------------------------------------------------
# from_json / to_json (recipe support)
# ----------------------------------------------------------------------
def test_from_json_loads_recipe(tmp_path: Path) -> None:
    recipe = tmp_path / "kick.json"
    recipe.write_text(json.dumps({**VALID_ONESHOT, "fundamental_hz": [40.0, 90.0]}))

    spec = GenerationSpec.from_json(recipe)
    assert spec.category == "kick"
    assert spec.fundamental_hz == (40.0, 90.0)


def test_from_json_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        GenerationSpec.from_json("does/not/exist.json")


def test_from_json_invalid_json_raises(tmp_path: Path) -> None:
    recipe = tmp_path / "broken.json"
    recipe.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        GenerationSpec.from_json(recipe)


def test_from_json_enforces_validation(tmp_path: Path) -> None:
    recipe = tmp_path / "invalid.json"
    recipe.write_text(json.dumps({**VALID_ONESHOT, "fundamental_hz": [90.0, 40.0]}))
    with pytest.raises(ValidationError):
        GenerationSpec.from_json(recipe)


def test_to_json_round_trip(tmp_path: Path) -> None:
    spec = _spec()
    out = spec.to_json(tmp_path / "out.json")
    assert GenerationSpec.from_json(out) == spec


# ----------------------------------------------------------------------
# Validation failures
# ----------------------------------------------------------------------
def test_fundamental_min_must_be_below_max() -> None:
    with pytest.raises(ValidationError, match="ascending"):
        _spec(fundamental_hz=(90.0, 40.0))


def test_fundamental_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _spec(fundamental_hz=(0.0, 90.0))


def test_spectral_floor_above_fundamental_is_rejected() -> None:
    with pytest.raises(ValidationError, match="spectral_floor_hz"):
        _spec(fundamental_hz=(40.0, 90.0), spectral_floor_hz=50.0)


def test_spectral_ceiling_below_fundamental_is_rejected() -> None:
    with pytest.raises(ValidationError, match="spectral_ceiling_hz"):
        _spec(fundamental_hz=(40.0, 90.0), spectral_ceiling_hz=60.0)


def test_envelope_must_fit_inside_duration() -> None:
    with pytest.raises(ValidationError, match="envelope does not fit"):
        _spec(attack_ms=300.0, decay_ms=400.0, release_ms=200.0, duration_ms=800)


def test_loop_requires_duration_beats() -> None:
    payload = {**VALID_LOOP}
    payload.pop("duration_beats")
    with pytest.raises(ValidationError, match="duration_beats is required"):
        GenerationSpec.model_validate(payload)


def test_loop_envelope_checked_against_derived_duration() -> None:
    # 2 beats at 128 BPM ~= 938 ms, so a 950 ms attack alone overflows it.
    with pytest.raises(ValidationError, match="envelope does not fit"):
        GenerationSpec.model_validate({**VALID_LOOP, "attack_ms": 950.0})


def test_one_shot_requires_duration_ms() -> None:
    payload = {**VALID_ONESHOT}
    payload.pop("duration_ms")
    with pytest.raises(ValidationError, match="duration_ms is required"):
        GenerationSpec.model_validate(payload)


def test_sustain_level_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _spec(sustain_level=1.5)


def test_peak_db_cannot_exceed_zero() -> None:
    with pytest.raises(ValidationError):
        _spec(peak_db=0.5)


def test_diversity_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _spec(diversity=1.2)


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _spec(batch_size=0)


def test_negative_temporal_values_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(attack_ms=-1.0)


def test_invalid_type_literal_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(type="bass")


def test_unsupported_sample_rate_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported sample_rate"):
        _spec(sample_rate=22050)


def test_unsupported_bit_depth_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported bit_depth"):
        _spec(bit_depth=12)


def test_invalid_channel_count_rejected() -> None:
    with pytest.raises(ValidationError, match="channels must be"):
        _spec(channels=6)


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(reverb_amount=0.4)


# ----------------------------------------------------------------------
# Response models
# ----------------------------------------------------------------------
def test_generation_response_holds_files_and_constraint_map() -> None:
    analysis = SpectralAnalysis(
        fundamental_detected_hz=55.0,
        ceiling_violation_db=-42.5,
        attack_measured_ms=1.4,
        floor_slope_db_per_oct=-24.0,
        tilt_measured_db_per_octave=-3.0,
    )
    file = GeneratedFile(
        url="https://cdn.example.com/out/kick_0.wav",
        duration_ms=800,
        peak_db=-12.1,
        spectral_analysis=analysis,
    )
    response = GenerationResponse(
        job_id="job_123",
        status="complete",
        files=[file],
        constraints_met={"fundamental_hz": True, "spectral_ceiling_hz": True},
    )

    assert response.job_id == "job_123"
    assert response.status == "complete"
    assert response.files[0].spectral_analysis.fundamental_detected_hz == 55.0
    assert response.constraints_met["fundamental_hz"] is True
    assert response.model_dump(mode="json")["files"][0]["duration_ms"] == 800


def test_generation_response_defaults_are_empty() -> None:
    response = GenerationResponse(job_id="job_456", status="queued")
    assert response.files == []
    assert response.constraints_met == {}


def test_complete_with_warnings_is_a_valid_status() -> None:
    response = GenerationResponse(job_id="job_789", status="complete_with_warnings")
    assert response.status == "complete_with_warnings"


def test_invalid_job_status_rejected() -> None:
    with pytest.raises(ValidationError):
        GenerationResponse(job_id="job_789", status="maybe")


# ----------------------------------------------------------------------
# Tolerances
# ----------------------------------------------------------------------
def test_tolerances_defaults() -> None:
    tol = Tolerances()
    assert tol.fundamental_hz == 5.0
    assert tol.ceiling_violation_db == -40.0
    assert tol.peak_db == 0.5
    assert tol.attack_ms == 2.0
    assert tol.duration_pct == 0.02


def test_spec_gets_default_tolerances() -> None:
    assert _spec().tolerances == Tolerances()


def test_spec_tolerances_overridable() -> None:
    spec = _spec(tolerances={"peak_db": 0.1, "duration_pct": 0.0})
    assert spec.tolerances.peak_db == 0.1
    assert spec.tolerances.duration_pct == 0.0


def test_negative_tolerance_rejected() -> None:
    with pytest.raises(ValidationError):
        Tolerances(attack_ms=-1.0)


def test_positive_ceiling_violation_rejected() -> None:
    with pytest.raises(ValidationError):
        Tolerances(ceiling_violation_db=1.0)


def test_positive_floor_slope_rejected() -> None:
    with pytest.raises(ValidationError):
        Tolerances(floor_slope_db_per_oct=3.0)


def test_negative_tilt_tolerance_rejected() -> None:
    with pytest.raises(ValidationError):
        Tolerances(tilt_db_per_octave=-0.5)


def test_spectral_analysis_rejects_positive_floor_slope() -> None:
    with pytest.raises(ValidationError):
        SpectralAnalysis(
            fundamental_detected_hz=55.0,
            ceiling_violation_db=-55.0,
            attack_measured_ms=1.0,
            floor_slope_db_per_oct=2.0,  # energy rising as frequency drops
            tilt_measured_db_per_octave=0.0,
        )


def test_tolerances_round_trip_in_recipe(tmp_path: Path) -> None:
    recipe = tmp_path / "loose.json"
    recipe.write_text(json.dumps({**VALID_ONESHOT, "tolerances": {"fundamental_hz": 12.0}}))
    assert GenerationSpec.from_json(recipe).tolerances.fundamental_hz == 12.0


# ----------------------------------------------------------------------
# Constraint evaluation
# ----------------------------------------------------------------------
def _generated(**overrides: object) -> GeneratedFile:
    """Build a rendered variant that satisfies :data:`VALID_ONESHOT` exactly."""
    payload: dict[str, object] = {
        "url": "https://cdn.example.com/out/kick_0.wav",
        "duration_ms": 800,
        "peak_db": -12.0,
        "spectral_analysis": {
            "fundamental_detected_hz": 55.0,
            "ceiling_violation_db": -55.0,
            "attack_measured_ms": 1.0,
            "floor_slope_db_per_oct": -24.0,
            "tilt_measured_db_per_octave": 0.0,
        },
    }
    analysis_overrides = overrides.pop("spectral_analysis", None)
    payload.update(overrides)
    if analysis_overrides:
        payload["spectral_analysis"] = {
            **payload["spectral_analysis"],  # type: ignore[dict-item]
            **analysis_overrides,  # type: ignore[arg-type]
        }
    return GeneratedFile.model_validate(payload)


def test_evaluate_constraints_passes_exact_match() -> None:
    result = _spec().evaluate_constraints(_generated())
    assert result == {
        "duration_ms": True,
        "peak_db": True,
        "fundamental_hz": True,
        "spectral_ceiling_hz": True,
        "spectral_floor_hz": True,
        "spectral_tilt_db_per_octave": True,
        "attack_ms": True,
    }


def test_evaluate_constraints_tolerates_measurement_drift() -> None:
    generated = _generated(
        peak_db=-12.4,
        duration_ms=805,
        spectral_analysis={
            "fundamental_detected_hz": 92.0,  # inside 40+5 .. 90+5
            "ceiling_violation_db": -41.0,
            "attack_measured_ms": 2.8,
        },
    )
    assert all(_spec().evaluate_constraints(generated).values())


def test_evaluate_constraints_detects_pitch_violation() -> None:
    generated = _generated(spectral_analysis={"fundamental_detected_hz": 120.0})
    result = _spec().evaluate_constraints(generated)
    assert result["fundamental_hz"] is False
    assert result["spectral_ceiling_hz"] is True


def test_evaluate_constraints_detects_leak_above_ceiling() -> None:
    generated = _generated(spectral_analysis={"ceiling_violation_db": -12.0})
    assert _spec().evaluate_constraints(generated)["spectral_ceiling_hz"] is False


def test_evaluate_constraints_detects_slow_attack() -> None:
    generated = _generated(spectral_analysis={"attack_measured_ms": 12.0})
    assert _spec().evaluate_constraints(generated)["attack_ms"] is False


def test_evaluate_constraints_detects_shallow_high_pass() -> None:
    # -6 dB/oct is a single-pole high-pass: not enough attenuation below the floor.
    generated = _generated(spectral_analysis={"floor_slope_db_per_oct": -6.0})
    assert _spec().evaluate_constraints(generated)["spectral_floor_hz"] is False


def test_steeper_high_pass_than_required_still_passes() -> None:
    generated = _generated(spectral_analysis={"floor_slope_db_per_oct": -48.0})
    assert _spec().evaluate_constraints(generated)["spectral_floor_hz"] is True


def test_evaluate_constraints_detects_wrong_tilt() -> None:
    # Spec asks for -3 dB/oct, measurement came back flat.
    tilted = _spec(spectral_tilt_db_per_octave=-3.0)
    flat = _generated(spectral_analysis={"tilt_measured_db_per_octave": 0.0})
    assert tilted.evaluate_constraints(flat)["spectral_tilt_db_per_octave"] is False


def test_evaluate_constraints_accepts_tilt_within_tolerance() -> None:
    tilted = _spec(spectral_tilt_db_per_octave=-3.0)
    drifted = _generated(spectral_analysis={"tilt_measured_db_per_octave": -4.2})
    assert tilted.evaluate_constraints(drifted)["spectral_tilt_db_per_octave"] is True


def test_flat_tilt_passes_when_none_requested() -> None:
    assert _spec().evaluate_constraints(_generated())["spectral_tilt_db_per_octave"] is True


def test_evaluate_constraints_detects_oversized_file() -> None:
    # 900 ms vs. the 800 ms target is a 12.5% error, far past the 2% default.
    assert _spec().evaluate_constraints(_generated(duration_ms=900))["duration_ms"] is False


def test_tighter_tolerance_turns_pass_into_failure() -> None:
    generated = _generated(peak_db=-12.4)
    assert _spec().evaluate_constraints(generated)["peak_db"] is True

    strict = _spec(tolerances={"peak_db": 0.1})
    assert strict.evaluate_constraints(generated)["peak_db"] is False


def test_evaluate_constraints_uses_derived_loop_duration() -> None:
    loop = GenerationSpec.model_validate(VALID_LOOP)
    # Derived duration is 938 ms; 940 ms is within the 2% band.
    ok = GeneratedFile.model_validate(
        {
            "url": "https://cdn.example.com/out/hat_0.wav",
            "duration_ms": 940,
            "peak_db": -6.0,
            "spectral_analysis": {
                "fundamental_detected_hz": 800.0,
                "ceiling_violation_db": -60.0,
                "attack_measured_ms": 0.5,
                "floor_slope_db_per_oct": -18.0,
                "tilt_measured_db_per_octave": 0.0,
            },
        }
    )
    assert loop.evaluate_constraints(ok)["duration_ms"] is True


def test_evaluate_constraints_output_feeds_response() -> None:
    spec = _spec()
    generated = _generated(spectral_analysis={"fundamental_detected_hz": 120.0})
    response = GenerationResponse(
        job_id="job_qc",
        status="complete_with_warnings",
        files=[generated],
        constraints_met=spec.evaluate_constraints(generated),
    )
    assert response.constraints_met["fundamental_hz"] is False
    assert response.constraints_met["peak_db"] is True
    assert response.status == "complete_with_warnings"
