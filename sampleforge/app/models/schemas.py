"""Pydantic schemas for SampleForge.

This module defines the machine-readable contract of the product:
:class:`GenerationSpec` — a full description of a desired audio sample, split
into **hard constraints** (spectral and temporal targets that are enforced by
post-processing and verified after generation) and **soft context** (musical
facts fed to the model as conditioning signals that shape, but never guarantee,
the output).

The response models (:class:`GenerationResponse`, :class:`GeneratedFile`,
:class:`SpectralAnalysis`) carry the post-generation measurements that the
client uses to decide whether a variant is usable.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Type aliases kept small and explicit so the API docs and the OpenAPI schema
# stay readable (and so no `Any` leaks into the public contract).
SampleType = Literal["one_shot", "loop", "texture", "stinger"]
OutputFormat = Literal["wav", "flac", "mp3"]

#: Lifecycle of a job. ``complete_with_warnings`` is a success state, not a
#: failure: the audio was delivered and met the constraints the post-processing
#: chain could guarantee, but at least one hard constraint was missed and the
#: caller should check ``constraints_met`` before shipping the file.
JobStatus = Literal[
    "queued",
    "processing",
    "complete",
    "complete_with_warnings",
    "failed",
]

# The same values as constants, so the worker (which writes them) and the API
# (which filters on them) cannot drift apart. Defined here rather than in the
# worker to keep the API from importing a module that pulls in librosa.
STATUS_QUEUED: Final[str] = "queued"
STATUS_PROCESSING: Final[str] = "processing"
STATUS_COMPLETE: Final[str] = "complete"
STATUS_COMPLETE_WITH_WARNINGS: Final[str] = "complete_with_warnings"
STATUS_FAILED: Final[str] = "failed"

#: Statuses that mean a job will not change again.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_COMPLETE, STATUS_COMPLETE_WITH_WARNINGS, STATUS_FAILED}
)

#: Statuses counted as "the batch produced output" for aggregate reporting.
SUCCESS_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_COMPLETE, STATUS_COMPLETE_WITH_WARNINGS}
)

#: Sample rates a mastering house will actually hand us. Anything else is a
#: mistake (or a resampling surprise) rather than an intent.
SUPPORTED_SAMPLE_RATES: frozenset[int] = frozenset({44100, 48000, 88200, 96000})

#: Bit depths we can write without upsampling artefacts in the output file.
SUPPORTED_BIT_DEPTHS: frozenset[int] = frozenset({16, 24, 32})


class Tolerances(BaseModel):
    """Per-constraint slack used when verifying a rendered sample.

    DSP post-processing can only ever get *close* to a target: a filter's
    roll-off is finite, a fade is sample-quantised, and a peak normaliser lands
    on the nearest representable step. Without tolerances, every generated file
    would report as a constraint violation over floating-point dust.

    Tolerances turn the spec's exact targets into pass/fail bands for
    :meth:`GenerationSpec.evaluate_constraints`. Defaults are tuned to be tight
    enough to catch real failures (a wrong pitch, a missing low-pass, a clipped
    master) while ignoring measurement noise. Loosen them when you want
    "close enough to use", tighten them when you want a QC gate.

    Slack tolerances are non-negative — a negative one would make the constraint
    unsatisfiable. The two roll-off thresholds (:attr:`ceiling_violation_db` and
    :attr:`floor_slope_db_per_oct`) are instead required to be non-positive,
    because they bound how much energy may leak past a filter, not how far a
    measurement may drift from its target.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    fundamental_hz: float = Field(
        default=5.0,
        ge=0.0,
        description=(
            "Slack in Hz added to *both* edges of fundamental_hz when checking "
            "the detected fundamental. Raise it for wide-window windows "
            "(e.g. pads) where small pitch deviations are inaudible."
        ),
    )
    ceiling_violation_db: float = Field(
        default=-40.0,
        le=0.0,
        description=(
            "Maximum tolerated stopband energy above spectral_ceiling_hz, in dB "
            "relative to the passband. The default -40 dB demands a clean "
            "roll-off; must be <= 0 (a positive value would defeat the "
            "constraint entirely)."
        ),
    )
    floor_slope_db_per_oct: float = Field(
        default=-12.0,
        le=0.0,
        description=(
            "Steepest high-pass roll-off accepted below spectral_floor_hz, in dB "
            "per octave. The default -12 dB/oct requires at least a 2-pole "
            "high-pass (-24 dB/oct would satisfy it comfortably); a shallower "
            "measurement means low-end energy is bleeding through."
        ),
    )
    peak_db: float = Field(
        default=0.5,
        ge=0.0,
        description="Absolute tolerance in dB around the target peak level.",
    )
    attack_ms: float = Field(
        default=2.0,
        ge=0.0,
        description="Absolute tolerance in milliseconds on the measured attack.",
    )
    tilt_db_per_octave: float = Field(
        default=1.5,
        ge=0.0,
        description=(
            "Absolute tolerance in dB per octave on the measured spectral tilt "
            "versus spectral_tilt_db_per_octave. Slopes are fitted across many "
            "octaves, so this is naturally looser than the level tolerances."
        ),
    )
    duration_pct: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description=(
            "Relative tolerance on total duration (0.02 = 2%). One rendered "
            "sample at 44.1 kHz is 2.3 ms, so the default already permits "
            "off-by-one rounding."
        ),
    )
    stereo_width: float = Field(
        default=0.05,
        ge=0.0,
        description=(
            "Absolute tolerance on the measured side/mid ratio. M/S rescaling "
            "hits its target closely, so this is mostly a guard against the "
            "ratio being undefined on near-mono material."
        ),
    )


class GenerationSpec(BaseModel):
    """A machine-readable specification of a single audio sample.

    A spec is the only input the generation pipeline needs. It answers four
    questions:

    1. **What kind of sound?** — :attr:`type`, :attr:`category`.
    2. **How long and in what format?** — :attr:`duration_ms` /
       :attr:`duration_beats`, :attr:`sample_rate`, :attr:`bit_depth`,
       :attr:`channels`, :attr:`format`, :attr:`metadata_embed`.
    3. **What must the signal obey?** — the *hard* constraints
       (:attr:`fundamental_hz`, :attr:`spectral_floor_hz`,
       :attr:`spectral_ceiling_hz`, :attr:`spectral_tilt_db_per_octave`,
       :attr:`peak_db`, and the ADSR envelope in :attr:`attack_ms`,
       :attr:`decay_ms`, :attr:`sustain_level`, :attr:`release_ms`).
       These are enforced by DSP post-processing and then re-measured; the
       result is reported back in :class:`SpectralAnalysis` and judged by
       :meth:`evaluate_constraints` against :attr:`tolerances`.
    4. **What musical context should bias the model?** — the *soft* context
       (:attr:`bpm`, :attr:`key`, :attr:`genre`, :attr:`mood`,
       :attr:`reference_sample_url`). The model is conditioned on these, but
       they are never guaranteed: a loop tagged ``128 BPM`` may contain
       microtiming that a human then straightens out.

    The distinction matters when reading generation results: a hard constraint
    that was missed is a bug in the post-processing chain, while a soft hint
    that was ignored is not.

    **Duration handling.** Time-based samples (:attr:`type` other than
    ``"loop"``) are measured in milliseconds via :attr:`duration_ms`.
    Loops are measured in beats via :attr:`duration_beats` and additionally
    require :attr:`bpm`, which lets the validator derive the loop's real
    duration (``beats * 60000 / bpm``) so the envelope and duration
    constraints can be checked for loops as well.

    **Cross-field validation** (performed in a single ``model_validator``):

    * ``type="loop"`` requires :attr:`duration_beats` and :attr:`bpm`; every
      other type requires :attr:`duration_ms`.
    * :attr:`fundamental_hz` must be an ascending, positive range.
    * The fundamental must sit strictly *inside* the usable band:
      ``spectral_floor_hz < fundamental_min <= fundamental_max <
      spectral_ceiling_hz``. A fundamental outside the band would be removed
      by its own high-pass/low-pass, making the spec self-contradictory.
    * ``attack_ms + decay_ms + release_ms < duration_ms`` — the envelope has to
      fit inside the sample with room to spare.

    Examples:
        >>> spec = GenerationSpec(
        ...     type="one_shot",
        ...     category="kick",
        ...     duration_ms=800,
        ...     fundamental_hz=(40.0, 90.0),
        ...     spectral_floor_hz=25.0,
        ...     spectral_ceiling_hz=12000.0,
        ...     peak_db=-12.0,
        ...     attack_ms=1.0,
        ...     decay_ms=400.0,
        ...     sustain_level=0.0,
        ...     release_ms=50.0,
        ...     bpm=140.0,
        ...     key="F#m",
        ...     genre="techno",
        ... )
        >>> spec.duration_ms
        800
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "type": "one_shot",
                "category": "kick",
                "duration_ms": 800,
                "sample_rate": 44100,
                "bit_depth": 24,
                "channels": 2,
                "fundamental_hz": [40.0, 90.0],
                "spectral_ceiling_hz": 12000.0,
                "spectral_floor_hz": 25.0,
                "spectral_tilt_db_per_octave": -3.0,
                "peak_db": -12.0,
                "attack_ms": 1.0,
                "decay_ms": 400.0,
                "sustain_level": 0.0,
                "release_ms": 50.0,
                "bpm": 140.0,
                "key": "F#m",
                "genre": "techno",
                "mood": "dark",
                "batch_size": 4,
                "diversity": 0.7,
                "format": "wav",
                "metadata_embed": True,
            }
        },
    )

    # ------------------------------------------------------------------
    # 1. Basic — what the sample is and how it is delivered.
    # ------------------------------------------------------------------
    type: SampleType = Field(
        description=(
            "Sound archetype. 'one_shot' is a single hit (kick, snare), 'loop' "
            "is a beat-aligned loop, 'texture' is an evolving bed or drone, and "
            "'stinger' is a short dramatic transition."
        )
    )
    category: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Instrument/role slug, e.g. 'kick', 'snare', 'hihat', 'riser', 'impact', 'pad'."
        ),
        examples=["kick"],
    )
    duration_ms: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Length in milliseconds. Required for every type except 'loop'. "
            "For loops this field is derived from duration_beats and bpm."
        ),
    )
    duration_beats: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Length in beats (e.g. 2.0 for a one-bar loop at 4/4). Required "
            "when type='loop'; ignored otherwise."
        ),
    )
    sample_rate: int = Field(default=44100, description="Sample rate in Hz.")
    bit_depth: int = Field(default=24, description="Bit depth of the written file.")
    channels: int = Field(default=2, description="1 = mono, 2 = stereo.")

    # ------------------------------------------------------------------
    # 2. Spectral constraints — hard, enforced by post-processing.
    # ------------------------------------------------------------------
    fundamental_hz: tuple[float, float] = Field(
        description=(
            "Permitted range for the fundamental frequency as (min_hz, max_hz). "
            "Hard constraint: the generated fundamental is pitch-shifted into "
            "this window."
        ),
        examples=[(40.0, 90.0)],
    )
    spectral_ceiling_hz: float = Field(
        gt=0,
        description=(
            "Low-pass corner in Hz. All energy above this frequency is rolled "
            "off (hard constraint)."
        ),
    )
    spectral_floor_hz: float = Field(
        ge=0,
        description=(
            "High-pass corner in Hz. All energy below this frequency is removed "
            "(hard constraint). Must stay below fundamental_hz[0]."
        ),
    )
    spectral_tilt_db_per_octave: float = Field(
        default=0.0,
        ge=-24.0,
        le=24.0,
        description=(
            "Spectral tilt applied per octave above the fundamental. Negative "
            "values darken the sample, positive values brighten it. 0.0 leaves "
            "the natural balance untouched."
        ),
    )
    peak_db: float = Field(
        le=0.0,
        ge=-100.0,
        description=(
            "Target peak level in dBFS (e.g. -12.0). The output is normalised to "
            "this value; it must not exceed 0 dBFS to avoid clipping."
        ),
    )

    # ------------------------------------------------------------------
    # 3. Temporal constraints — hard, enforced on the amplitude envelope.
    # ------------------------------------------------------------------
    attack_ms: float = Field(ge=0.0, description="Attack time in milliseconds.")
    decay_ms: float = Field(ge=0.0, description="Decay time in milliseconds.")
    sustain_level: float = Field(
        ge=0.0,
        le=1.0,
        description="Sustain amplitude as a 0-1 fraction of the peak level.",
    )
    release_ms: float = Field(ge=0.0, description="Release time in milliseconds.")

    # ------------------------------------------------------------------
    # 4. Context — soft, used only as model conditioning.
    # ------------------------------------------------------------------
    bpm: float = Field(
        gt=0.0,
        le=400.0,
        description=(
            "Tempo in BPM. Soft conditioning — except for loops, where it also "
            "defines the sample's real duration."
        ),
    )
    key: str = Field(
        min_length=1,
        max_length=32,
        description="Musical key, e.g. 'F#m', 'C major', 'A min'.",
    )
    genre: str = Field(
        min_length=1,
        max_length=64,
        description="Target genre, e.g. 'techno', 'house', 'cinematic'.",
    )
    mood: str | None = Field(
        default=None,
        max_length=64,
        description="Optional mood descriptor, e.g. 'dark', 'aggressive', 'ethereal'.",
    )
    reference_sample_url: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "Optional URL of a reference sample ('make something like this'). "
            "Soft conditioning only — the model never copies the reference."
        ),
    )

    # ------------------------------------------------------------------
    # 5. Batch — how many variants and how far apart they should be.
    # ------------------------------------------------------------------
    batch_size: int = Field(
        default=1,
        ge=1,
        le=64,
        description="Number of variants to generate for this spec.",
    )
    diversity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Variation between batch items: 0.0 = identical, 1.0 = maximum variation.",
    )

    # ------------------------------------------------------------------
    # 6. Output — delivery format and metadata.
    # ------------------------------------------------------------------
    format: OutputFormat = Field(
        default="wav",
        description="Container/codec of the delivered file.",
    )
    metadata_embed: bool = Field(
        default=True,
        description=(
            "Embed licence and generation parameters in the file metadata "
            "(ID3v2 for mp3, VBRI for flac, LIST/INFO for wav)."
        ),
    )
    stereo_width: float | None = Field(
        default=None,
        ge=0.0,
        le=4.0,
        description=(
            "Target side/mid level ratio, enforced with M/S processing. 0.0 "
            "collapses the sample to mono, 1.0 gives an equal side and mid "
            "level, higher values exaggerate the stereo image. None leaves the "
            "model's own width untouched."
        ),
    )

    # ------------------------------------------------------------------
    # 7. Verification — how close is close enough?
    # ------------------------------------------------------------------
    tolerances: Tolerances = Field(
        default_factory=Tolerances,
        description=(
            "Slack applied when checking the rendered output against this "
            "spec's hard constraints. See :meth:`evaluate_constraints`."
        ),
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_spec(self) -> Self:
        """Validate cross-field consistency of the spec.

        Runs after every field has been parsed, so it can compare values that
        belong to different groups (a beats-based duration against a
        millisecond envelope, for example). On success the validated model is
        returned; on failure a :class:`ValueError` is raised and Pydantic
        reports it as a field error for this model.

        Raises:
            ValueError: If the delivery format (sample rate, bit depth,
                channels) is unsupported, the duration fields do not match
                :attr:`type`, the fundamental range is malformed, the
                fundamental falls outside the passband, or the envelope does
                not fit inside the duration.
        """
        # --- delivery format ---------------------------------------------
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"unsupported sample_rate {self.sample_rate}; "
                f"expected one of {sorted(SUPPORTED_SAMPLE_RATES)}"
            )
        if self.bit_depth not in SUPPORTED_BIT_DEPTHS:
            raise ValueError(
                f"unsupported bit_depth {self.bit_depth}; "
                f"expected one of {sorted(SUPPORTED_BIT_DEPTHS)}"
            )
        if self.channels not in (1, 2):
            raise ValueError(f"channels must be 1 (mono) or 2 (stereo), got {self.channels}")

        # --- duration semantics -------------------------------------------
        if self.type == "loop":
            if self.duration_beats is None:
                raise ValueError("duration_beats is required when type='loop'")
            # Beats only mean something against a tempo, so a loop without BPM
            # has no derivable duration (and therefore no valid envelope).
            duration_ms = round(self.duration_beats * 60_000.0 / self.bpm)
        else:
            if self.duration_ms is None:
                raise ValueError(f"duration_ms is required when type={self.type!r}")
            duration_ms = self.duration_ms

        # --- fundamental range -------------------------------------------
        f_min, f_max = self.fundamental_hz
        if f_min <= 0:
            raise ValueError(f"fundamental_hz minimum must be > 0 Hz, got {f_min}")
        if f_min >= f_max:
            raise ValueError(f"fundamental_hz must be ascending: got ({f_min}, {f_max})")

        # --- spectral band containment -----------------------------------
        # A fundamental outside [floor, ceiling] would be removed by its own
        # high-pass/low-pass, so the spec would contradict itself.
        if self.spectral_floor_hz >= f_min:
            raise ValueError(
                f"spectral_floor_hz ({self.spectral_floor_hz} Hz) must be below "
                f"the fundamental minimum ({f_min} Hz)"
            )
        if self.spectral_ceiling_hz <= f_max:
            raise ValueError(
                f"spectral_ceiling_hz ({self.spectral_ceiling_hz} Hz) must be above "
                f"the fundamental maximum ({f_max} Hz)"
            )

        # --- envelope fits inside the sample ------------------------------
        envelope_ms = self.attack_ms + self.decay_ms + self.release_ms
        if envelope_ms >= duration_ms:
            raise ValueError(
                f"envelope does not fit: attack_ms + decay_ms + release_ms = "
                f"{envelope_ms:.2f} ms must be less than the duration "
                f"({duration_ms} ms)"
            )

        return self

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    @classmethod
    def from_json(cls, path: str | Path) -> Self:
        """Load a spec from a JSON file — the recipe format.

        Recipes are plain JSON documents so they can live in a repo, be shared
        between projects, or be edited by a human without touching Python. Any
        ``GenerationSpec`` field may be set; validation is identical to normal
        construction, so a malformed recipe fails here rather than deep inside
        a worker.

        Args:
            path: Path to a ``.json`` file containing a spec object.

        Returns:
            The validated :class:`GenerationSpec`.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            pydantic.ValidationError: If the JSON is valid but does not
                describe a valid spec.

        Example:
            >>> spec = GenerationSpec.from_json("recipes/deep_kick.json")  # doctest: +SKIP
            >>> spec.category  # doctest: +SKIP
            'kick'
        """
        recipe_path = Path(path)
        with recipe_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.model_validate(payload)

    def to_json(self, path: str | Path, *, indent: int = 2) -> Path:
        """Write the spec to a JSON file, e.g. to save a tuned spec as a recipe.

        Args:
            path: Destination file path.
            indent: JSON indentation for readability.

        Returns:
            The path that was written.
        """
        out_path = Path(path)
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(self.model_dump(mode="json"), handle, indent=indent)
            handle.write("\n")
        return out_path

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def effective_duration_ms(self) -> int:
        """The sample's real duration in milliseconds.

        For loops this is derived from :attr:`duration_beats` and :attr:`bpm`
        (``beats * 60000 / bpm``); otherwise it is :attr:`duration_ms`.
        """
        if self.type == "loop" and self.duration_beats is not None:
            return round(self.duration_beats * 60_000.0 / self.bpm)
        if self.duration_ms is None:
            raise ValueError(f"duration_ms is not set for type={self.type!r}")
        return self.duration_ms

    @property
    def total_frames(self) -> int:
        """Number of sample frames the rendered output will contain."""
        return round(self.effective_duration_ms * self.sample_rate / 1000.0)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def evaluate_constraints(self, generated: GeneratedFile) -> dict[str, bool]:
        """Check a rendered variant against this spec's hard constraints.

        Compares post-generation measurements to the requested targets, with
        :attr:`tolerances` applied, and returns the same pass/fail map shape as
        :attr:`GenerationResponse.constraints_met`.

        Only constraints that are *measurable* from a rendered file are checked, so
        every hard constraint in this spec has a verdict here. The spectral
        floor and tilt are verified indirectly, via the fitted slopes in
        :class:`SpectralAnalysis` rather than point measurements.

        Args:
            generated: A rendered variant with its measured analysis.

        Returns:
            Mapping of constraint name to whether it was met. Keys are stable:
            ``duration_ms``, ``peak_db``, ``fundamental_hz``,
            ``spectral_ceiling_hz``, ``spectral_floor_hz``,
            ``spectral_tilt_db_per_octave``, ``attack_ms``.

        Example:
            >>> spec = GenerationSpec.from_json("recipes/deep_kick.json")  # doctest: +SKIP
            >>> spec.evaluate_constraints(file)["fundamental_hz"]  # doctest: +SKIP
            True
        """
        tol = self.tolerances
        analysis = generated.spectral_analysis
        f_min, f_max = self.fundamental_hz

        expected_duration = self.effective_duration_ms
        duration_error = abs(generated.duration_ms - expected_duration) / expected_duration

        return {
            "duration_ms": duration_error <= tol.duration_pct,
            "peak_db": abs(generated.peak_db - self.peak_db) <= tol.peak_db,
            "fundamental_hz": (
                f_min - tol.fundamental_hz
                <= analysis.fundamental_detected_hz
                <= f_max + tol.fundamental_hz
            ),
            "spectral_ceiling_hz": (analysis.ceiling_violation_db <= tol.ceiling_violation_db),
            # A steeper-than-required roll-off passes: the requirement is a
            # floor on attenuation, so -24 dB/oct satisfies a -12 dB/oct target.
            "spectral_floor_hz": (analysis.floor_slope_db_per_oct <= tol.floor_slope_db_per_oct),
            "spectral_tilt_db_per_octave": (
                abs(analysis.tilt_measured_db_per_octave - self.spectral_tilt_db_per_octave)
                <= tol.tilt_db_per_octave
            ),
            "attack_ms": (abs(analysis.attack_measured_ms - self.attack_ms) <= tol.attack_ms),
        }


class SpectralAnalysis(BaseModel):
    """Measurements taken from a generated file *after* post-processing.

    These are the empirical values, not the requested ones. Comparing them
    against the originating :class:`GenerationSpec` tells you whether the hard
    constraints were actually honoured.

    The first three fields come from point measurements (a pitch estimate, a
    band energy ratio, an envelope segmentation). :attr:`floor_slope_db_per_oct`
    and :attr:`tilt_measured_db_per_octave` come from least-squares slope fits
    over the spectrum, which is why they are reported as dB per octave rather
    than absolute dB.
    """

    model_config = ConfigDict(extra="forbid")

    fundamental_detected_hz: float = Field(
        gt=0.0,
        description="Fundamental frequency measured in the output, in Hz.",
    )
    ceiling_violation_db: float = Field(
        description=(
            "Energy found above spectral_ceiling_hz, in dB relative to the "
            "ceiling. 0.0 or less means the roll-off held; positive values mean "
            "the ceiling was exceeded."
        ),
    )
    attack_measured_ms: float = Field(
        ge=0.0,
        description="Attack time measured in the output, in milliseconds.",
    )
    floor_slope_db_per_oct: float = Field(
        le=0.0,
        description=(
            "Measured high-pass slope below spectral_floor_hz, in dB per octave. "
            "Negative values mean energy falls as frequency drops: -6 is a "
            "single-pole filter, -24 is a 4-pole one. Values >= 0 mean no "
            "usable high-pass was applied."
        ),
    )
    tilt_measured_db_per_octave: float = Field(
        ge=-24.0,
        le=24.0,
        description=(
            "Measured spectral slope above the fundamental, in dB per octave. "
            "Compared against the spec's spectral_tilt_db_per_octave to confirm "
            "the requested darkening or brightening was actually applied."
        ),
    )


class GeneratedFile(BaseModel):
    """A single rendered variant produced by a generation job.

    Only :attr:`url` is guaranteed: a job row records where each variant landed,
    and the measurements are filled in when the analysis pass runs over the
    stored file. They are optional rather than zeroed so a consumer can tell
    "not measured" from "measured as zero" — a peak of 0 dBFS is a clipped
    master, not a missing value.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        min_length=1,
        description="Download URL for the rendered file (typically a signed URL).",
    )
    duration_ms: int | None = Field(
        default=None,
        gt=0,
        description="Measured length of the rendered file, when analysed.",
    )
    peak_db: float | None = Field(
        default=None,
        le=0.0,
        description="Measured peak level in dBFS, when analysed.",
    )
    spectral_analysis: SpectralAnalysis | None = Field(
        default=None,
        description="Post-generation spectral and temporal measurements, when analysed.",
    )


class GenerationResponse(BaseModel):
    """Result of a generation job, returned by the API and the worker.

    One entry is present in :attr:`files` per generated variant, so
    ``len(files)`` should equal the spec's ``batch_size`` on success.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(description="Identifier of the generation job.")
    status: JobStatus = Field(description="Current or final job status.")
    files: list[GeneratedFile] = Field(
        default_factory=list,
        description="Rendered variants, one per successful sample in the batch.",
    )
    constraints_met: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Per-constraint pass/fail map, keyed by constraint name (e.g. "
            "{'fundamental_hz': true, 'spectral_ceiling_hz': true}). Built by "
            "GenerationSpec.evaluate_constraints, so when a job completes "
            "normally it carries a verdict on every hard constraint."
        ),
    )
    spec: GenerationSpec | None = Field(
        default=None,
        description=(
            "The spec this job was submitted with, echoed back so a client can "
            "rebuild overlays and reports without having kept its own copy. "
            "None only when the stored spec no longer validates."
        ),
    )


class JobListItem(GenerationResponse):
    """One job as it appears in the recent-jobs list.

    A superset of :class:`GenerationResponse`: everything a job poll returns,
    plus the row metadata a list needs (ownership by a batch or recipe, and
    when the job was created and last touched).
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: str | None = Field(default=None, description="Batch this job belongs to, if any.")
    recipe_id: str | None = Field(
        default=None, description="Recipe this job was launched from, if any."
    )
    created_at: datetime = Field(description="When the job was submitted.")
    updated_at: datetime = Field(description="When the job last changed state.")


class JobList(BaseModel):
    """A page of recent jobs."""

    model_config = ConfigDict(extra="forbid")

    items: list[JobListItem] = Field(
        default_factory=list, description="Jobs in this page, newest first."
    )
    total: int = Field(description="Total jobs matching the query.")
    limit: int = Field(description="Page size applied.")
    offset: int = Field(description="Offset applied.")


class HealthResponse(BaseModel):
    """Service health, as reported by ``GET /v1/health``.

    ``status`` is ``"ok"`` or ``"degraded"``. The HTTP status stays 200 either
    way: a 503 would take the instance out of a load balancer's rotation, which
    is the opposite of what an operator wants when one optional component is
    unhappy.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"] = Field(
        description="'degraded' when a dependency is unavailable."
    )
    model_loaded: bool = Field(description="Whether this process already holds a loaded generator.")
    gpu_available: bool = Field(description="Whether a CUDA device is usable.")
    queue_depth: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Jobs waiting in the arq queue, or null when the broker could not "
            "be reached. Null, not 0: an unreachable broker and an empty queue "
            "are different situations."
        ),
    )
    version: str = Field(description="Service version.")
    detail: str | None = Field(default=None, description="Why the service is degraded, when it is.")


# ----------------------------------------------------------------------
# Job submission
# ----------------------------------------------------------------------
class JobSubmitResponse(BaseModel):
    """Acknowledgement returned when a job is accepted.

    Carries the poll URL rather than making the client construct it, so the
    path shape lives in one place.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(description="Identifier of the queued job.")
    status: JobStatus = Field(description="Job status at submission time.")
    poll_url: str = Field(description="Path to poll for the job's result.")


class BatchOptions(BaseModel):
    """How a multi-job batch should be executed.

    Attributes:
        parallel: Enqueue every job immediately rather than one at a time.
        max_concurrent: Ceiling on jobs running at once. The worker applies it;
            the API passes it through, so submitting a batch of 50 with
            ``max_concurrent=4`` costs the same as submitting 4.
        on_failure: ``"stop"`` cancels the remaining jobs when one fails;
            ``"continue"`` lets the batch finish so partial results are usable.
    """

    model_config = ConfigDict(extra="forbid")

    parallel: bool = Field(default=True, description="Enqueue all jobs immediately.")
    max_concurrent: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Maximum jobs the worker should run at once.",
    )
    on_failure: Literal["stop", "continue"] = Field(
        default="continue",
        description="What to do with the rest of the batch when a job fails.",
    )


class BatchRequest(BaseModel):
    """A batch of independent generation jobs submitted together."""

    model_config = ConfigDict(extra="forbid")

    specs: list[GenerationSpec] = Field(
        min_length=1,
        max_length=100,
        description="One spec per job. Each is queued as its own job.",
    )
    options: BatchOptions = Field(
        default_factory=BatchOptions, description="Batch execution options."
    )


class BatchSubmitResponse(BaseModel):
    """Acknowledgement returned when a batch is accepted."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(description="Identifier shared by every job in the batch.")
    total_jobs: int = Field(description="How many jobs were created.")
    poll_url: str = Field(description="Path to poll for the batch's progress.")


class BatchProgressResponse(BaseModel):
    """Aggregate state of a batch, recomputed from its jobs on every poll.

    Counts are derived, never incremented in place: a poll always reflects the
    database, so a worker crash cannot leave a batch permanently reporting 3 of
    4 when the truth is unknowable.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(description="The batch being polled.")
    completed: int = Field(description="Jobs that finished, with or without warnings.")
    failed: int = Field(description="Jobs that failed.")
    total: int = Field(description="Jobs in the batch.")
    results: list[GenerationResponse] = Field(
        default_factory=list,
        description="Per-job results, in submission order.",
    )


class BatchListItem(BaseModel):
    """One batch as it appears in the batch list.

    Carries the same derived counts as :class:`BatchProgressResponse` but not
    the per-job results — a list of N batches must not ship N full result sets.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(description="Identifier shared by every job in the batch.")
    completed: int = Field(description="Jobs that finished, with or without warnings.")
    failed: int = Field(description="Jobs that failed.")
    total: int = Field(description="Jobs in the batch.")
    created_at: datetime = Field(description="When the batch was submitted.")


class BatchList(BaseModel):
    """A page of batches."""

    model_config = ConfigDict(extra="forbid")

    items: list[BatchListItem] = Field(
        default_factory=list, description="Batches in this page, newest first."
    )
    total: int = Field(description="Total batches matching the query.")
    limit: int = Field(description="Page size applied.")
    offset: int = Field(description="Offset applied.")


# ----------------------------------------------------------------------
# Recipes
# ----------------------------------------------------------------------
class RecipeCreate(BaseModel):
    """A named, reusable spec saved for later."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="Unique recipe name.")
    description: str | None = Field(
        default=None, max_length=512, description="What this recipe is for."
    )
    spec: GenerationSpec = Field(description="The spec to save.")


class RecipeUpdate(BaseModel):
    """Partial update of a saved recipe.

    Every field is optional, so a caller can rename a recipe without resending
    the spec, or edit the spec without touching the name.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128, description="New name.")
    description: str | None = Field(default=None, max_length=512, description="New description.")
    spec: GenerationSpec | None = Field(default=None, description="New spec.")


class RecipeRead(BaseModel):
    """A saved recipe as returned by the API."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str = Field(description="Recipe identifier.")
    name: str = Field(description="Unique recipe name.")
    description: str | None = Field(default=None, description="What it is for.")
    spec: GenerationSpec = Field(description="The stored spec.")
    created_at: datetime = Field(description="When the recipe was saved.")
    updated_at: datetime = Field(description="When the recipe was last modified.")


class RecipeList(BaseModel):
    """A page of recipes."""

    model_config = ConfigDict(extra="forbid")

    items: list[RecipeRead] = Field(
        default_factory=list, description="Recipes in this page, newest first."
    )
    total: int = Field(description="Total recipes matching the query.")
    limit: int = Field(description="Page size applied.")
    offset: int = Field(description="Offset applied.")


class RecipeRunResponse(JobSubmitResponse):
    """Acknowledgement for a job launched from a saved recipe."""
