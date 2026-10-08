import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Player from './Player.svelte';
import { computePeaks } from '#lib/audio/peaks.js';
import { wavDataUri } from '#lib/audio/wavEncode.js';

function tone(durationSeconds: number): { src: string; peaks: ReturnType<typeof computePeaks> } {
	const sampleRate = 44100;
	const samples = new Float32Array(Math.floor(sampleRate * durationSeconds));
	for (let i = 0; i < samples.length; i++) {
		samples[i] = Math.sin((2 * Math.PI * 440 * i) / sampleRate) * 0.5;
	}
	return { src: wavDataUri(samples, sampleRate), peaks: computePeaks(samples, 300) };
}

test('renders transport and starts playback', async () => {
	const { src, peaks } = tone(0.3);
	const screen = await render(Player, { src, peaks, durationMs: 300 });
	const play = screen.getByRole('button', { name: 'Play' });
	await expect.element(play).toBeVisible();
	await play.click();
	await expect.element(screen.getByRole('button', { name: 'Pause' })).toBeVisible();
});
