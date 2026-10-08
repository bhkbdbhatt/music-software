/**
 * Minimal 16-bit PCM WAV encoder — used by mock mode to synthesize playable
 * samples in the browser without touching the backend.
 */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
	const bytesPerSample = 2;
	const blockAlign = bytesPerSample; // mono
	const dataSize = samples.length * bytesPerSample;
	const buffer = new ArrayBuffer(44 + dataSize);
	const view = new DataView(buffer);

	function writeString(offset: number, text: string): void {
		for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
	}

	writeString(0, 'RIFF');
	view.setUint32(4, 36 + dataSize, true);
	writeString(8, 'WAVE');
	writeString(12, 'fmt ');
	view.setUint32(16, 16, true);
	view.setUint16(20, 1, true); // PCM
	view.setUint16(22, 1, true); // mono
	view.setUint32(24, sampleRate, true);
	view.setUint32(28, sampleRate * blockAlign, true);
	view.setUint16(32, blockAlign, true);
	view.setUint16(34, 16, true);
	writeString(36, 'data');
	view.setUint32(40, dataSize, true);

	let offset = 44;
	for (const sample of samples) {
		const clamped = Math.max(-1, Math.min(1, sample));
		view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
		offset += bytesPerSample;
	}
	return buffer;
}

export function wavDataUri(samples: Float32Array, sampleRate: number): string {
	const bytes = new Uint8Array(encodeWav(samples, sampleRate));
	let binary = '';
	for (const byte of bytes) binary += String.fromCharCode(byte);
	return `data:audio/wav;base64,${btoa(binary)}`;
}
