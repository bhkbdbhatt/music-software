/**
 * In-place iterative radix-2 FFT. `real`/`imag` must be equal powers of two.
 * Returns magnitude spectrum (linear amplitude) of length N/2.
 */
export function fftMagnitudes(real: Float32Array, imag: Float32Array): Float32Array {
	const n = real.length;
	if (n !== imag.length || (n & (n - 1)) !== 0) {
		throw new Error(`fftMagnitudes expects equal power-of-two arrays, got ${n}`);
	}

	for (let i = 1, j = 0; i < n; i++) {
		let bit = n >> 1;
		for (; j & bit; bit >>= 1) j ^= bit;
		j ^= bit;
		if (i < j) {
			[real[i], real[j]] = [real[j], real[i]];
			[imag[i], imag[j]] = [imag[j], imag[i]];
		}
	}

	for (let len = 2; len <= n; len <<= 1) {
		const angle = (-2 * Math.PI) / len;
		const wLenR = Math.cos(angle);
		const wLenI = Math.sin(angle);
		for (let i = 0; i < n; i += len) {
			let wR = 1;
			let wI = 0;
			for (let j = 0; j < len / 2; j++) {
				const uR = real[i + j];
				const uI = imag[i + j];
				const vR = real[i + j + len / 2] * wR - imag[i + j + len / 2] * wI;
				const vI = real[i + j + len / 2] * wI + imag[i + j + len / 2] * wR;
				real[i + j] = uR + vR;
				imag[i + j] = uI + vI;
				real[i + j + len / 2] = uR - vR;
				imag[i + j + len / 2] = uI - vI;
				const nextR = wR * wLenR - wI * wLenI;
				wI = wR * wLenI + wI * wLenR;
				wR = nextR;
			}
		}
	}

	const magnitudes = new Float32Array(n / 2);
	for (let i = 0; i < n / 2; i++) {
		magnitudes[i] = Math.hypot(real[i], imag[i]) / (n / 2);
	}
	return magnitudes;
}

export function hannWindow(length: number): Float32Array {
	const window = new Float32Array(length);
	for (let i = 0; i < length; i++) {
		window[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (length - 1)));
	}
	return window;
}

/**
 * Magnitude spectrum of one channel, windowed with Hann, over `fftSize`
 * samples starting at `offset`. Result length = fftSize / 2.
 */
export function spectrumAt(samples: Float32Array, offset: number, fftSize = 2048): Float32Array {
	const real = new Float32Array(fftSize);
	const imag = new Float32Array(fftSize);
	const window = hannWindow(fftSize);
	const usable = Math.min(fftSize, Math.max(0, samples.length - offset));
	for (let i = 0; i < usable; i++) {
		real[i] = samples[offset + i] * window[i];
	}
	return fftMagnitudes(real, imag);
}

/** Bin index (of an fftSize transform) for a frequency. */
export function binForFrequency(frequency: number, sampleRate: number, fftSize: number): number {
	return Math.round((frequency * fftSize) / sampleRate);
}
