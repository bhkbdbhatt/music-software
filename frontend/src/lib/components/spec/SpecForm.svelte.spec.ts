import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import SpecForm from './SpecForm.svelte';
import { defaultSpec } from '#lib/spec/spec.js';

test('shows a beat-length field only for loops', async () => {
	const screen = await render(SpecForm, { spec: defaultSpec() });
	await expect.element(screen.getByLabelText('Duration', { exact: true })).toBeVisible();
	await screen.getByLabelText('Type').selectOptions('loop');
	await expect.element(screen.getByLabelText('Length')).toBeVisible();
});

test('surfaces validation errors from the spec', async () => {
	const spec = { ...defaultSpec(), spectral_floor_hz: 500 };
	const screen = await render(SpecForm, { spec });
	await expect.element(screen.getByText(/Floor must sit below/)).toBeVisible();
});

test('toggles advanced tolerances', async () => {
	const screen = await render(SpecForm, { spec: defaultSpec() });
	const summary = screen.getByText('Verification tolerances');
	await summary.click();
	await expect.element(screen.getByLabelText('Pitch slack')).toBeVisible();
});
