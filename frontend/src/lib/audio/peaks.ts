export interface Peaks {
	min: Float32Array;
	max: Float32Array;
}

/**
 * Reduce PCM samples to per-bucket min/max envelopes for waveform drawing.
 * One bucket per horizontal pixel; each bucket keeps the extremes so
 * transients survive downsampling.
 */
export function computePeaks(samples: Float32Array, buckets: number): Peaks {
	const count = Math.max(1, Math.floor(buckets));
	const min = new Float32Array(count);
	const max = new Float32Array(count);
	const perBucket = samples.length / count;

	for (let i = 0; i < count; i++) {
		const start = Math.floor(i * perBucket);
		const end = Math.min(samples.length, Math.max(start + 1, Math.floor((i + 1) * perBucket)));
		let lo = Infinity;
		let hi = -Infinity;
		for (let j = start; j < end; j++) {
			const value = samples[j];
			if (value < lo) lo = value;
			if (value > hi) hi = value;
		}
		min[i] = lo === Infinity ? 0 : lo;
		max[i] = hi === -Infinity ? 0 : hi;
	}
	return { min, max };
}

/** Average peaks across channels (channel data arrays of equal length). */
export function mixPeaks(channels: Float32Array[], buckets: number): Peaks {
	if (channels.length === 0)
		return { min: new Float32Array(buckets), max: new Float32Array(buckets) };
	if (channels.length === 1) return computePeaks(channels[0], buckets);

	const mixed = new Float32Array(channels[0].length);
	for (const channel of channels) {
		for (let i = 0; i < mixed.length; i++) mixed[i] += channel[i];
	}
	for (let i = 0; i < mixed.length; i++) mixed[i] /= channels.length;
	return computePeaks(mixed, buckets);
}

/** Peak envelope from an AudioBuffer's channels. */
export function peaksFromBuffer(buffer: AudioBuffer, buckets: number): Peaks {
	const channels: Float32Array[] = [];
	for (let c = 0; c < buffer.numberOfChannels; c++) channels.push(buffer.getChannelData(c));
	return mixPeaks(channels, buckets);
}
