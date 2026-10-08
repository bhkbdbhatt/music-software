import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { createRawSnippet, type Snippet } from 'svelte';
import Modal from './Modal.svelte';

function props(onclose: () => void): {
	open: boolean;
	title: string;
	onclose: () => void;
	children: Snippet;
} {
	return {
		open: true,
		title: 'Delete recipe',
		onclose,
		children: createRawSnippet(() => ({ render: () => '<p>This cannot be undone.</p>' }))
	};
}

test('renders a dialog when open', async () => {
	const screen = await render(Modal, props(vi.fn()));
	await expect.element(screen.getByRole('dialog', { name: 'Delete recipe' })).toBeVisible();
	await expect.element(screen.getByText('This cannot be undone.')).toBeVisible();
});

test('closes on Escape', async () => {
	const onclose = vi.fn();
	await render(Modal, props(onclose));
	document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
	expect(onclose).toHaveBeenCalled();
});

test('closes when the close button is clicked', async () => {
	const onclose = vi.fn();
	const screen = await render(Modal, props(onclose));
	await screen.getByRole('button', { name: 'Close dialog' }).click();
	expect(onclose).toHaveBeenCalled();
});
