import { expect, test } from 'vitest';
import {
	defaultSpec,
	effectiveDurationMs,
	getPath,
	isValidSpec,
	setPath,
	validateSpec
} from './spec.js';

test('the default spec is valid', () => {
	expect(validateSpec(defaultSpec())).toEqual({});
	expect(isValidSpec(defaultSpec())).toBe(true);
});

test('reads and writes dotted paths without mutating the original', () => {
	const spec = defaultSpec();
	const updated = setPath(spec, 'tolerances.peak_db', 2);
	expect(getPath(updated, 'tolerances.peak_db')).toBe(2);
	expect(getPath(spec, 'tolerances.peak_db')).toBe(0.5);
});

test('rejects a loop without a beat count', () => {
	const spec = { ...defaultSpec(), type: 'loop' as const, duration_ms: null };
	expect(validateSpec(spec)).toHaveProperty('duration_beats');
});

test('derives loop duration from beats and bpm', () => {
	const spec = { ...defaultSpec(), type: 'loop' as const, duration_beats: 4, bpm: 120 };
	expect(effectiveDurationMs(spec)).toBe(2000);
});

test('rejects an envelope longer than the sample', () => {
	const spec = { ...defaultSpec(), duration_ms: 100, attack_ms: 50, decay_ms: 40, release_ms: 20 };
	expect(validateSpec(spec)).toHaveProperty('attack_ms');
});

test('rejects a floor above the fundamental', () => {
	const spec = { ...defaultSpec(), spectral_floor_hz: 100 };
	expect(validateSpec(spec)).toHaveProperty('spectral_floor_hz');
});

test('rejects a ceiling below the fundamental', () => {
	const spec = { ...defaultSpec(), spectral_ceiling_hz: 80 };
	expect(validateSpec(spec)).toHaveProperty('spectral_ceiling_hz');
});
