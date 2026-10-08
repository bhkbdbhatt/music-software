import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Toggle from './Toggle.svelte';

test('is a switch that toggles on click', async () => {
	const screen = await render(Toggle, { 'aria-label': 'Normalize' });
	const toggle = screen.getByRole('switch', { name: 'Normalize' });
	await expect.element(toggle).toHaveAttribute('aria-checked', 'false');
	await toggle.click();
	await expect.element(toggle).toHaveAttribute('aria-checked', 'true');
	await toggle.click();
	await expect.element(toggle).toHaveAttribute('aria-checked', 'false');
});

test('reports changes through onchange', async () => {
	const onchange = vi.fn();
	const screen = await render(Toggle, { 'aria-label': 'Limit', onchange });
	await screen.getByRole('switch').click();
	expect(onchange).toHaveBeenCalledWith(true);
});
