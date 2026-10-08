import { expect, test } from 'vitest';
import { binForFrequency, fftMagnitudes, hannWindow, spectrumAt } from './fft.js';

function sine(length: number, frequency: number, sampleRate: number): Float32Array {
	const data = new Float32Array(length);
	for (let i = 0; i < length; i++) {
		data[i] = Math.sin((2 * Math.PI * frequency * i) / sampleRate);
	}
	return data;
}

test('finds a 1 kHz sine at the expected bin', () => {
	const sampleRate = 44100;
	const fftSize = 4096;
	const magnitudes = fftMagnitudes(sine(fftSize, 1000, sampleRate), new Float32Array(fftSize));
	let peak = 0;
	for (let i = 1; i < magnitudes.length; i++) {
		if (magnitudes[i] > magnitudes[peak]) peak = i;
	}
	const frequency = (peak / magnitudes.length) * (sampleRate / 2);
	expect(frequency).toBeGreaterThan(980);
	expect(frequency).toBeLessThan(1020);
});

test('rejects non power-of-two input', () => {
	expect(() => fftMagnitudes(new Float32Array(100), new Float32Array(100))).toThrow();
});

test('hann window tapers at the edges', () => {
	const window = hannWindow(65);
	expect(window[0]).toBeCloseTo(0, 5);
	expect(window[64]).toBeCloseTo(0, 5);
	expect(window[32]).toBeCloseTo(1, 5);
});

test('spectrumAt reads from the requested offset', () => {
	const samples = sine(8192, 440, 44100);
	const magnitudes = spectrumAt(samples, 4096, 2048);
	expect(magnitudes).toHaveLength(1024);
	expect(Math.max(...magnitudes)).toBeGreaterThan(0.1);
});

test('binForFrequency maps hz to bins', () => {
	expect(binForFrequency(1000, 44100, 44100)).toBe(1000);
});
