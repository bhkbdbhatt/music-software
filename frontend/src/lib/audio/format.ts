/** Compact time label: `1:02.3`, `0:04.2`, or `12:03.4` for long audio. */
export function formatTime(ms: number): string {
	if (!Number.isFinite(ms) || ms < 0) return '0:00';
	const totalTenths = Math.round(ms / 100);
	const minutes = Math.floor(totalTenths / 600);
	const withinMinute = totalTenths % 600;
	const seconds = Math.floor(withinMinute / 10);
	const tenths = withinMinute % 10;
	return `${minutes}:${String(seconds).padStart(2, '0')}.${tenths}`;
}

/** Frequency label with sensible units: 40 Hz, 1.2 kHz, 12 kHz. */
export function formatHz(hz: number): string {
	if (hz >= 1000) {
		const kHz = hz / 1000;
		return `${Number.isInteger(kHz) ? kHz : kHz.toFixed(1)} kHz`;
	}
	return `${Math.round(hz)} Hz`;
}
