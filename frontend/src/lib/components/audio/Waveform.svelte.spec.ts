import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Waveform from './Waveform.svelte';
import { computePeaks } from '#lib/audio/peaks.js';

function tonePeaks() {
	const samples = new Float32Array(44100);
	for (let i = 0; i < samples.length; i++) samples[i] = Math.sin(i / 40) * 0.8;
	return computePeaks(samples, 300);
}

test('renders a waveform canvas', async () => {
	const screen = await render(Waveform, {
		peaks: tonePeaks(),
		durationMs: 1000,
		progressMs: 250
	});
	await expect.element(screen.getByRole('img', { name: 'Waveform' })).toBeVisible();
});

test('seeks to the clicked position', async () => {
	const onseek = vi.fn();
	const screen = await render(Waveform, {
		peaks: tonePeaks(),
		durationMs: 1000,
		onseek
	});
	await screen.getByRole('img', { name: 'Waveform' }).click();
	expect(onseek).toHaveBeenCalledTimes(1);
	const [ms] = onseek.mock.calls[0];
	expect(ms).toBeGreaterThanOrEqual(0);
	expect(ms).toBeLessThanOrEqual(1000);
});
