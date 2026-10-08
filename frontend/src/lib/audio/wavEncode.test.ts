import { expect, test } from 'vitest';
import { encodeWav, wavDataUri } from './wavEncode.js';

test('encodes a valid 16-bit PCM WAV header', () => {
	const buffer = encodeWav(new Float32Array(1000), 44100);
	const view = new DataView(buffer);
	const tag = (offset: number, length: number) =>
		String.fromCharCode(...new Uint8Array(buffer, offset, length));
	expect(tag(0, 4)).toBe('RIFF');
	expect(tag(8, 4)).toBe('WAVE');
	expect(tag(12, 4)).toBe('fmt ');
	expect(view.getUint16(20, true)).toBe(1);
	expect(view.getUint32(24, true)).toBe(44100);
	expect(view.getUint32(40, true)).toBe(2000);
	expect(buffer.byteLength).toBe(44 + 2000);
});

test('produces a data URI that round-trips to base64', () => {
	const uri = wavDataUri(new Float32Array(10), 44100);
	expect(uri.startsWith('data:audio/wav;base64,')).toBe(true);
	expect(atob(uri.split(',')[1]).length).toBe(44 + 20);
});
