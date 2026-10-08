import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	ApiError,
	DEFAULT_API_KEY,
	PROXY_BASE,
	api,
	errorMessage,
	getApiKey,
	setApiKey
} from './client.js';
import { defaultSpec } from '../spec/spec.js';

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

describe('api client', () => {
	let fetchMock: ReturnType<typeof vi.fn>;
	let storage: Map<string, string>;

	beforeEach(() => {
		fetchMock = vi.fn(async () => jsonResponse({ status: 'ok' }));
		vi.stubGlobal('fetch', fetchMock);
		storage = new Map<string, string>();
		vi.stubGlobal('localStorage', {
			getItem: (key: string) => storage.get(key) ?? null,
			setItem: (key: string, value: string) => {
				storage.set(key, value);
			}
		});
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('routes requests through the proxy with the API key', async () => {
		await api.health();

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(url).toBe(`${PROXY_BASE}/v1/health`);
		expect(init.method).toBe('GET');
		expect(new Headers(init.headers).get('X-API-Key')).toBe(DEFAULT_API_KEY);
		expect(init.signal).toBeInstanceOf(AbortSignal);
	});

	it('serializes query parameters and skips empty values', async () => {
		await api.listJobs({ limit: 10, offset: 20, status: 'complete' });
		await api.listJobs({ limit: undefined, offset: 0, status: null });

		const first = (fetchMock.mock.calls[0] as [string, RequestInit])[0];
		const second = (fetchMock.mock.calls[1] as [string, RequestInit])[0];
		expect(first).toBe(`${PROXY_BASE}/v1/jobs?limit=10&offset=20&status=complete`);
		expect(second).toBe(`${PROXY_BASE}/v1/jobs?offset=0`);
	});

	it('serializes the spec body with a JSON content type', async () => {
		const spec = defaultSpec();
		await api.generate(spec);

		const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(init.method).toBe('POST');
		expect(init.body).toBe(JSON.stringify(spec));
		expect(new Headers(init.headers).get('content-type')).toBe('application/json');
	});

	it('throws ApiError carrying status and detail message', async () => {
		fetchMock.mockImplementation(async () => jsonResponse({ detail: 'model cold' }, 503));

		const error = await api.health().catch((caught: unknown) => caught);
		expect(error).toBeInstanceOf(ApiError);
		const apiError = error as ApiError;
		expect(apiError.status).toBe(503);
		expect(apiError.message).toBe('model cold');
	});

	it('joins array-shaped validation detail into one message', async () => {
		fetchMock.mockImplementation(async () =>
			jsonResponse({ detail: [{ msg: 'duration too short' }, { msg: 'pitch out of range' }] }, 422)
		);

		const error = (await api.health().catch((caught: unknown) => caught)) as ApiError;
		expect(error.message).toBe('duration too short; pitch out of range');
	});

	it('builds file URLs against the unauthenticated files route', () => {
		expect(api.fileUrl('job-0042', 2)).toBe(`${PROXY_BASE}/v1/files/job-0042/2`);
	});

	it('persists the API key and falls back to the default', () => {
		expect(getApiKey()).toBe(DEFAULT_API_KEY);
		setApiKey('secret-123');
		expect(getApiKey()).toBe('secret-123');
	});
});

describe('errorMessage', () => {
	it('unwraps ApiError, Error, and unknown values', () => {
		expect(errorMessage(new ApiError(404, 'gone'))).toBe('gone');
		expect(errorMessage(new Error('boom'))).toBe('boom');
		expect(errorMessage('nope')).toBe('Something went wrong');
	});
});
