<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();

	function humanize(key: string): string {
		return key.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
	}

	const entries = $derived(Object.entries(context.response?.constraints_met ?? {}));
</script>

{#if entries.length === 0}
	<EmptyState
		title="No verdicts yet"
		description="Per-constraint pass/fail results appear when the job finishes."
	/>
{:else}
	<ul class="flex flex-wrap gap-2">
		{#each entries as [key, ok] (key)}
			<li class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5">
				<span class="text-xs">{humanize(key)}</span>
				{#if ok}
					<Badge tone="success">met</Badge>
				{:else}
					<Badge tone="danger">missed</Badge>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
