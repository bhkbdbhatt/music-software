<script lang="ts">
	import { page } from '$app/state';
	import { ArrowLeft, Download, FileAudio } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api } from '#lib/api/client.js';
	import { isActiveStatus, statusLabel, statusTone } from '#lib/api/status.js';
	import { Poller } from '#lib/api/poll.svelte.js';
	import type { GenerationResponse } from '#lib/api/types.js';
	import { formatTime } from '#lib/audio/format.js';
	import PanelWorkspace from '#lib/panels/PanelWorkspace.svelte';
	import Badge from '#lib/components/ui/Badge.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	const jobId = $derived(page.params.id ?? '');

	let poller = $state<Poller<GenerationResponse> | null>(null);

	const response = $derived(poller?.data ?? null);
	const status = $derived(response?.status ?? null);
	const files = $derived(response?.files ?? []);
	const error = $derived(poller?.error ?? '');
	const waiting = $derived(status !== null && isActiveStatus(status));

	$effect(() => {
		const current = new Poller(
			() => api.getJob(jobId),
			800,
			(data) => !isActiveStatus(data.status)
		);
		poller = current;
		current.start();
		return () => current.destroy();
	});
</script>

<svelte:head><title>Job {jobId} — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<a
		href="/jobs"
		class="mb-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
	>
		<ArrowLeft size={13} /> All jobs
	</a>
	<div class="flex flex-wrap items-center gap-3">
		<h2 class="font-mono text-lg font-semibold tracking-tight">{jobId}</h2>
		{#if status}
			<Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
		{/if}
		{#if waiting}
			<span class="flex items-center gap-2 text-sm text-muted-foreground">
				<Spinner size={14} /> Working…
			</span>
		{/if}
	</div>
	{#if error}
		<p class="mt-2 text-sm text-destructive" role="alert">{error}</p>
	{/if}
</section>

{#if files.length > 0}
	<section class="mb-6 rounded-lg border border-border bg-card">
		<h3 class="border-b border-border px-4 py-2.5 text-sm font-medium">Files</h3>
		<ul>
			{#each files as file, index (index)}
				<li
					class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5 last:border-0"
				>
					<FileAudio size={15} class="shrink-0 text-muted-foreground" />
					<span class="text-sm">Variant {index + 1}</span>
					<span class="text-xs text-muted-foreground tabular-nums">
						{file.duration_ms != null ? formatTime(file.duration_ms) : '—'}
						{file.peak_db != null ? ` · ${file.peak_db.toFixed(1)} dBFS` : ''}
					</span>
					<a
						href={file.url}
						download="{jobId}-{index + 1}.wav"
						class="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
					>
						<Download size={13} /> Download
					</a>
				</li>
			{/each}
		</ul>
	</section>
{/if}

<PanelWorkspace {response} storageKey="job" />
