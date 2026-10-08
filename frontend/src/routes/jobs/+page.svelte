<script lang="ts">
	import { onMount } from 'svelte';
	import { ChevronRight, ListChecks } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api } from '#lib/api/client.js';
	import { isActiveStatus, statusLabel, statusTone } from '#lib/api/status.js';
	import { Poller } from '#lib/api/poll.svelte.js';
	import type { JobList, JobStatus } from '#lib/api/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import Select from '#lib/components/ui/Select.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const LIMIT = 10;

	let offset = $state(0);
	let statusFilter = $state('');
	let poller = $state<Poller<JobList> | null>(null);

	const jobs = $derived(poller?.data ?? null);
	const items = $derived(jobs?.items ?? []);
	const total = $derived(jobs?.total ?? 0);
	const loadError = $derived(poller?.error ?? '');
	const refreshing = $derived(poller?.loading ?? false);
	const statusOptions = [
		{ value: '', label: 'All statuses' },
		{ value: 'queued', label: 'Queued' },
		{ value: 'processing', label: 'Processing' },
		{ value: 'complete', label: 'Complete' },
		{ value: 'complete_with_warnings', label: 'Warnings' },
		{ value: 'failed', label: 'Failed' }
	];

	$effect(() => {
		const current = new Poller(
			() =>
				api.listJobs({ limit: LIMIT, offset, status: (statusFilter || null) as JobStatus | null }),
			2000,
			(data) => !(data.items ?? []).some((item) => isActiveStatus(item.status))
		);
		poller = current;
		current.start();
		return () => current.destroy();
	});

	onMount(() => () => poller?.destroy());

	function changeStatus(value: string): void {
		statusFilter = value;
		offset = 0;
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
</script>

<svelte:head><title>Jobs — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<h2 class="text-lg font-semibold tracking-tight">Jobs</h2>
	<p class="mt-1 text-sm text-muted-foreground">All generation jobs, newest first.</p>
</section>

<div class="mb-4 flex flex-wrap items-center gap-3">
	<label for="job-status" class="text-xs font-medium text-muted-foreground">Status</label>
	<Select
		id="job-status"
		options={statusOptions}
		value={statusFilter}
		onchange={(event) =>
			changeStatus((event.currentTarget as HTMLSelectElement | null)?.value ?? '')}
		class="w-44"
	/>
	{#if refreshing}
		<span class="flex items-center gap-2 text-xs text-muted-foreground">
			<Spinner size={13} /> Refreshing
		</span>
	{/if}
	<span class="ml-auto text-xs text-muted-foreground">{total} total</span>
</div>

{#if loadError}
	<div
		class="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
		role="alert"
	>
		{loadError}
	</div>
{/if}

{#if jobs && items.length === 0}
	<EmptyState
		icon={ListChecks}
		title="No jobs match"
		description="Adjust the status filter or submit a generation."
	/>
{:else if jobs}
	<div class="overflow-x-auto rounded-lg border border-border bg-card">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs text-muted-foreground">
					<th class="px-3 py-2 font-medium">Status</th>
					<th class="px-3 py-2 font-medium">Job</th>
					<th class="px-3 py-2 font-medium">Spec</th>
					<th class="px-3 py-2 font-medium">Batch</th>
					<th class="px-3 py-2 font-medium">Created</th>
					<th class="px-3 py-2 font-medium"></th>
				</tr>
			</thead>
			<tbody>
				{#each items as item (item.job_id)}
					<tr class="border-b border-border last:border-0 hover:bg-muted/40">
						<td class="px-3 py-2">
							<Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
						</td>
						<td class="max-w-40 truncate px-3 py-2 font-mono text-xs">{item.job_id}</td>
						<td class="px-3 py-2">
							{item.spec ? `${item.spec.category} · ${item.spec.type}` : '—'}
						</td>
						<td class="px-3 py-2">
							{#if item.batch_id}
								<a
									href="/batches/{item.batch_id}"
									class="font-mono text-xs text-primary hover:underline">{item.batch_id}</a
								>
							{:else}
								—
							{/if}
						</td>
						<td class="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">
							{formatDate(item.created_at)}
						</td>
						<td class="px-3 py-2 text-right">
							<a
								href="/jobs/{item.job_id}"
								aria-label="Open job {item.job_id}"
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
		<Spinner size={14} /> Loading jobs…
	</div>
{/if}
