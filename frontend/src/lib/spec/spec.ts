import type { GenerationSpec, Tolerances } from './types.js';

export function defaultTolerances(): Tolerances {
	return {
		fundamental_hz: 5.0,
		ceiling_violation_db: -40.0,
		floor_slope_db_per_oct: -12.0,
		peak_db: 0.5,
		attack_ms: 2.0,
		tilt_db_per_octave: 1.5,
		duration_pct: 0.02,
		stereo_width: 0.05
	};
}

export function defaultSpec(): GenerationSpec {
	return {
		type: 'one_shot',
		category: 'kick',
		duration_ms: 800,
		duration_beats: null,
		sample_rate: 44100,
		bit_depth: 24,
		channels: 2,
		fundamental_hz: [40, 90],
		spectral_ceiling_hz: 12000,
		spectral_floor_hz: 25,
		spectral_tilt_db_per_octave: 0,
		peak_db: -12,
		attack_ms: 1,
		decay_ms: 400,
		sustain_level: 0,
		release_ms: 50,
		bpm: 140,
		key: 'F#m',
		genre: 'techno',
		mood: null,
		reference_sample_url: null,
		batch_size: 1,
		diversity: 0.5,
		format: 'wav',
		metadata_embed: true,
		stereo_width: null,
		tolerances: defaultTolerances()
	};
}

export function getPath(obj: unknown, path: string): unknown {
	return path
		.split('.')
		.reduce<unknown>(
			(acc, key) =>
				acc === null || acc === undefined ? undefined : (acc as Record<string, unknown>)[key],
			obj
		);
}

export function setPath<T extends Record<string, unknown>>(
	obj: T,
	path: string,
	value: unknown
): T {
	const clone = structuredClone(obj) as Record<string, unknown>;
	const keys = path.split('.');
	let cursor: Record<string, unknown> = clone;
	for (const key of keys.slice(0, -1)) {
		cursor = cursor[key] as Record<string, unknown>;
	}
	cursor[keys[keys.length - 1]] = value;
	return clone as T;
}

/** Real length in ms: derived for loops (beats / bpm), direct otherwise. */
export function effectiveDurationMs(spec: GenerationSpec): number {
	if (spec.type === 'loop') {
		const beats = spec.duration_beats ?? 0;
		return spec.bpm > 0 ? Math.round((beats * 60000) / spec.bpm) : 0;
	}
	return spec.duration_ms ?? 0;
}

/**
 * Cross-field validation mirroring the backend's `GenerationSpec` validator.
 * Returns a map of dotted field path -> human-readable error; empty = valid.
 */
export function validateSpec(spec: GenerationSpec): Record<string, string> {
	const errors: Record<string, string> = {};

	if (!spec.category.trim()) {
		errors['category'] = 'Category is required.';
	}
	if (!spec.key.trim()) {
		errors['key'] = 'Key is required.';
	}
	if (!spec.genre.trim()) {
		errors['genre'] = 'Genre is required.';
	}

	if (spec.type === 'loop') {
		if (!spec.duration_beats || spec.duration_beats <= 0) {
			errors['duration_beats'] = 'Loops need a positive beat count.';
		}
	} else if (!spec.duration_ms || spec.duration_ms <= 0) {
		errors['duration_ms'] = 'Duration must be greater than 0 ms.';
	}

	const [fMin, fMax] = spec.fundamental_hz;
	if (fMin <= 0) {
		errors['fundamental_hz'] = 'Minimum must be above 0 Hz.';
	} else if (fMin >= fMax) {
		errors['fundamental_hz'] = 'Minimum must be below maximum.';
	}
	if (fMin > 0 && fMin < fMax) {
		if (spec.spectral_floor_hz >= fMin) {
			errors['spectral_floor_hz'] = `Floor must sit below the fundamental (${fMin} Hz).`;
		}
		if (spec.spectral_ceiling_hz <= fMax) {
			errors['spectral_ceiling_hz'] = `Ceiling must sit above the fundamental (${fMax} Hz).`;
		}
	}

	if (spec.peak_db > 0 || spec.peak_db < -100) {
		errors['peak_db'] = 'Peak must be between -100 and 0 dBFS.';
	}
	if (spec.sustain_level < 0 || spec.sustain_level > 1) {
		errors['sustain_level'] = 'Sustain is a 0-1 fraction.';
	}
	if (spec.bpm <= 0 || spec.bpm > 400) {
		errors['bpm'] = 'BPM must be between 0 and 400.';
	}
	if (spec.batch_size < 1 || spec.batch_size > 64) {
		errors['batch_size'] = 'Batch size is 1-64.';
	}
	if (spec.diversity < 0 || spec.diversity > 1) {
		errors['diversity'] = 'Diversity is a 0-1 scale.';
	}
	if (typeof spec.stereo_width === 'number' && (spec.stereo_width < 0 || spec.stereo_width > 4)) {
		errors['stereo_width'] = 'Stereo width is 0-4.';
	}

	const duration = effectiveDurationMs(spec);
	const envelope = spec.attack_ms + spec.decay_ms + spec.release_ms;
	if (duration > 0 && envelope >= duration) {
		errors['attack_ms'] = `ADSR (${envelope} ms) must fit inside ${duration} ms.`;
	}

	return errors;
}

export function isValidSpec(spec: GenerationSpec): boolean {
	return Object.keys(validateSpec(spec)).length === 0;
}
