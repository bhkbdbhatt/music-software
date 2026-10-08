import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import WorkspaceGrid from './WorkspaceGrid.svelte';
import { defaultOrder } from './registry.js';
import { emptyContext } from './types.js';

test('renders one card per default panel', async () => {
	const screen = await render(WorkspaceGrid, { props: { context: emptyContext() } });
	for (const title of ['Player', 'Waveform', 'Spectrum', 'Verdicts']) {
		await expect.element(screen.getByText(title, { exact: true })).toBeVisible();
	}
	expect(defaultOrder()).toHaveLength(5);
});

test('hides a panel and restores it from the picker', async () => {
	const screen = await render(WorkspaceGrid, { props: { context: emptyContext() } });
	const text = () => screen.container.textContent ?? '';
	await screen.getByRole('button', { name: 'Hide Player' }).click();
	await expect.poll(() => text()).not.toContain('Player');
	await screen.getByRole('button', { name: /Panels/ }).click();
	await screen.getByRole('switch', { name: 'Show Player' }).click();
	await screen.getByRole('button', { name: 'Close dialog' }).click();
	await expect.element(screen.getByText('Player', { exact: true })).toBeVisible();
});
