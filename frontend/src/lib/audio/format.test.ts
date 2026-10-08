import { expect, test } from 'vitest';
import { formatHz, formatTime } from './format.js';

test('formats milliseconds as m:ss.t', () => {
	expect(formatTime(0)).toBe('0:00.0');
	expect(formatTime(4200)).toBe('0:04.2');
	expect(formatTime(62300)).toBe('1:02.3');
	expect(formatTime(-5)).toBe('0:00');
});

test('formats frequencies with unit prefixes', () => {
	expect(formatHz(40)).toBe('40 Hz');
	expect(formatHz(1000)).toBe('1 kHz');
	expect(formatHz(1200)).toBe('1.2 kHz');
	expect(formatHz(12000)).toBe('12 kHz');
});
