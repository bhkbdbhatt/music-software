import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { createRawSnippet, type Snippet } from 'svelte';
import Button from './Button.svelte';

function text(content: string): Snippet {
	return createRawSnippet(() => ({ render: () => `<span>${content}</span>` }));
}

test('renders its label', async () => {
	const screen = await render(Button, { children: text('Generate') });
	await expect.element(screen.getByRole('button', { name: 'Generate' })).toBeVisible();
});

test('invokes onclick', async () => {
	const onclick = vi.fn();
	const screen = await render(Button, { onclick, children: text('Run') });
	await screen.getByRole('button', { name: 'Run' }).click();
	expect(onclick).toHaveBeenCalledTimes(1);
});

test('does not fire when disabled', async () => {
	const onclick = vi.fn();
	const screen = await render(Button, { disabled: true, onclick, children: text('Run') });
	await screen.getByRole('button', { name: 'Run' }).click({ force: true });
	expect(onclick).not.toHaveBeenCalled();
});

test('marks itself busy while loading', async () => {
	const screen = await render(Button, { loading: true, children: text('Saving') });
	const button = screen.getByRole('button');
	await expect.element(button).toHaveAttribute('aria-busy', 'true');
	await expect.element(button).toBeDisabled();
});
