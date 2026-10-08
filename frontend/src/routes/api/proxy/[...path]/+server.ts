import { BACKEND_URL } from '$app/env/private';
import type { RequestHandler } from './$types';

const REQUEST_HEADERS_TO_DROP = ['host', 'content-length', 'accept-encoding'];
const RESPONSE_HEADERS_TO_DROP = [
	'content-encoding',
	'transfer-encoding',
	'connection',
	'keep-alive'
];

async function proxy(request: Request, path: string): Promise<Response> {
	const base = BACKEND_URL.replace(/\/+$/, '');
	const url = new URL(request.url);

	const headers = new Headers(request.headers);
	for (const name of REQUEST_HEADERS_TO_DROP) headers.delete(name);

	const init: RequestInit = { method: request.method, headers, redirect: 'follow' };
	if (request.method !== 'GET' && request.method !== 'HEAD') {
		init.body = await request.arrayBuffer();
	}

	try {
		const upstream = await fetch(`${base}/${path}${url.search}`, init);
		const responseHeaders = new Headers(upstream.headers);
		for (const name of RESPONSE_HEADERS_TO_DROP) responseHeaders.delete(name);
		if (upstream.headers.get('content-encoding')) responseHeaders.delete('content-length');

		return new Response(upstream.body, {
			status: upstream.status,
			statusText: upstream.statusText,
			headers: responseHeaders
		});
	} catch (error) {
		console.error('api proxy: backend unreachable', error);
		return new Response(JSON.stringify({ detail: 'backend unreachable' }), {
			status: 502,
			headers: { 'content-type': 'application/json' }
		});
	}
}

export const GET: RequestHandler = ({ request, params }) => proxy(request, params.path);
export const HEAD: RequestHandler = ({ request, params }) => proxy(request, params.path);
export const POST: RequestHandler = ({ request, params }) => proxy(request, params.path);
export const PUT: RequestHandler = ({ request, params }) => proxy(request, params.path);
export const PATCH: RequestHandler = ({ request, params }) => proxy(request, params.path);
export const DELETE: RequestHandler = ({ request, params }) => proxy(request, params.path);
