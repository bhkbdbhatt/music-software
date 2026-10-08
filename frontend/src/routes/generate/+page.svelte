<script lang="ts">
	import { onDestroy } from 'svelte';
	import { WandSparkles } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api, errorMessage } from '#lib/api/client.js';
	import { isActiveStatus, statusLabel, statusTone } from '#lib/api/status.js';
	import { Poller } from '#lib/api/poll.svelte.js';
	import { defaultSpec, validateSpec } from '#lib/spec/spec.js';
	import type { GenerationResponse, GenerationSpec } from '#lib/api/types.js';
	import SpecForm from '#lib/components/spec/SpecForm.svelte';
	import PanelWorkspace from '#lib/panels/PanelWorkspace.svelte';
	import Badge from '#lib/components/ui/Badge.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let spec = $state<GenerationSpec>(defaultSpec());
	let attempted = $state(false);
	let submitting = $state(false);
	let submitError = $state('');
	let submittedSpec = $state<GenerationSpec | null>(null);
	let poller = $state<Poller<GenerationResponse> | null>(null);

	const errors = $derived(attempted ? validateSpec(spec) : {});
	const response = $derived(poller?.data ?? null);
	const pollError = $derived(poller?.error ?? '');
	const status = $derived(response?.status ?? null);
	const waiting = $derived(
		submitting || (status !== null && isActiveStatus(status)) || (poller?.loading ?? false)
	);

	onDestroy(() => {
		poller?.destroy();
	});

	async function submit(): Promise<void> {
		attempted = true;
		submitError = '';
		const found = validateSpec(spec);
		if (Object.keys(found).length > 0) return;
		submitting = true;
		try {
			const submitted = await api.generate(spec);
			submittedSpec = structuredClone(spec);
			poller?.destroy();
			poller = new Poller(
				() => api.getJob(submitted.job_id),
				800,
				(data) => !isActiveStatus(data.status)
			);
			poller.start();
		} catch (cause) {
			submitError = errorMessage(cause);
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head><title>Generate — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<h2 class="text-lg font-semibold tracking-tight">Generate</h2>
	<p class="mt-1 text-sm text-muted-foreground">Compose a generation spec and submit a job.</p>
</section>

<form
	class="rounded-lg border border-border bg-card p-4"
	onsubmit={(event) => {
		event.preventDefault();
		void submit();
	}}
>
	<SpecForm bind:spec {errors} />

	<div class="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
		<Button type="submit" variant="primary" loading={submitting} disabled={waiting}>
			<WandSparkles size={15} /> Generate
		</Button>

		{#if waiting}
			<span class="flex items-center gap-2 text-sm text-muted-foreground">
				<Spinner size={14} />
				{status ? statusLabel(status) : 'Submitting…'}
			</span>
		{/if}

		{#if status && !waiting}
			<Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
		{/if}

		{#if submitError}
			<span class="text-sm text-destructive" role="alert">{submitError}</span>
		{/if}
		{#if pollError}
			<span class="text-sm text-destructive" role="alert">{pollError}</span>
		{/if}
	</div>
</form>

<div class="mt-6">
	<PanelWorkspace spec={submittedSpec} {response} storageKey="generate" />
</div>
