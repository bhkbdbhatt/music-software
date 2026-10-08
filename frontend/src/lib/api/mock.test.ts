import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockFetch, resetMock } from './mock.js';
import { defaultSpec } from '../spec/spec.js';
import type { BatchProgressResponse, GenerationResponse, JobList } from './types.js';

async function call(path: string, init: RequestInit = {}): Promise<Response> {
	const pending = mockFetch(path, init);
	await vi.advanceTimersByTimeAsync(250);
	return pending;
}

async function getJson<T>(path: string): Promise<{ status: number; body: T }> {
	const response = await call(path);
	return { status: response.status, body: (await response.json()) as T };
}

async function postJson<T>(path: string, body?: unknown): Promise<{ status: number; body: T }> {
	const init: RequestInit =
		body === undefined ? { method: 'POST' } : { method: 'POST', body: JSON.stringify(body) };
	const response = await call(path, init);
	return { status: response.status, body: (await response.json()) as T };
}

async function putJson<T>(path: string, body: unknown): Promise<{ status: number; body: T }> {
	const response = await call(path, { method: 'PUT', body: JSON.stringify(body) });
	return { status: response.status, body: (await response.json()) as T };
}

async function advanceToComplete(): Promise<void> {
	await vi.advanceTimersByTimeAsync(3_000);
}

describe('mock API', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		resetMock();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('serves a health report', async () => {
		const { status, body } = await getJson<{ status: string; version: string }>('/v1/health');
		expect(status).toBe(200);
		expect(body.status).toBe('ok');
		expect(body.version).toBe('mock');
	});

	it('moves a generated job from queued to processing to complete', async () => {
		const submit = await postJson<{ job_id: string; status: string; poll_url: string }>(
			'/v1/generate',
			defaultSpec()
		);
		expect(submit.status).toBe(202);
		expect(submit.body.status).toBe('queued');
		expect(submit.body.poll_url).toBe(`/v1/jobs/${submit.body.job_id}`);

		const queued = await getJson<GenerationResponse>(`/v1/jobs/${submit.body.job_id}`);
		expect(queued.body.status).toBe('queued');

		await vi.advanceTimersByTimeAsync(600);
		const processing = await getJson<GenerationResponse>(`/v1/jobs/${submit.body.job_id}`);
		expect(processing.body.status).toBe('processing');

		await advanceToComplete();
		const done = await getJson<GenerationResponse>(`/v1/jobs/${submit.body.job_id}`);
		expect(['complete', 'complete_with_warnings']).toContain(done.body.status);
		const file = done.body.files?.[0];
		expect(file?.url.startsWith('data:audio/wav')).toBe(true);
		expect(file?.spectral_analysis).toBeDefined();
		expect(typeof done.body.constraints_met?.fundamental_hz).toBe('boolean');
	});

	it('rejects invalid specs with 422', async () => {
		const invalid = { ...defaultSpec(), duration_ms: 0 };
		const { status, body } = await postJson<{ detail: string }>('/v1/generate', invalid);
		expect(status).toBe(422);
		expect(body.detail).toContain('duration_ms');
	});

	it('lists jobs newest first with limit, offset, and status filter', async () => {
		const page = await getJson<JobList>('/v1/jobs?limit=2');
		expect(page.status).toBe(200);
		expect(page.body.items).toHaveLength(2);
		expect(page.body.total).toBe(7);
		expect(page.body.limit).toBe(2);

		await postJson('/v1/generate', defaultSpec());
		const queued = await getJson<JobList>('/v1/jobs?status=queued');
		expect(queued.body.items?.every((item) => item.status === 'queued')).toBe(true);
		expect(queued.body.total).toBe(1);
	});

	it('404s on an unknown job', async () => {
		const { status, body } = await getJson<{ detail: string }>('/v1/jobs/job-9999');
		expect(status).toBe(404);
		expect(body.detail).toBe('Job not found.');
	});

	it('submits and tracks a batch', async () => {
		const submit = await postJson<{ batch_id: string; total_jobs: number; poll_url: string }>(
			'/v1/batch',
			{ specs: [defaultSpec(), defaultSpec()] }
		);
		expect(submit.status).toBe(202);
		expect(submit.body.total_jobs).toBe(2);
		expect(submit.body.poll_url).toBe(`/v1/batches/${submit.body.batch_id}`);

		await advanceToComplete();
		const progress = await getJson<BatchProgressResponse>(`/v1/batches/${submit.body.batch_id}`);
		expect(progress.body.total).toBe(2);
		expect(progress.body.completed).toBe(2);
		expect(progress.body.failed).toBe(0);
		expect(progress.body.results).toHaveLength(2);

		const list = await getJson<{ total: number }>('/v1/batches');
		expect(list.body.total).toBe(2);
	});

	it('404s on an unknown batch', async () => {
		const { status } = await getJson('/v1/batches/batch-9999');
		expect(status).toBe(404);
	});

	it('seeds two recipes and supports CRUD plus run', async () => {
		const seeded = await getJson<{ items: Array<{ name: string }>; total: number }>('/v1/recipes');
		expect(seeded.body.total).toBe(2);
		expect(seeded.body.items.map((recipe) => recipe.name)).toContain('kick_909');

		const created = await postJson<{ id: string; name: string }>('/v1/recipes', {
			name: 'sub_bass',
			description: 'Deep sub for drops.',
			spec: defaultSpec()
		});
		expect(created.status).toBe(201);

		const duplicate = await postJson<{ detail: string }>('/v1/recipes', {
			name: 'sub_bass',
			spec: defaultSpec()
		});
		expect(duplicate.status).toBe(409);

		const updated = await putJson<{ description: string }>(`/v1/recipes/${created.body.id}`, {
			description: 'Revised.'
		});
		expect(updated.status).toBe(200);
		expect(updated.body.description).toBe('Revised.');

		const run = await postJson<{ job_id: string; status: string }>(
			`/v1/recipes/${created.body.id}/run`
		);
		expect(run.status).toBe(202);
		expect(run.body.status).toBe('queued');

		const missing = await postJson('/v1/recipes/recipe-9999/run');
		expect(missing.status).toBe(404);
	});

	it('validates recipe creation input', async () => {
		const { status } = await postJson('/v1/recipes', { spec: defaultSpec() });
		expect(status).toBe(422);
	});

	it('resetMock restores the seed data', async () => {
		await postJson('/v1/generate', defaultSpec());
		const inflated = await getJson<JobList>('/v1/jobs');
		expect(inflated.body.total).toBe(8);

		resetMock();
		const seeded = await getJson<JobList>('/v1/jobs');
		expect(seeded.body.total).toBe(7);
	});
});
