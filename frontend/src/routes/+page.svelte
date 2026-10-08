<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { ChevronRight, Layers, ScrollText, WandSparkles } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api, errorMessage } from '#lib/api/client.js';
	import { statusLabel, statusTone } from '#lib/api/status.js';
	import type { BatchList, HealthResponse, JobList } from '#lib/api/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let health = $state<HealthResponse | null>(null);
	let jobs = $state<JobList | null>(null);
	let batches = $state<BatchList | null>(null);
	let loading = $state(true);
	let loadError = $state('');

	async function refresh(): Promise<void> {
		loading = true;
		loadError = '';
		try {
			const [healthResult, jobsResult, batchesResult] = await Promise.allSettled([
				api.health(),
				api.listJobs({ limit: 5 }),
				api.listBatches({ limit: 5 })
			]);
			health = healthResult.status === 'fulfilled' ? healthResult.value : null;
			jobs = jobsResult.status === 'fulfilled' ? jobsResult.value : null;
			batches = batchesResult.status === 'fulfilled' ? batchesResult.value : null;
			const firstFailure = [healthResult, jobsResult, batchesResult].find(
				(result) => result.status === 'rejected'
			);
			loadError =
				firstFailure && firstFailure.status === 'rejected' ? errorMessage(firstFailure.reason) : '';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void refresh();
	});
</script>

<svelte:head><title>Dashboard — {APP_NAME}</title></svelte:head>

<section class="mb-6 flex flex-wrap items-center gap-3">
	<div class="min-w-0 flex-1">
		<h2 class="text-lg font-semibold tracking-tight">Dashboard</h2>
		<p class="mt-1 text-sm text-muted-foreground">
			Recent jobs, batch activity, and quick actions.
		</p>
	</div>
	<div class="flex items-center gap-2">
		{#if health}
			<Badge tone={health.status === 'ok' ? 'success' : 'warning'}>
				backend {health.status}
			</Badge>
		{/if}
		<Button variant="outline" onclick={() => void refresh()} {loading}>Refresh</Button>
		<Button variant="primary" onclick={() => goto('/generate')}>
			<WandSparkles size={15} /> New generation
		</Button>
	</div>
</section>

{#if loadError}
	<div
		class="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
		role="alert"
	>
		{loadError}
	</div>
{/if}

<div class="grid gap-6 lg:grid-cols-2">
	<section class="rounded-lg border border-border bg-card">
		<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
			<h3 class="text-sm font-medium">Recent jobs</h3>
			<a href="/jobs" class="text-xs text-primary hover:underline">View all</a>
		</div>
		{#if loading && !jobs}
			<div class="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
				<Spinner size={14} /> Loading…
			</div>
		{:else if (jobs?.items ?? []).length === 0}
			<p class="px-4 py-6 text-sm text-muted-foreground">No jobs yet.</p>
		{:else}
			<ul class="divide-y divide-border">
				{#each jobs?.items ?? [] as item (item.job_id)}
					<li>
						<a
							href="/jobs/{item.job_id}"
							class="flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40"
						>
							<Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
							<span class="min-w-0 flex-1 truncate font-mono text-xs">{item.job_id}</span>
							<span class="text-xs text-muted-foreground">
								{item.spec ? item.spec.category : ''}
							</span>
							<ChevronRight size={14} class="text-muted-foreground" />
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="rounded-lg border border-border bg-card">
		<div class="flex items-center justify-between border-b border-border px-4 py-2.5">
			<h3 class="text-sm font-medium">Batch activity</h3>
			<a href="/batches" class="text-xs text-primary hover:underline">View all</a>
		</div>
		{#if loading && !batches}
			<div class="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
				<Spinner size={14} /> Loading…
			</div>
		{:else if (batches?.items ?? []).length === 0}
			<div class="px-4 py-6">
				<p class="text-sm text-muted-foreground">No batches yet.</p>
				<a
					href="/recipes"
					class="mt-1 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
				>
					<ScrollText size={14} /> Browse recipes
				</a>
			</div>
		{:else}
			<ul class="divide-y divide-border">
				{#each batches?.items ?? [] as batch (batch.batch_id)}
					<li>
						<a
							href="/batches/{batch.batch_id}"
							class="flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40"
						>
							<Layers size={14} class="shrink-0 text-muted-foreground" />
							<span class="min-w-0 flex-1 truncate font-mono text-xs">{batch.batch_id}</span>
							<span class="text-xs text-muted-foreground tabular-nums">
								{batch.completed}/{batch.total}
							</span>
							<ChevronRight size={14} class="text-muted-foreground" />
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>
