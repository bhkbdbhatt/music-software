import { expect, test } from 'vitest';
import { computePeaks, mixPeaks } from './peaks.js';

test('computes one min/max pair per bucket', () => {
	const samples = new Float32Array(1000);
	for (let i = 0; i < samples.length; i++) samples[i] = Math.sin(i / 10);
	const peaks = computePeaks(samples, 50);
	expect(peaks.min).toHaveLength(50);
	expect(peaks.max).toHaveLength(50);
	for (let i = 0; i < 50; i++) {
		expect(peaks.min[i]).toBeLessThanOrEqual(peaks.max[i]);
	}
});

test('survives fewer samples than buckets', () => {
	const peaks = computePeaks(new Float32Array([0.5, -0.5]), 8);
	expect(peaks.min).toHaveLength(8);
	expect(peaks.max[0]).toBe(0.5);
	expect(peaks.min[4]).toBe(-0.5);
});

test('mixPeaks averages channels', () => {
	const a = new Float32Array([1, 1, 1, 1]);
	const b = new Float32Array([-1, -1, -1, -1]);
	const peaks = mixPeaks([a, b], 2);
	expect(peaks.max[0]).toBeCloseTo(0);
	expect(peaks.min[0]).toBeCloseTo(0);
});
