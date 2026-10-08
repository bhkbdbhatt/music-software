import { VITE_MOCK_API } from '$app/env/public';
import { mockFetch } from './mock.js';
import type {
	BatchList,
	BatchOptions,
	BatchProgressResponse,
	BatchSubmitResponse,
	GenerationResponse,
	GenerationSpec,
	HealthResponse,
	JobList,
	JobStatus,
	JobSubmitResponse,
	RecipeCreate,
	RecipeList,
	RecipeRead,
	RecipeRunResponse,
	RecipeUpdate
} from './types.js';

export const PROXY_BASE = '/api/proxy';
export const DEFAULT_API_KEY = 'dev-key-change-me';
const API_KEY_STORAGE = 'sf-api-key';
const TIMEOUT_MS = 15_000;

type Query = Record<string, string | number | null | undefined>;

export class ApiError extends Error {
	readonly status: number;
	readonly body: unknown;

	constructor(status: number, message: string, body?: unknown) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.body = body;
	}
}

export function getApiKey(): string {
	try {
		return localStorage.getItem(API_KEY_STORAGE) ?? DEFAULT_API_KEY;
	} catch {
		return DEFAULT_API_KEY;
	}
}

export function setApiKey(key: string): void {
	try {
		localStorage.setItem(API_KEY_STORAGE, key);
	} catch {
		// Storage unavailable (private mode); the key just will not persist.
	}
}

export function errorMessage(error: unknown): string {
	if (error instanceof ApiError) return error.message;
	if (error instanceof Error) return error.message;
	return 'Something went wrong';
}

function buildUrl(path: string, query?: Query): string {
	if (!query) return path;
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(query)) {
		if (value === undefined || value === null || value === '') continue;
		params.set(key, String(value));
	}
	const search = params.toString();
	return search ? `${path}?${search}` : path;
}

function formatDetail(detail: unknown): string | null {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail)) {
		const messages = detail
			.map((entry) =>
				typeof entry === 'object' && entry !== null && 'msg' in entry
					? String((entry as { msg: unknown }).msg)
					: String(entry)
			)
			.filter((message) => message.length > 0);
		if (messages.length > 0) return messages.join('; ');
	}
	return null;
}

async function toApiError(response: Response): Promise<ApiError> {
	let body: unknown = null;
	try {
		body = await response.json();
	} catch {
		// Non-JSON error body; fall back to the status text.
	}
	const detail =
		body && typeof body === 'object' && 'detail' in body
			? formatDetail((body as { detail: unknown }).detail)
			: null;
	return new ApiError(response.status, detail ?? response.statusText ?? 'Request failed', body);
}

async function realFetch(path: string, init: RequestInit): Promise<Response> {
	const headers = new Headers(init.headers);
	headers.set('X-API-Key', getApiKey());
	return fetch(PROXY_BASE + path, {
		...init,
		headers,
		signal: init.signal ?? AbortSignal.timeout(TIMEOUT_MS)
	});
}

async function request<T>(
	method: string,
	path: string,
	options: { body?: unknown; query?: Query } = {}
): Promise<T> {
	const url = buildUrl(path, options.query);
	const init: RequestInit = { method };
	if (options.body !== undefined) {
		init.body = JSON.stringify(options.body);
		init.headers = { 'content-type': 'application/json' };
	}
	const response = await (VITE_MOCK_API ? mockFetch : realFetch)(url, init);
	if (!response.ok) throw await toApiError(response);
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

export interface ListParams {
	limit?: number;
	offset?: number;
}

export interface JobListParams extends ListParams {
	status?: JobStatus | null;
}

export const api = {
	health: () => request<HealthResponse>('GET', '/v1/health'),

	generate: (spec: GenerationSpec) =>
		request<JobSubmitResponse>('POST', '/v1/generate', { body: spec }),

	getJob: (jobId: string) => request<GenerationResponse>('GET', `/v1/jobs/${jobId}`),

	listJobs: (params: JobListParams = {}) =>
		request<JobList>('GET', '/v1/jobs', {
			query: { limit: params.limit, offset: params.offset, status: params.status }
		}),

	submitBatch: (specs: GenerationSpec[], options?: BatchOptions) =>
		request<BatchSubmitResponse>('POST', '/v1/batch', {
			body: options ? { specs, options } : { specs }
		}),

	getBatch: (batchId: string) => request<BatchProgressResponse>('GET', `/v1/batches/${batchId}`),

	listBatches: (params: ListParams = {}) =>
		request<BatchList>('GET', '/v1/batches', {
			query: { limit: params.limit, offset: params.offset }
		}),

	listRecipes: (params: ListParams = {}) =>
		request<RecipeList>('GET', '/v1/recipes', {
			query: { limit: params.limit, offset: params.offset }
		}),

	getRecipe: (recipeId: string) => request<RecipeRead>('GET', `/v1/recipes/${recipeId}`),

	createRecipe: (payload: RecipeCreate) =>
		request<RecipeRead>('POST', '/v1/recipes', { body: payload }),

	updateRecipe: (recipeId: string, payload: RecipeUpdate) =>
		request<RecipeRead>('PUT', `/v1/recipes/${recipeId}`, { body: payload }),

	runRecipe: (recipeId: string) =>
		request<RecipeRunResponse>('POST', `/v1/recipes/${recipeId}/run`),

	fileUrl: (jobId: string, variant: number) => `${PROXY_BASE}/v1/files/${jobId}/${variant}`
};
