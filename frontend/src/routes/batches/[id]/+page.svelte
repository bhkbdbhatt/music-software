<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft, ChevronRight } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api } from '#lib/api/client.js';
	import { statusLabel, statusTone } from '#lib/api/status.js';
	import { Poller } from '#lib/api/poll.svelte.js';
	import type { BatchProgressResponse } from '#lib/api/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const batchId = $derived(page.params.id ?? '');

	let poller = $state<Poller<BatchProgressResponse> | null>(null);

	const progress = $derived(poller?.data ?? null);
	const error = $derived(poller?.error ?? '');
	const results = $derived(progress?.results ?? []);
	const pending = $derived(
		progress !== null && progress.completed + progress.failed < progress.total
	);

	$effect(() => {
		const id = batchId;
		const current = new Poller(
			() => api.getBatch(id),
			1000,
			(data) => data.completed + data.failed >= data.total
		);
		poller = current;
		current.start();
		return () => current.destroy();
	});
</script>

<svelte:head><title>Batch {batchId} — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<a
		href="/batches"
		class="mb-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
	>
		<ArrowLeft size={13} /> All batches
	</a>
	<div class="flex flex-wrap items-center gap-3">
		<h2 class="font-mono text-lg font-semibold tracking-tight">{batchId}</h2>
		{#if pending}
			<span class="flex items-center gap-2 text-sm text-muted-foreground">
				<Spinner size={14} /> Running…
			</span>
		{/if}
		{#if progress}
			<span class="text-sm text-muted-foreground tabular-nums">
				{progress.completed} completed · {progress.failed} failed · {progress.total} total
			</span>
		{/if}
	</div>
	{#if error}
		<p class="mt-2 text-sm text-destructive" role="alert">{error}</p>
	{/if}
</section>

{#if progress}
	<div class="mb-4 h-2 overflow-hidden rounded-full bg-muted">
		<div
			class="h-full rounded-full bg-primary transition-all"
			style="width: {Math.round(
				((progress.completed + progress.failed) / Math.max(1, progress.total)) * 100
			)}%"
		></div>
	</div>

	<div class="overflow-x-auto rounded-lg border border-border bg-card">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs text-muted-foreground">
					<th class="px-3 py-2 font-medium">#</th>
					<th class="px-3 py-2 font-medium">Status</th>
					<th class="px-3 py-2 font-medium">Job</th>
					<th class="px-3 py-2 font-medium">Files</th>
					<th class="px-3 py-2 font-medium"></th>
				</tr>
			</thead>
			<tbody>
				{#each results as result, index (result.job_id)}
					<tr class="border-b border-border last:border-0 hover:bg-muted/40">
						<td class="px-3 py-2 text-xs text-muted-foreground tabular-nums">{index + 1}</td>
						<td class="px-3 py-2">
							<Badge tone={statusTone(result.status)}>{statusLabel(result.status)}</Badge>
						</td>
						<td class="max-w-48 truncate px-3 py-2 font-mono text-xs">{result.job_id}</td>
						<td class="px-3 py-2 text-xs text-muted-foreground">
							{result.files?.length ?? 0}
						</td>
						<td class="px-3 py-2 text-right">
							<a
								href="/jobs/{result.job_id}"
								aria-label="Open job {result.job_id}"
								class="inline-flex rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
							>
								<ChevronRight size={16} />
							</a>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}
