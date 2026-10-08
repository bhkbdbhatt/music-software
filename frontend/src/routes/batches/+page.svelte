<script lang="ts">
	import { ChevronRight, Layers } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api } from '#lib/api/client.js';
	import { Poller } from '#lib/api/poll.svelte.js';
	import type { BatchList } from '#lib/api/types.js';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const LIMIT = 10;

	let offset = $state(0);
	let poller = $state<Poller<BatchList> | null>(null);

	const batches = $derived(poller?.data ?? null);
	const items = $derived(batches?.items ?? []);
	const total = $derived(batches?.total ?? 0);
	const loadError = $derived(poller?.error ?? '');

	$effect(() => {
		const current = new Poller(
			() => api.listBatches({ limit: LIMIT, offset }),
			3000,
			(data) => (data.items ?? []).every((item) => item.completed + item.failed >= item.total)
		);
		poller = current;
		current.start();
		return () => current.destroy();
	});

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
</script>

<svelte:head><title>Batches — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<h2 class="text-lg font-semibold tracking-tight">Batches</h2>
	<p class="mt-1 text-sm text-muted-foreground">Groups of jobs submitted together.</p>
</section>

{#if loadError}
	<div
		class="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
		role="alert"
	>
		{loadError}
	</div>
{/if}

{#if batches && items.length === 0}
	<EmptyState
		icon={Layers}
		title="No batches yet"
		description="Submit several specs together from the batch API."
	/>
{:else if batches}
	<div class="space-y-3">
		{#each items as batch (batch.batch_id)}
			<a
				href="/batches/{batch.batch_id}"
				class="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card px-4 py-3 hover:bg-muted/40"
			>
				<span class="font-mono text-sm">{batch.batch_id}</span>
				<span class="text-xs text-muted-foreground">{formatDate(batch.created_at)}</span>
				<span class="ml-auto flex items-center gap-3">
					{#if batch.failed > 0}
						<span class="text-xs text-destructive">{batch.failed} failed</span>
					{/if}
					<span class="text-xs text-muted-foreground tabular-nums">
						{batch.completed}/{batch.total} done
					</span>
					<span class="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
						<span
							class="block h-full rounded-full bg-primary transition-all"
							style="width: {Math.round((batch.completed / Math.max(1, batch.total)) * 100)}%"
						></span>
					</span>
					<ChevronRight size={16} class="text-muted-foreground" />
				</span>
			</a>
		{/each}
	</div>

	<div class="mt-4 flex items-center justify-between gap-3 text-sm">
		<button
			type="button"
			class="rounded-md border border-border px-3 py-1.5 text-muted-foreground hover:bg-muted disabled:opacity-40"
			disabled={offset === 0}
			onclick={() => (offset = Math.max(0, offset - LIMIT))}
		>
			Previous
		</button>
		<span class="text-xs text-muted-foreground">
			{offset + 1}–{Math.min(offset + LIMIT, total)} of {total}
		</span>
		<button
			type="button"
			class="rounded-md border border-border px-3 py-1.5 text-muted-foreground hover:bg-muted disabled:opacity-40"
			disabled={offset + LIMIT >= total}
			onclick={() => (offset += LIMIT)}
		>
			Next
		</button>
	</div>
{:else}
	<div class="flex items-center gap-2 text-sm text-muted-foreground">
		<Spinner size={14} /> Loading batches…
	</div>
{/if}
