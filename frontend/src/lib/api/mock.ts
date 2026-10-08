import { wavDataUri } from '#lib/audio/wavEncode.js';
import {
	defaultSpec,
	defaultTolerances,
	effectiveDurationMs,
	validateSpec
} from '#lib/spec/spec.js';
import type {
	BatchOptions,
	BatchProgressResponse,
	GenerationResponse,
	GeneratedFile,
	GenerationSpec,
	HealthResponse,
	JobList,
	JobListItem,
	JobStatus,
	JobSubmitResponse,
	RecipeList,
	RecipeRead,
	SpectralAnalysis
} from './types.js';

const LATENCY_MS = 150;
const QUEUED_MS = 500;
const PROCESSING_MS = 2_000;
const MAX_RENDER_MS = 2_500;
const SAMPLE_RATE = 44_100;

interface MockJob {
	id: string;
	spec: GenerationSpec;
	submittedAt: number;
	batchId?: string;
	recipeId?: string;
	forcedStatus?: JobStatus;
}

interface MockBatch {
	id: string;
	jobIds: string[];
	submittedAt: number;
	options: BatchOptions;
}

let jobCounter = 0;
let jobs = new Map<string, MockJob>();
let batches = new Map<string, MockBatch>();
let recipes: RecipeRead[] = [];

function hashString(value: string): number {
	let hash = 2166136261;
	for (let index = 0; index < value.length; index += 1) {
		hash ^= value.charCodeAt(index);
		hash = Math.imul(hash, 16777619);
	}
	return hash >>> 0;
}

function misses(id: string, key: string): boolean {
	return hashString(`${id}:${key}`) % 13 === 0;
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function json(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

function errorResponse(status: number, detail: string): Response {
	return json({ detail }, status);
}

function isTerminal(status: JobStatus): boolean {
	return status === 'complete' || status === 'complete_with_warnings' || status === 'failed';
}

function statusAt(job: MockJob): JobStatus {
	if (job.forcedStatus) return job.forcedStatus;
	const elapsed = Date.now() - job.submittedAt;
	if (elapsed < QUEUED_MS) return 'queued';
	if (elapsed < QUEUED_MS + PROCESSING_MS) return 'processing';
	return 'complete';
}

function analyse(spec: GenerationSpec, jobId: string): SpectralAnalysis {
	const [minHz, maxHz] = spec.fundamental_hz;
	const fundamentalInside = !misses(jobId, 'fundamental_hz');
	const fundamentalDetected = fundamentalInside
		? minHz + ((hashString(`${jobId}:f`) >>> 0) % Math.max(1, Math.round(maxHz - minHz)))
		: maxHz + 10;
	const ceilingClean = !misses(jobId, 'spectral_ceiling_hz');
	const floorSteep = !misses(jobId, 'spectral_floor_hz');
	const tiltOnTarget = !misses(jobId, 'spectral_tilt_db_per_octave');
	return {
		fundamental_detected_hz: Math.round(fundamentalDetected),
		ceiling_violation_db: ceilingClean ? -72 : 3,
		attack_measured_ms: spec.attack_ms,
		floor_slope_db_per_oct: floorSteep ? -24 : -6,
		tilt_measured_db_per_octave: tiltOnTarget
			? spec.spectral_tilt_db_per_octave
			: spec.spectral_tilt_db_per_octave + 4
	};
}

function evaluateConstraints(
	spec: GenerationSpec,
	analysis: SpectralAnalysis,
	durationMs: number
): Record<string, boolean> {
	const tolerances = spec.tolerances ?? defaultTolerances();
	const constraints: Record<string, boolean> = {};
	const [minHz, maxHz] = spec.fundamental_hz;
	constraints.fundamental_hz =
		analysis.fundamental_detected_hz >= minHz - tolerances.fundamental_hz &&
		analysis.fundamental_detected_hz <= maxHz + tolerances.fundamental_hz;
	constraints.spectral_ceiling_hz =
		analysis.ceiling_violation_db <= tolerances.ceiling_violation_db;
	constraints.spectral_floor_hz =
		analysis.floor_slope_db_per_oct <= tolerances.floor_slope_db_per_oct;
	constraints.spectral_tilt_db_per_octave =
		Math.abs(analysis.tilt_measured_db_per_octave - spec.spectral_tilt_db_per_octave) <=
		tolerances.tilt_db_per_octave;
	constraints.peak_db = true;
	constraints.attack_ms =
		Math.abs(analysis.attack_measured_ms - spec.attack_ms) <= tolerances.attack_ms;
	const target = effectiveDurationMs(spec);
	if (target > 0 && target <= MAX_RENDER_MS) {
		constraints.duration_ms = Math.abs(durationMs - target) / target <= tolerances.duration_pct;
	}
	return constraints;
}

function synthSamples(spec: GenerationSpec): Float32Array {
	const target = effectiveDurationMs(spec);
	const durationMs = Math.min(Math.max(target, 200), MAX_RENDER_MS);
	const length = Math.round((durationMs / 1000) * SAMPLE_RATE);
	const [minHz, maxHz] = spec.fundamental_hz;
	const frequency = (minHz + maxHz) / 2;
	const peak = 10 ** (spec.peak_db / 20);
	const attack = Math.max(1, Math.round((spec.attack_ms / 1000) * SAMPLE_RATE));
	const release = Math.max(1, Math.round((spec.release_ms / 1000) * SAMPLE_RATE));
	const samples = new Float32Array(length);
	for (let index = 0; index < length; index += 1) {
		const time = index / SAMPLE_RATE;
		const oscillator =
			0.7 * Math.sin(2 * Math.PI * frequency * time) +
			0.3 * Math.sin(2 * Math.PI * frequency * 2 * time);
		let envelope = 1;
		if (index < attack) envelope = index / attack;
		if (index > length - release) envelope = Math.min(envelope, (length - index) / release);
		const decay = Math.exp((-3 * time) / (durationMs / 1000));
		samples[index] = peak * envelope * decay * oscillator;
	}
	return samples;
}

function buildFile(spec: GenerationSpec, jobId: string, variant: number): GeneratedFile {
	const variantId = `${jobId}:${variant}`;
	const samples = synthSamples(spec);
	const analysis = analyse(spec, variantId);
	const durationMs = Math.round((samples.length / SAMPLE_RATE) * 1000);
	return {
		url: wavDataUri(samples, SAMPLE_RATE),
		duration_ms: durationMs,
		peak_db: spec.peak_db,
		spectral_analysis: analysis
	};
}

function toResponse(job: MockJob): GenerationResponse {
	const status = statusAt(job);
	const response: GenerationResponse = {
		job_id: job.id,
		status,
		spec: job.spec
	};
	if (status === 'complete' || status === 'complete_with_warnings') {
		const variants = Math.max(1, job.spec.batch_size);
		const files = Array.from({ length: variants }, (_, variant) =>
			buildFile(job.spec, job.id, variant)
		);
		const analysis = files[0]?.spectral_analysis;
		const constraints: Record<string, boolean> = {};
		if (analysis) {
			Object.assign(
				constraints,
				evaluateConstraints(job.spec, analysis, files[0]?.duration_ms ?? 0)
			);
		}
		response.files = files;
		response.constraints_met = constraints;
		if (Object.values(constraints).some((met) => !met)) {
			response.status = 'complete_with_warnings';
		}
	}
	return response;
}

function toListItem(job: MockJob): JobListItem {
	const response = toResponse(job);
	return {
		job_id: response.job_id,
		status: response.status,
		files: response.files,
		constraints_met: response.constraints_met,
		spec: response.spec,
		batch_id: job.batchId ?? null,
		recipe_id: job.recipeId ?? null,
		created_at: new Date(job.submittedAt).toISOString(),
		updated_at: new Date(job.submittedAt + QUEUED_MS + PROCESSING_MS).toISOString()
	};
}

function createJob(spec: GenerationSpec, batchId?: string, recipeId?: string): MockJob {
	jobCounter += 1;
	const job: MockJob = {
		id: `job-${String(jobCounter).padStart(4, '0')}`,
		spec,
		submittedAt: Date.now(),
		batchId,
		recipeId
	};
	jobs.set(job.id, job);
	return job;
}

function submitResponse(job: MockJob): JobSubmitResponse {
	return {
		job_id: job.id,
		status: 'queued',
		poll_url: `/v1/jobs/${job.id}`
	};
}

function validateSpecBody(body: unknown): { spec?: GenerationSpec; error?: string } {
	if (typeof body !== 'object' || body === null) {
		return { error: 'Request body must be a JSON object.' };
	}
	const spec = body as GenerationSpec;
	let errors: Record<string, string>;
	try {
		errors = validateSpec(spec);
	} catch {
		return { error: 'Request body is not a valid GenerationSpec.' };
	}
	if (Object.keys(errors).length > 0) {
		return {
			error: Object.entries(errors)
				.map(([field, message]) => `${field}: ${message}`)
				.join('; ')
		};
	}
	return { spec };
}

function seed(): void {
	const now = Date.now();
	const seedJobs: Array<{
		spec: GenerationSpec;
		submittedAt: number;
		forcedStatus?: JobStatus;
	}> = [
		{ spec: { ...defaultSpec(), category: 'kick' }, submittedAt: now - 60_000 },
		{
			spec: { ...defaultSpec(), category: 'snare', fundamental_hz: [180, 260] },
			submittedAt: now - 120_000
		},
		{
			spec: {
				...defaultSpec(),
				type: 'stinger',
				category: 'riser',
				duration_ms: 4_000,
				fundamental_hz: [220, 880]
			},
			submittedAt: now - 240_000
		},
		{
			spec: { ...defaultSpec(), type: 'texture', category: 'pad' },
			submittedAt: now - 360_000,
			forcedStatus: 'failed'
		}
	];
	for (const { spec, submittedAt, forcedStatus } of seedJobs) {
		jobCounter += 1;
		const id = `job-${String(jobCounter).padStart(4, '0')}`;
		jobs.set(id, { id, spec, submittedAt, forcedStatus });
	}
	const batchJobIds: string[] = [];
	for (let index = 0; index < 3; index += 1) {
		jobCounter += 1;
		const id = `job-${String(jobCounter).padStart(4, '0')}`;
		jobs.set(id, {
			id,
			spec: { ...defaultSpec(), category: 'hihat', diversity: 0.3 + index * 0.2 },
			submittedAt: now - 45_000,
			batchId: 'batch-0001'
		});
		batchJobIds.push(id);
	}
	batches.set('batch-0001', {
		id: 'batch-0001',
		jobIds: batchJobIds,
		submittedAt: now - 45_000,
		options: { parallel: true, max_concurrent: 4, on_failure: 'continue' }
	});
	recipes = [
		{
			id: 'recipe-0001',
			name: 'kick_909',
			description: 'Punchy 909-style kick for techno.',
			spec: { ...defaultSpec(), category: 'kick', fundamental_hz: [40, 70] },
			created_at: new Date(now - 86_400_000).toISOString(),
			updated_at: new Date(now - 86_400_000).toISOString()
		},
		{
			id: 'recipe-0002',
			name: 'dark_pad',
			description: 'Evolving dark texture for breakdowns.',
			spec: {
				...defaultSpec(),
				type: 'texture',
				category: 'pad',
				duration_ms: 6_000,
				fundamental_hz: [110, 220],
				spectral_tilt_db_per_octave: -3
			},
			created_at: new Date(now - 43_200_000).toISOString(),
			updated_at: new Date(now - 43_200_000).toISOString()
		}
	];
}

export function resetMock(): void {
	jobCounter = 0;
	jobs = new Map();
	batches = new Map();
	recipes = [];
	seed();
}

function batchProgress(batch: MockBatch): BatchProgressResponse {
	const results = batch.jobIds
		.map((jobId) => jobs.get(jobId))
		.filter((job): job is MockJob => job !== undefined)
		.map((job) => toResponse(job));
	const terminal = results.filter((result) => isTerminal(result.status));
	return {
		batch_id: batch.id,
		completed: terminal.filter((result) => result.status !== 'failed').length,
		failed: terminal.filter((result) => result.status === 'failed').length,
		total: results.length,
		results
	};
}

async function handle(path: string, init: RequestInit): Promise<Response> {
	const url = new URL(path, 'http://mock.local');
	const method = (init.method ?? 'GET').toUpperCase();
	const body = typeof init.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined;

	if (method === 'GET' && url.pathname === '/v1/health') {
		const health: HealthResponse = {
			status: 'ok',
			model_loaded: false,
			gpu_available: false,
			queue_depth: 0,
			version: 'mock'
		};
		return json(health);
	}

	if (method === 'POST' && url.pathname === '/v1/generate') {
		const { spec, error } = validateSpecBody(body);
		if (!spec) return errorResponse(422, error ?? 'Invalid spec.');
		return json(submitResponse(createJob(spec)), 202);
	}

	if (method === 'GET' && url.pathname === '/v1/jobs') {
		const limit = Number(url.searchParams.get('limit') ?? 50);
		const offset = Number(url.searchParams.get('offset') ?? 0);
		const status = url.searchParams.get('status');
		const all = [...jobs.values()].sort((a, b) => b.submittedAt - a.submittedAt);
		const filtered = all.filter((job) => status === null || statusAt(job) === status);
		const page: JobList = {
			items: filtered.slice(offset, offset + limit).map((job) => toListItem(job)),
			total: filtered.length,
			limit,
			offset
		};
		return json(page);
	}

	const jobMatch = /^\/v1\/jobs\/([^/]+)$/.exec(url.pathname);
	if (method === 'GET' && jobMatch) {
		const job = jobs.get(jobMatch[1] ?? '');
		if (!job) return errorResponse(404, 'Job not found.');
		return json(toResponse(job));
	}

	if (method === 'POST' && url.pathname === '/v1/batch') {
		const specs = (body as { specs?: unknown } | undefined)?.specs;
		if (!Array.isArray(specs) || specs.length === 0) {
			return errorResponse(422, 'specs must be a non-empty array.');
		}
		jobCounter += 1;
		const batchId = `batch-${String(jobCounter).padStart(4, '0')}`;
		const options = ((body as { options?: BatchOptions } | undefined)?.options ?? {
			parallel: true,
			max_concurrent: 4,
			on_failure: 'continue'
		}) satisfies BatchOptions;
		const jobIds: string[] = [];
		for (const candidate of specs) {
			const { spec, error } = validateSpecBody(candidate);
			if (!spec) return errorResponse(422, error ?? 'Invalid spec.');
			jobIds.push(createJob(spec, batchId).id);
		}
		batches.set(batchId, { id: batchId, jobIds, submittedAt: Date.now(), options });
		return json(
			{ batch_id: batchId, total_jobs: jobIds.length, poll_url: `/v1/batches/${batchId}` },
			202
		);
	}

	if (method === 'GET' && url.pathname === '/v1/batches') {
		const limit = Number(url.searchParams.get('limit') ?? 50);
		const offset = Number(url.searchParams.get('offset') ?? 0);
		const all = [...batches.values()].sort((a, b) => b.submittedAt - a.submittedAt);
		const page = {
			items: all.slice(offset, offset + limit).map((batch) => ({
				batch_id: batch.id,
				completed: batchProgress(batch).completed,
				failed: batchProgress(batch).failed,
				total: batch.jobIds.length,
				created_at: new Date(batch.submittedAt).toISOString()
			})),
			total: all.length,
			limit,
			offset
		};
		return json(page);
	}

	const batchMatch = /^\/v1\/batches\/([^/]+)$/.exec(url.pathname);
	if (method === 'GET' && batchMatch) {
		const batch = batches.get(batchMatch[1] ?? '');
		if (!batch) return errorResponse(404, 'Batch not found.');
		return json(batchProgress(batch));
	}

	if (method === 'GET' && url.pathname === '/v1/recipes') {
		const limit = Number(url.searchParams.get('limit') ?? 50);
		const offset = Number(url.searchParams.get('offset') ?? 0);
		const page: RecipeList = {
			items: recipes.slice(offset, offset + limit),
			total: recipes.length,
			limit,
			offset
		};
		return json(page);
	}

	if (method === 'POST' && url.pathname === '/v1/recipes') {
		const payload = body as { name?: unknown; description?: unknown; spec?: unknown } | undefined;
		if (typeof payload?.name !== 'string' || payload.name.length === 0) {
			return errorResponse(422, 'name: Field required');
		}
		if (recipes.some((recipe) => recipe.name === payload.name)) {
			return errorResponse(409, 'Recipe name already exists.');
		}
		const { spec, error } = validateSpecBody(payload.spec);
		if (!spec) return errorResponse(422, error ?? 'Invalid spec.');
		const now = new Date().toISOString();
		const recipe: RecipeRead = {
			id: `recipe-${String(recipes.length + 1).padStart(4, '0')}`,
			name: payload.name,
			description: typeof payload.description === 'string' ? payload.description : null,
			spec,
			created_at: now,
			updated_at: now
		};
		recipes = [...recipes, recipe];
		return json(recipe, 201);
	}

	const recipeMatch = /^\/v1\/recipes\/([^/]+)$/.exec(url.pathname);
	if (recipeMatch) {
		const recipe = recipes.find((candidate) => candidate.id === recipeMatch[1]);
		if (!recipe) return errorResponse(404, 'Recipe not found.');
		if (method === 'GET') return json(recipe);
		if (method === 'PUT') {
			const payload = body as { name?: unknown; description?: unknown; spec?: unknown } | undefined;
			const updated: RecipeRead = { ...recipe, updated_at: new Date().toISOString() };
			if (typeof payload?.name === 'string' && payload.name.length > 0) {
				updated.name = payload.name;
			}
			if (payload?.description !== undefined) {
				updated.description = typeof payload.description === 'string' ? payload.description : null;
			}
			if (payload?.spec !== undefined) {
				const { spec, error } = validateSpecBody(payload.spec);
				if (!spec) return errorResponse(422, error ?? 'Invalid spec.');
				updated.spec = spec;
			}
			recipes = recipes.map((candidate) => (candidate.id === updated.id ? updated : candidate));
			return json(updated);
		}
	}

	const runMatch = /^\/v1\/recipes\/([^/]+)\/run$/.exec(url.pathname);
	if (method === 'POST' && runMatch) {
		const recipe = recipes.find((candidate) => candidate.id === runMatch[1]);
		if (!recipe) return errorResponse(404, 'Recipe not found.');
		return json(submitResponse(createJob(recipe.spec, undefined, recipe.id)), 202);
	}

	return errorResponse(404, `No mock route for ${method} ${url.pathname}.`);
}

export async function mockFetch(path: string, init: RequestInit = {}): Promise<Response> {
	await sleep(LATENCY_MS);
	return handle(path, init);
}

resetMock();
