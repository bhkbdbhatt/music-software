import type { JobStatus } from './types.js';

export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

const TONES: Record<JobStatus, StatusTone> = {
	queued: 'neutral',
	processing: 'info',
	complete: 'success',
	complete_with_warnings: 'warning',
	failed: 'danger'
};

const LABELS: Record<JobStatus, string> = {
	queued: 'Queued',
	processing: 'Processing',
	complete: 'Complete',
	complete_with_warnings: 'Warnings',
	failed: 'Failed'
};

export function statusTone(status: JobStatus): StatusTone {
	return TONES[status];
}

export function statusLabel(status: JobStatus): string {
	return LABELS[status];
}

export function isActiveStatus(status: JobStatus): boolean {
	return status === 'queued' || status === 'processing';
}

export function isTerminalStatus(status: JobStatus): boolean {
	return !isActiveStatus(status);
}
