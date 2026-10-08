import { expect, test } from 'vitest';
import { PANELS, PANEL_BY_ID, PANEL_IDS, defaultOrder } from './registry.js';
import { emptyContext } from './types.js';

test('every panel id is unique and indexed', () => {
	expect(new Set(PANEL_IDS).size).toBe(PANELS.length);
	for (const panel of PANELS) {
		expect(PANEL_BY_ID[panel.id]).toBe(panel);
		expect(panel.title.length).toBeGreaterThan(0);
		expect(panel.component).toBeTypeOf('function');
		expect(panel.icon).toBeTruthy();
	}
});

test('the default order only contains known panels', () => {
	const order = defaultOrder();
	expect(order.length).toBeGreaterThan(0);
	for (const id of order) {
		expect(PANEL_IDS).toContain(id);
		expect(PANEL_BY_ID[id].defaultVisible).toBe(true);
	}
});

test('panels marked hidden stay out of the default order', () => {
	const order = defaultOrder();
	expect(order).not.toContain('raw');
	expect(order).not.toContain('metadata');
});

test('the empty panel context has no audio or spec', () => {
	const context = emptyContext();
	expect(context.spec).toBeNull();
	expect(context.response).toBeNull();
	expect(context.peaks).toBeNull();
	expect(context.durationMs).toBe(0);
});
