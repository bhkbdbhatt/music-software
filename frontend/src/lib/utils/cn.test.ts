import { expect, test } from 'vitest';
import { cn } from './cn.js';

test('merges conflicting tailwind classes, last wins', () => {
	expect(cn('p-2', 'p-4')).toBe('p-4');
});

test('joins conditional classes', () => {
	const hidden = false;
	expect(cn('btn', hidden && 'hidden', 'primary')).toBe('btn primary');
});
