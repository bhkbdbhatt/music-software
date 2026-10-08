<script lang="ts">
	import type { PanelContext, JobStatus } from '#lib/panels/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();

	function tone(status: JobStatus): 'neutral' | 'info' | 'success' | 'warning' | 'danger' {
		switch (status) {
			case 'complete':
				return 'success';
			case 'complete_with_warnings':
				return 'warning';
			case 'failed':
				return 'danger';
			case 'processing':
				return 'info';
			default:
				return 'neutral';
		}
	}

	const response = $derived(context.response);
	const files = $derived(response?.files ?? []);
</script>

{#if response}
	<dl class="space-y-2">
		<div class="flex items-center justify-between gap-3">
			<dt class="text-xs text-muted-foreground">Job</dt>
			<dd class="truncate font-mono text-xs" title={response.job_id}>{response.job_id}</dd>
		</div>
		<div class="flex items-center justify-between gap-3">
			<dt class="text-xs text-muted-foreground">Status</dt>
			<dd><Badge tone={tone(response.status)}>{response.status}</Badge></dd>
		</div>
		<div class="flex items-center justify-between gap-3">
			<dt class="text-xs text-muted-foreground">Variants</dt>
			<dd class="text-xs tabular-nums">{files.length}</dd>
		</div>
		{#if response.spec}
			<div class="flex items-center justify-between gap-3">
				<dt class="text-xs text-muted-foreground">Category</dt>
				<dd class="text-xs">{response.spec.category} · {response.spec.type}</dd>
			</div>
		{/if}
		{#each files as file, index (index)}
			<div class="flex items-center justify-between gap-3">
				<dt class="text-xs text-muted-foreground">Variant {index + 1}</dt>
				<dd class="min-w-0">
					<a
						href={file.url}
						class="block max-w-56 truncate text-xs text-primary hover:underline"
						title={file.url}>{file.url}</a
					>
				</dd>
			</div>
		{/each}
	</dl>
{:else}
	<EmptyState title="No metadata" description="Job details appear once submitted." />
{/if}
