import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Tabs from './Tabs.svelte';

const TABS = [
	{ id: 'audio', label: 'Audio' },
	{ id: 'spec', label: 'Spec' },
	{ id: 'raw', label: 'Raw' }
];

test('selects the first tab by default', async () => {
	const screen = await render(Tabs, { tabs: TABS });
	await expect
		.element(screen.getByRole('tab', { name: 'Audio' }))
		.toHaveAttribute('aria-selected', 'true');
	await expect
		.element(screen.getByRole('tab', { name: 'Spec' }))
		.toHaveAttribute('aria-selected', 'false');
});

test('switches tabs on click', async () => {
	const screen = await render(Tabs, { tabs: TABS });
	await screen.getByRole('tab', { name: 'Raw' }).click();
	await expect
		.element(screen.getByRole('tab', { name: 'Raw' }))
		.toHaveAttribute('aria-selected', 'true');
	await expect
		.element(screen.getByRole('tab', { name: 'Audio' }))
		.toHaveAttribute('aria-selected', 'false');
});
