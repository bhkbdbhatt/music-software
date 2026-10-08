import { mixPeaks, peaksFromBuffer, type Peaks } from './peaks.js';

let sharedContext: AudioContext | undefined;

function audioContext(): AudioContext {
	sharedContext ??= new AudioContext();
	return sharedContext;
}

export async function decodeAudioUrl(url: string): Promise<AudioBuffer> {
	const response = await fetch(url);
	if (!response.ok) {
		throw new Error(`Failed to fetch audio (${response.status}): ${url}`);
	}
	const data = await response.arrayBuffer();
	return audioContext().decodeAudioData(data);
}

export interface LoadedAudio {
	buffer: AudioBuffer;
	peaks: Peaks;
	durationMs: number;
	sampleRate: number;
}

/**
 * Fetch, decode and reduce a URL to a waveform peak envelope.
 * Decoding happens once per call; pages should hoist the result and pass
 * it down instead of letting every player re-fetch.
 */
export async function loadAudio(url: string, buckets: number): Promise<LoadedAudio> {
	const buffer = await decodeAudioUrl(url);
	return {
		buffer,
		peaks: peaksFromBuffer(buffer, buckets),
		durationMs: buffer.duration * 1000,
		sampleRate: buffer.sampleRate
	};
}

/** Peaks for a URL without keeping the decoded buffer around. */
export async function loadPeaks(url: string, buckets: number): Promise<Peaks> {
	const buffer = await decodeAudioUrl(url);
	return mixPeaks([buffer.getChannelData(0)], buckets);
}
