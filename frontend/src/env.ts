import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	BACKEND_URL: {
		description: 'Origin of the SampleForge backend used by the dev proxy (/api/proxy/*)',
		schema: (value) => value ?? 'http://127.0.0.1:8000'
	},
	VITE_MOCK_API: {
		description: 'Whether the app talks to the built-in mock API instead of a backend',
		public: true,
		schema: (value) => value === 'true'
	}
});
