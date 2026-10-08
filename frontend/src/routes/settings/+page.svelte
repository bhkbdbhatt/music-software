<script lang="ts">
	import { onMount } from 'svelte';
	import { VITE_MOCK_API } from '$app/env/public';
	import { Braces, RefreshCw, ShieldCheck } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { DEFAULT_API_KEY, api, errorMessage, getApiKey, setApiKey } from '#lib/api/client.js';
	import type { HealthResponse } from '#lib/api/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Field from '#lib/components/ui/Field.svelte';
	import Input from '#lib/components/ui/Input.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let apiKeyInput = $state('');
	let keySaved = $state(false);
	let health = $state<HealthResponse | null>(null);
	let healthError = $state('');
	let checking = $state(false);

	async function checkHealth(): Promise<void> {
		checking = true;
		healthError = '';
		try {
			health = await api.health();
		} catch (cause) {
			health = null;
			healthError = errorMessage(cause);
		} finally {
			checking = false;
		}
	}

	function saveKey(): void {
		const trimmed = apiKeyInput.trim();
		setApiKey(trimmed.length > 0 ? trimmed : DEFAULT_API_KEY);
		apiKeyInput = getApiKey();
		keySaved = true;
	}

	onMount(() => {
		apiKeyInput = getApiKey();
		void checkHealth();
	});
</script>

<svelte:head><title>Settings — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<h2 class="text-lg font-semibold tracking-tight">Settings</h2>
	<p class="mt-1 text-sm text-muted-foreground">
		API connection, theme, and workspace preferences.
	</p>
</section>

<div class="grid max-w-3xl gap-6">
	<section class="rounded-lg border border-border bg-card p-4">
		<h3 class="mb-3 text-sm font-medium">API connection</h3>
		<div class="flex flex-wrap items-end gap-3">
			<div class="min-w-64 flex-1">
				<Field label="API key" hint="Sent as X-API-Key on every request." for="api-key">
					<Input
						id="api-key"
						type="password"
						value={apiKeyInput}
						oninput={(event) => {
							apiKeyInput = (event.currentTarget as HTMLInputElement).value;
							keySaved = false;
						}}
					/>
				</Field>
			</div>
			<Button variant="primary" onclick={saveKey}>
				{#if keySaved}Saved{:else}Save key{/if}
			</Button>
		</div>
		{#if apiKeyInput === DEFAULT_API_KEY}
			<p class="mt-2 text-xs text-warning">Using the development default key.</p>
		{/if}
	</section>

	<section class="rounded-lg border border-border bg-card p-4">
		<div class="mb-3 flex items-center justify-between gap-3">
			<h3 class="text-sm font-medium">Backend status</h3>
			<Button variant="outline" size="sm" loading={checking} onclick={() => void checkHealth()}>
				<RefreshCw size={13} /> Check
			</Button>
		</div>

		{#if checking && !health}
			<div class="flex items-center gap-2 text-sm text-muted-foreground">
				<Spinner size={14} /> Contacting backend…
			</div>
		{:else if healthError}
			<div class="flex items-start gap-2 text-sm text-destructive" role="alert">
				<ShieldCheck size={15} class="mt-0.5 shrink-0" />
				<span>Backend unreachable: {healthError}</span>
			</div>
		{:else if health}
			<dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
				<div class="flex items-center justify-between gap-2 sm:block">
					<dt class="text-xs text-muted-foreground">Status</dt>
					<dd>
						<Badge tone={health.status === 'ok' ? 'success' : 'warning'}>{health.status}</Badge>
					</dd>
				</div>
				<div class="flex items-center justify-between gap-2 sm:block">
					<dt class="text-xs text-muted-foreground">Model</dt>
					<dd>{health.model_loaded ? 'loaded' : 'not loaded'}</dd>
				</div>
				<div class="flex items-center justify-between gap-2 sm:block">
					<dt class="text-xs text-muted-foreground">GPU</dt>
					<dd>{health.gpu_available ? 'available' : 'unavailable'}</dd>
				</div>
				<div class="flex items-center justify-between gap-2 sm:block">
					<dt class="text-xs text-muted-foreground">Queue depth</dt>
					<dd class="tabular-nums">{health.queue_depth ?? '—'}</dd>
				</div>
				<div class="flex items-center justify-between gap-2 sm:block">
					<dt class="text-xs text-muted-foreground">Version</dt>
					<dd class="font-mono text-xs">{health.version}</dd>
				</div>
			</dl>
		{/if}
	</section>

	<section class="rounded-lg border border-border bg-card p-4">
		<h3 class="mb-2 text-sm font-medium">Data source</h3>
		<div class="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
			<Braces size={15} />
			{#if VITE_MOCK_API}
				<Badge tone="info">Mock API</Badge>
				<span>Requests are answered in-browser; no backend needed.</span>
			{:else}
				<Badge tone="neutral">Live backend</Badge>
				<span>Requests proxy to the SampleForge API.</span>
			{/if}
		</div>
	</section>

	<section class="rounded-lg border border-border bg-card p-4">
		<h3 class="mb-2 text-sm font-medium">Theme</h3>
		<p class="text-sm text-muted-foreground">
			Use the toggle in the top bar to switch between light, dark, and system themes. The workspace
			remembers your panel layout per page automatically.
		</p>
	</section>
</div>
